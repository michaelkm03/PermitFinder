"""
wa-permits CLI

Find multi-night backpacking chains where every campsite has available permits.

Usage examples
--------------
  # Show all possible 5-night chains for North Cascades (mock data):
  wa-permits north-cascades --start-date 2026-07-15 --nights 5

  # Same query against real-time Recreation.gov availability:
  wa-permits north-cascades --start-date 2026-07-15 --nights 5 --live

  # Only show chains with at least 2 permits available on every night:
  wa-permits north-cascades --start-date 2026-07-15 --nights 5 --live \\
      --permit-count 2 --available

  # Include trailhead-connected routes (separate trails sharing a parking lot):
  wa-permits rainier --start-date 2026-07-22 --nights 7 --trailhead
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta

from permit_engine.graph import build_graph
from permit_engine.search import Chain, filter_by_availability, find_chains

# ---------------------------------------------------------------------------
# Supported parks
# ---------------------------------------------------------------------------

PARKS: dict[str, dict] = {
    "rainier": {
        "display_name": "Mount Rainier",
        "facility_id": "4675317",
        # (south_lat, west_lon, north_lat, east_lon)
        "bbox": (46.70, -122.05, 47.12, -121.47),
    },
    "north-cascades": {
        "display_name": "North Cascades",
        "facility_id": "4675322",
        "bbox": (48.35, -121.75, 49.05, -120.40),
    },
    "olympic": {
        "display_name": "Olympic National Park",
        "facility_id": "4098362",
        "bbox": (47.20, -124.80, 48.20, -122.90),
    },
}

# ANSI colour codes — only rendered when output is a real terminal.
_BOLD   = "\033[1m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_DIM    = "\033[2m"
_RESET  = "\033[0m"


def main() -> int:
    args = _parse_args()
    park = PARKS[args.park]

    # Select data source: live API or built-in mock data.
    if args.live:
        from permit_engine import api as data_source
    else:
        from permit_engine import mock as data_source

    print(f"\n{_BOLD}Park    :{_RESET} {park['display_name']}")
    print(f"{_BOLD}Date    :{_RESET} {args.start_date} → {args.start_date + timedelta(days=args.nights - 1)}")
    print(f"{_BOLD}Nights  :{_RESET} {args.nights}")
    print(f"{_BOLD}Source  :{_RESET} {'live Recreation.gov + OpenStreetMap' if args.live else 'mock data'}")
    if args.available:
        print(f"{_BOLD}Filter  :{_RESET} chains with >= {args.permit_count} permits on every night")
    if args.trailhead:
        print(f"{_BOLD}Trailhead connections:{_RESET} included")
    print()

    # Step 1 — build the trail graph from sites and OSM trails.
    print("Building trail graph...", end=" ", flush=True)
    raw_sites  = data_source.fetch_sites(park["facility_id"])
    raw_trails = data_source.fetch_trails(park["bbox"])
    graph = build_graph(raw_sites, raw_trails, allow_trailhead=args.trailhead)
    edge_count = sum(len(v) for v in graph.adjacency.values()) // 2
    print(f"{len(graph.sites)} sites, {edge_count} edges")

    # Step 2 — fetch per-night availability for every site in the graph.
    print("Fetching availability...", end=" ", flush=True)
    availability: dict[str, dict[str, int]] = {}
    for div_id in graph.sites:
        availability[div_id] = data_source.fetch_availability(
            park["facility_id"], div_id, args.start_date
        )
    print("done")

    # Step 3 — DFS to find all multi-night chains.
    chains = find_chains(graph, availability, args.start_date, args.nights)

    # Step 4 — apply --available filter when requested.
    if args.available:
        chains = filter_by_availability(chains, args.permit_count)

    if not chains:
        print(f"\n{_YELLOW}No chains found.{_RESET}")
        if args.available:
            print("  Try removing --available or lowering --permit-count.")
        return 0

    print(f"\nFound {_BOLD}{len(chains)}{_RESET} chain(s).\n")
    _print_summary_table(chains)
    _print_chain_details(chains)
    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="wa-permits",
        description="Find multi-night backpacking permit chains in Washington State parks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join([
            "parks:  " + ", ".join(PARKS.keys()),
            "",
            "examples:",
            "  wa-permits north-cascades --start-date 2026-07-15 --nights 5",
            "  wa-permits rainier --start-date 2026-07-22 --nights 7 --live",
            "  wa-permits olympic --start-date 2026-08-01 --nights 4 --live --permit-count 2 --available",
        ]),
    )
    parser.add_argument(
        "park",
        choices=list(PARKS.keys()),
        help="Park to search.",
    )
    parser.add_argument(
        "--start-date",
        required=True,
        type=_parse_date,
        metavar="YYYY-MM-DD",
        help="First night of the trip.",
    )
    parser.add_argument(
        "--nights",
        required=True,
        type=int,
        metavar="N",
        help="Number of nights.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help=(
            "Fetch real-time data from Recreation.gov and OpenStreetMap. "
            "Without this flag, built-in mock data is used."
        ),
    )
    parser.add_argument(
        "--permit-count",
        type=int,
        default=1,
        metavar="N",
        help="Permits needed (party size). Used with --available. Default: 1.",
    )
    parser.add_argument(
        "--available",
        action="store_true",
        default=False,
        help=(
            "Only show chains where every site has >= --permit-count permits "
            "remaining. Without this flag all chains are shown and availability "
            "counts are displayed for reference."
        ),
    )
    parser.add_argument(
        "--trailhead",
        action="store_true",
        default=False,
        help=(
            "Include connections between sites on separate trails that share "
            "a trailhead parking lot. Excluded by default because a hiker must "
            "leave the trail system to make this transition."
        ),
    )
    return parser.parse_args()


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}'. Expected YYYY-MM-DD.")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _print_summary_table(chains: list[Chain]) -> None:
    header = (
        f"  {'#':>4}  "
        f"{'Entry Site':<30}  "
        f"{'Exit Site':<30}  "
        f"{'Date Range':<23}  "
        f"{'Min Avail':>9}"
    )
    print(f"{_BOLD}{header}{_RESET}")
    print("  " + "─" * 100)

    for i, chain in enumerate(chains, 1):
        entry     = chain.links[0].site.name
        exit_     = chain.links[-1].site.name
        date_range = f"{chain.start_date} -> {chain.end_date}"
        min_avail  = chain.min_remaining()
        avail_str  = str(min_avail) if min_avail >= 0 else "--"
        colour = _GREEN if min_avail > 1 else (_YELLOW if min_avail == 1 else _RED)

        print(
            f"  {i:>4}  "
            f"{entry:<30}  "
            f"{exit_:<30}  "
            f"{date_range:<23}  "
            f"{colour}{avail_str:>9}{_RESET}"
        )
    print()


def _print_chain_details(chains: list[Chain]) -> None:
    for i, chain in enumerate(chains, 1):
        print(
            f"{_BOLD}Chain #{i}{_RESET}  "
            f"{chain.num_nights} nights  "
            f"{chain.start_date} -> {chain.end_date}"
        )
        print(f"  {_DIM}{'Night':>6}  {'Date':<12}  {'Site':<30}  {'Avail':>5}{_RESET}")
        print(f"  {'─' * 62}")

        for j, link in enumerate(chain.links, 1):
            avail = link.remaining
            if avail < 0:
                colour, avail_str = _DIM, f"{'--':>5}"
            elif avail == 0:
                colour, avail_str = _RED, f"{avail:>5}"
            elif avail == 1:
                colour, avail_str = _YELLOW, f"{avail:>5}"
            else:
                colour, avail_str = _GREEN, f"{avail:>5}"

            print(
                f"  {j:>6}  {link.night_date!s:<12}  "
                f"{link.site.name:<30}  "
                f"{colour}{avail_str}{_RESET}"
            )
        print()


if __name__ == "__main__":
    sys.exit(main())
