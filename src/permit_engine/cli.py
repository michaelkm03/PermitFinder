"""
wa-permits CLI

Find multi-night backpacking chains where every campsite has available permits.

Usage examples
--------------
  # List all supported park names:
  wa-permits --list-parks

  # Show all possible 5-night chains for North Cascades (mock data):
  wa-permits --park north-cascades --start-date 2026-07-15 --nights 5

  # Search multiple parks at once:
  wa-permits --park north-cascades olympic --start-date 2026-07-15 --nights 5 --live

  # Search all parks:
  wa-permits --park all --start-date 2026-07-15 --nights 5 --live

  # Only show chains with at least 2 permits available on every night:
  wa-permits --park north-cascades --start-date 2026-07-15 --nights 5 --live \\
      --permit-count 2 --available

  # Include trailhead-connected routes (separate trails sharing a parking lot):
  wa-permits --park rainier --start-date 2026-07-22 --nights 7 --trailhead

  # Limit results to the first 20 chains:
  wa-permits --park olympic --start-date 2026-07-15 --nights 5 --live --limit 20

  # Limit API calls to 1 district of sites (reduces traffic; use --limit to cap chains):
  wa-permits --park olympic --start-date 2026-07-15 --nights 5 --live --detail-limit 1

  # Show district names and site counts for a park (fast, no availability fetch):
  wa-permits --park olympic --list-areas
  wa-permits --park olympic --list-areas --live

  # Find multi-night permit chains with availability:
  wa-permits --park olympic --list-chains --start-date 2026-07-15 --nights 5
  wa-permits --park olympic --list-chains --start-date 2026-07-15 --nights 5 --live

  # Search only specific areas (case-insensitive substring match):
  wa-permits --park olympic --list-chains --start-date 2026-07-15 --nights 5 --live --area "Carbon River" "Mowich"

  # Output chain data as JSON (progress on stderr, clean JSON on stdout):
  wa-permits --park rainier --list-chains --start-date 2026-07-15 --nights 5 --json
  wa-permits --park all --list-chains --start-date 2026-07-15 --nights 5 --limit 50 --json > chains.json

  # Variable-length chains (1 through 5 nights), grouped longest-first:
  wa-permits --park rainier --list-chains --start-date 2026-07-15 --nights 5 --no-exact-length

  # Flat availability table (Facility / District / Division / remaining / date range):
  wa-permits --park olympic --list-availability --start-date 2026-07-15 --nights 5
  wa-permits --park olympic --list-availability --start-date 2026-07-15 --nights 5 --live
  wa-permits --park olympic --list-availability --start-date 2026-07-15 --nights 5 --live --area Hoh
  wa-permits --park all    --list-availability --start-date 2026-07-15 --nights 5
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone

# Ensure stdout is UTF-8 on Windows so Rich box-drawing and Unicode arrows render.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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
        # rec.gov permit booking system type (controls which availability API is called)
        "permit_type": "ITINERARY",
    },
    "north-cascades": {
        "display_name": "North Cascades",
        "facility_id": "4675322",
        "bbox": (48.35, -121.75, 49.05, -120.40),
        # NC made no availability calls in its HAR (fully pre-season); assumed permititinerary like the others
        "permit_type": "ITINERARY",
    },
    "olympic": {
        "display_name": "Olympic National Park",
        "facility_id": "4098362",
        "bbox": (47.20, -124.80, 48.20, -122.90),
        # HAR confirms Olympic uses permititinerary endpoint, same as Rainier
        "permit_type": "ITINERARY",
    },
    "enchantments": {
        "display_name": "Enchantments (Alpine Lakes Wilderness)",
        "facility_id": "445863",
        "bbox": (47.47, -121.00, 47.56, -120.65),
        # HAR confirms Enchantments uses permitinyo/availabilityv2 (zone-based, not per-division)
        "permit_type": "ZONE",
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

    # --list-parks: just print park keys and exit.
    if args.list_parks:
        print("\nSupported parks:")
        for key, park in PARKS.items():
            print(f"  {key:<20}  {park['display_name']}  ({park['permit_type']})")
        print()
        return 0

    # --list-areas: fast structural overview — site counts per district, no availability fetch.
    if getattr(args, "list_areas", False):
        if not args.park:
            print("--list-areas requires --park (or use --park all)", file=sys.stderr)
            return 1

        if args.live:
            from permit_engine import api as _la_ds
        else:
            from permit_engine import mock as _la_ds  # type: ignore[assignment]

        from rich.panel import Panel as _Panel
        park_keys_la = list(PARKS.keys()) if "all" in (args.park or []) else (args.park or [])
        for pk in park_keys_la:
            park_cfg = PARKS[pk]
            t0 = time.perf_counter()
            sites = _la_ds.fetch_sites(park_cfg["facility_id"])
            elapsed = time.perf_counter() - t0

            # Group sites by district.
            district_sites: dict[str, list[dict]] = {}
            for s in sites:
                d = (s.get("district") or "—").strip() or "—"
                district_sites.setdefault(d, []).append(s)

            _console.print(_Panel(
                f"[dim]{'live data' if args.live else 'mock data'}"
                f"  ·  {len(sites)} sites  ·  {len(district_sites)} district{'s' if len(district_sites) != 1 else ''}"
                f"  ·  {elapsed:.2f}s[/dim]",
                title=f"[bold yellow]{park_cfg['display_name']} — Areas[/bold yellow]",
                expand=False,
                border_style="yellow dim",
            ))

            tbl = Table(
                box=rich_box.SIMPLE_HEAD,
                show_header=True,
                header_style="bold dim",
                pad_edge=True,
            )
            tbl.add_column("Area (District)", min_width=32)
            tbl.add_column("Sites", justify="right", width=6)
            tbl.add_column("Node Types", min_width=20)

            for dist in sorted(district_sites):
                type_set = sorted({
                    (s.get("type") or "—").strip() or "—"
                    for s in district_sites[dist]
                })
                types_str = ", ".join(type_set)
                tbl.add_row(dist, str(len(district_sites[dist])), types_str)

            _console.print(tbl)
            _console.print(
                f"[dim]  Use --list-chains --start-date DATE --nights N to find permit chains "
                f"within these areas.[/dim]"
            )
            _console.print()
        return 0

    # --list-availability: human-readable permit availability per division.
    if getattr(args, "list_availability", False):
        if not args.park:
            print("--list-availability requires --park (or use --park all)", file=sys.stderr)
            return 1

        if args.live:
            from permit_engine import api as _av_ds
        else:
            from permit_engine import mock as _av_ds  # type: ignore[assignment]

        park_keys_av = list(PARKS.keys()) if "all" in (args.park or []) else (args.park or [])
        end_date     = args.start_date + timedelta(days=args.nights - 1)
        target_dates = sorted(
            (args.start_date + timedelta(days=d)).strftime("%Y-%m-%d")
            for d in range(args.nights)
        )
        # Short date labels for sparkline header: "Jul 15", "Jul 16", ...
        date_labels = [
            (args.start_date + timedelta(days=d)).strftime("%b %-d")
            if sys.platform != "win32"
            else (args.start_date + timedelta(days=d)).strftime("%b %#d")
            for d in range(args.nights)
        ]
        source_note  = "live" if args.live else "mock data"

        from rich.panel import Panel as _Panel

        for pk in park_keys_av:
            park_cfg    = PARKS[pk]
            permit_type = park_cfg.get("permit_type", "ITINERARY")
            raw_sites   = _av_ds.fetch_sites(park_cfg["facility_id"])

            # Apply --area filter.
            if args.area:
                raw_sites = [
                    s for s in raw_sites
                    if any(f.lower() in (s.get("district") or "").lower() for f in args.area)
                ]

            # Fetch availability for every site.
            avail_map: dict[str, list[int]] = {}
            for s in raw_sites:
                raw = _av_ds.fetch_availability(
                    park_cfg["facility_id"],
                    s["division_id"],
                    args.start_date,
                    permit_type=permit_type,
                ) if args.live else _av_ds.fetch_availability(
                    park_cfg["facility_id"],
                    s["division_id"],
                    args.start_date,
                )
                avail_map[s["division_id"]] = [raw.get(d, -1) for d in target_dates]

            n_sites = len(raw_sites)
            n_open_sites = sum(
                1 for div_id, counts in avail_map.items()
                if any(c > 0 for c in counts)
            )

            _console.print(_Panel(
                f"[dim]{park_cfg['facility_id']}  ·  "
                f"{args.start_date} → {end_date}  ({args.nights} nights)  ·  "
                f"{n_sites} site{'s' if n_sites != 1 else ''}  ·  "
                f"{n_open_sites} with availability  ·  {source_note}[/dim]",
                title=f"[bold yellow]{park_cfg['display_name']} — Permit Availability[/bold yellow]",
                expand=False,
                border_style="yellow dim",
            ))

            # Build table: District | Division | [sparkline per night] | Min | Open
            tbl = Table(
                box=rich_box.SIMPLE_HEAD,
                show_header=True,
                header_style="bold dim",
                pad_edge=True,
                expand=False,
                padding=(0, 1),
            )
            tbl.add_column("District",  min_width=20, style="dim")
            tbl.add_column("Division",  min_width=26)
            # One column per night (date label as header).
            for lbl in date_labels:
                tbl.add_column(lbl, justify="center", width=7, no_wrap=True)
            tbl.add_column("Min",  justify="right", width=5)
            tbl.add_column("Open", justify="right", width=6)

            # Group rows by district.
            sorted_sites = sorted(raw_sites, key=lambda x: ((x.get("district") or ""), x["name"]))
            prev_district = None
            for s in sorted_sites:
                district = (s.get("district") or "—").strip() or "—"
                counts   = avail_map[s["division_id"]]
                known    = [c for c in counts if c >= 0]
                min_av   = min(known) if known else -1
                n_open   = sum(1 for c in known if c > 0)
                n_total  = len(target_dates)

                # Add a blank separator row between districts.
                if prev_district is not None and district != prev_district:
                    tbl.add_section()
                prev_district = district

                # Per-night cells.
                night_cells: list[Text] = []
                for c in counts:
                    if c < 0:
                        night_cells.append(Text("  ·  ", style="dim"))
                    elif c == 0:
                        night_cells.append(Text(" full", style="bold red"))
                    elif c == 1:
                        night_cells.append(Text(f"  1  ", style="bold yellow"))
                    else:
                        night_cells.append(Text(f"  {c}  ", style="bold green"))

                # Min and Open summary cells.
                if min_av < 0:
                    min_cell  = Text("  —", style="dim")
                    open_cell = Text("  —", style="dim")
                elif min_av == 0:
                    min_cell  = Text("  0", style="bold red")
                    open_cell = Text(f"{n_open}/{n_total}", style="red" if n_open < n_total else "dim")
                elif min_av == 1:
                    min_cell  = Text("  1", style="bold yellow")
                    open_cell = Text(f"{n_open}/{n_total}", style="yellow")
                else:
                    min_cell  = Text(f"  {min_av}", style="bold green")
                    open_cell = Text(f"{n_open}/{n_total}", style="green")

                tbl.add_row(district, s["name"], *night_cells, min_cell, open_cell)

            _console.print(tbl)
            _console.print(
                "[dim]  Nightly columns show permits remaining. "
                "Min = worst night. Open = nights with ≥ 1 remaining.[/dim]\n"
            )

        return 0

    # Without --list-chains, the chain search does not run.
    if not getattr(args, "list_chains", False):
        _console.print("\n[dim]Specify a command:[/dim]")
        _console.print("  [bold]--list-areas[/bold]         [dim]District overview for a park (fast, no availability fetch)[/dim]")
        _console.print("  [bold]--list-availability[/bold]  [dim]Flat table: Facility / District / Division / remaining / dates[/dim]")
        _console.print("  [bold]--list-chains[/bold]        [dim]Find multi-night permit chains with live or mock availability[/dim]")
        _console.print("\n[dim]Run wa-permits --help for full usage.[/dim]")
        return 0

    # Resolve which parks to search.
    park_keys = args.park or ["all"]
    if "all" in park_keys:
        selected = list(PARKS.keys())
    else:
        unknown = [k for k in park_keys if k not in PARKS]
        if unknown:
            print(f"Unknown park(s): {', '.join(unknown)}", file=sys.stderr)
            print(f"Run `wa-permits --list-parks` to see valid names.", file=sys.stderr)
            return 1
        selected = park_keys

    # Select data source: live API or built-in mock data.
    if args.live:
        from permit_engine import api as data_source
        if args.verbose:
            data_source.set_verbose(True)
    else:
        from permit_engine import mock as data_source

    if args.json:
        # Collect results from every park and emit a single JSON document to stdout.
        all_park_results = []
        for park_key in selected:
            park_chains = _search_park(park_key, PARKS[park_key], args, data_source)
            if park_chains:
                all_park_results.append({
                    "park": park_key,
                    "display_name": PARKS[park_key]["display_name"],
                    "chains": park_chains,
                })
        doc = {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "query": {
                "parks": selected,
                "start_date": str(args.start_date),
                "nights": args.nights,
                "source": "live" if args.live else "mock",
                "exact_length": args.exact_length,
                "limit": args.limit,
            },
            "parks": all_park_results,
        }
        print(json.dumps(doc, indent=2))
    else:
        for park_key in selected:
            _search_park(park_key, PARKS[park_key], args, data_source)

    return 0


def _search_park(
    park_key: str,
    park: dict,
    args: argparse.Namespace,
    data_source,
) -> list[dict] | None:
    """
    Run the full search pipeline for one park.

    Returns a list of chain-JSON dicts when --json is active (for the caller
    to assemble into the final document), or None when printing Rich output.
    """
    json_mode = getattr(args, "json", False)
    # Progress output: stderr in JSON mode so stdout stays clean JSON.
    _out = sys.stderr if json_mode else sys.stdout

    end_date = args.start_date + timedelta(days=args.nights - 1)

    if not json_mode:
        meta = [
            ("Park",   park["display_name"]),
            ("Dates",  f"{args.start_date}  ->  {end_date}  ({args.nights} nights)"),
            ("Source", "live Recreation.gov + OpenStreetMap" if args.live else "mock data"),
        ]
        if args.live:
            meta.append(("Permit type", park["permit_type"]))
        if not args.exact_length:
            meta.append(("Length", f"1 - {args.nights} nights (grouped)"))
        if args.available:
            meta.append(("Filter", f">= {args.permit_count} permits every night"))
        if args.trailhead:
            meta.append(("Trailhead", "connections included"))

        from rich.panel import Panel
        from rich.table import Table as _T
        info = _T.grid(padding=(0, 2))
        for label, value in meta:
            info.add_row(f"[dim]{label}[/dim]", f"[bold]{value}[/bold]")
        _console.print(Panel(info, title=f"[bold yellow]{park['display_name']}[/bold yellow]", expand=False, border_style="yellow dim"))
        print()

    # Step 1 — build the trail graph from sites and OSM trails.
    print("Building trail graph...", end=" ", flush=True, file=_out)
    raw_sites  = data_source.fetch_sites(park["facility_id"])
    raw_trails = data_source.fetch_trails(park["bbox"])
    graph = build_graph(raw_sites, raw_trails, allow_trailhead=args.trailhead)
    edge_count = sum(len(v) for v in graph.adjacency.values()) // 2
    print(f"{len(graph.sites)} sites, {edge_count} edges", file=_out)

    # Step 2 — fetch per-night availability.
    # Only query sites that have at least one neighbor — isolated sites can never
    # appear in a multi-night chain, so fetching them wastes API calls.
    permit_type = park.get("permit_type", "ITINERARY")
    connected_ids = [sid for sid in graph.sites if graph.adjacency.get(sid)]
    n_total  = len(graph.sites)
    n_fetch  = len(connected_ids)
    skipped  = n_total - n_fetch
    availability: dict[str, dict[str, int]] = {}
    avail_status = "mock"  # updated below for live runs
    detail_limit = args.detail_limit  # set by --detail-limit (default 25)

    # Target dates: the specific nights we care about. The API returns a full
    # month, so we filter down to exactly these dates before the DFS.
    target_dates = {
        (args.start_date + timedelta(days=d)).strftime("%Y-%m-%d")
        for d in range(args.nights)
    }

    _fetch_t0 = time.perf_counter()

    if not args.live:
        fetch_ids = connected_ids
        area_msg  = ""
        if args.area:
            fetch_ids = [
                sid for sid in connected_ids
                if any(f.lower() in (graph.sites[sid].district or "").lower() for f in args.area)
            ]
            area_msg = f" (area filter: {len(fetch_ids)} of {n_fetch} connected)"
        print(f"Fetching availability for {len(fetch_ids)}/{n_total} sites"
              f"{f' ({skipped} isolated skipped)' if skipped else ''}"
              f"{area_msg}...",
              end=" ", flush=True, file=_out)
        for div_id in fetch_ids:
            raw = data_source.fetch_availability(
                park["facility_id"], div_id, args.start_date
            )
            availability[div_id] = {d: v for d, v in raw.items() if d in target_dates}
        print(f"done [{time.perf_counter() - _fetch_t0:.1f}s]", file=_out)
    else:
        if not connected_ids:
            print(f"No connected sites to query.", file=_out)
        else:
            # Group connected sites by district; apply --area filter then --detail-limit cap.
            district_groups: dict[str, list[str]] = {}
            for sid in connected_ids:
                dist = (graph.sites[sid].district or "").strip() or "—"
                district_groups.setdefault(dist, []).append(sid)

            # --area: keep only districts matching any of the user-supplied substrings.
            if args.area:
                district_groups = {
                    dist: sids for dist, sids in district_groups.items()
                    if any(f.lower() in dist.lower() for f in args.area)
                }
                if not district_groups:
                    _console.print(
                        f"[yellow]No districts matched --area {args.area!r} for "
                        f"{park['display_name']}. Available districts:[/yellow]"
                    )
                    all_dg: dict[str, list[str]] = {}
                    for sid in connected_ids:
                        d = (graph.sites[sid].district or "").strip() or "—"
                        all_dg.setdefault(d, []).append(sid)
                    for d in sorted(all_dg):
                        _console.print(f"  [dim]{d}[/dim]")
                    return None

            n_districts_total   = len(district_groups)
            selected_districts  = list(district_groups.keys())[:detail_limit]
            site_ids            = [sid for d in selected_districts for sid in district_groups[d]]
            n_capped            = len(site_ids)
            dist_cap_msg = (
                f", {len(selected_districts)}/{n_districts_total} district"
                f"{'s' if len(selected_districts) != 1 else ''}"
                + (" via --detail-limit" if n_districts_total > len(selected_districts) else "")
            )
            api_calls = 0

            print(f"Fetching availability ({n_capped}/{n_total} sites"
                  f"{f', {skipped} isolated skipped' if skipped else ''}"
                  f"{dist_cap_msg}) — probing {site_ids[0]}...", end=" ", flush=True, file=_out)

            probe_raw = data_source.fetch_availability(
                park["facility_id"], site_ids[0], args.start_date, permit_type=permit_type
            )
            api_calls += 1
            # Filter probe to target dates only.
            probe = {d: v for d, v in probe_raw.items() if d in target_dates}

            if not probe_raw:
                # Empty response → pre-season, no quota data at all.
                print(f"done ({api_calls} call — pre-season, no data) [{time.perf_counter() - _fetch_t0:.1f}s]", file=_out)
                avail_status = "pre_season"
            else:
                all_zero = probe and not any(probe[d] > 0 for d in probe)

                if all_zero:
                    # Every target date is 0 — fully booked for this window.
                    # Propagate to all capped sites; no further calls needed.
                    for sid in site_ids:
                        availability[sid] = probe
                    saved = n_capped - 1
                    print(
                        f"done ({api_calls} call — all dates fully booked, {saved} calls saved)"
                        f" [{time.perf_counter() - _fetch_t0:.1f}s]",
                        file=_out,
                    )
                    avail_status = "all_booked"
                else:
                    avail_status = "live"
                    availability[site_ids[0]] = probe
                    remaining_ids = site_ids[1:]
                    print(f"done (1/{n_capped})", file=_out)
                    if remaining_ids:
                        print(f"Fetching remaining {len(remaining_ids)} sites...", end=" ", flush=True, file=_out)
                        for i, div_id in enumerate(remaining_ids, 2):
                            if args.verbose:
                                print(f"\n  [{i}/{n_capped}] {div_id}", end=" ", flush=True, file=_out)
                            raw = data_source.fetch_availability(
                                park["facility_id"], div_id, args.start_date, permit_type=permit_type
                            )
                            api_calls += 1
                            availability[div_id] = {d: v for d, v in raw.items() if d in target_dates}
                        print(f"done [{time.perf_counter() - _fetch_t0:.1f}s]", file=_out)

                    # Stats: calls made, districts queried, total available permit slots.
                    if not json_mode:
                        total_avail_slots = sum(
                            cnt
                            for site_avail in availability.values()
                            for cnt in site_avail.values()
                            if cnt > 0
                        )
                        n_dist_fetched = len(selected_districts)
                        _console.print(
                            f"[dim]  {api_calls} API call{'s' if api_calls != 1 else ''}"
                            f" · {n_dist_fetched}/{n_districts_total} district{'s' if n_dist_fetched != 1 else ''} queried"
                            f" · {total_avail_slots} available permit slot{'s' if total_avail_slots != 1 else ''}[/dim]"
                        )

    # Step 3 — DFS to find all multi-night chains.
    min_nights = None if args.exact_length else 1
    chains = find_chains(graph, availability, args.start_date, args.nights, min_nights=min_nights)

    # Step 4 — apply --available filter when requested.
    if args.available:
        chains = filter_by_availability(chains, args.permit_count)

    # Step 5 — apply --limit.
    if args.limit is not None:
        chains = chains[: args.limit]

    if not chains:
        if json_mode:
            print(f"No chains found for {park['display_name']}.", file=sys.stderr)
        else:
            _console.print(f"\n[yellow]No chains found for {park['display_name']}.[/yellow]")
            if args.available:
                _console.print("  Try removing --available or lowering --permit-count.")
        return None

    if json_mode:
        print(f"Found {len(chains)} chain(s) in {park['display_name']}.", file=sys.stderr)
        return [
            _build_chain_json(chain, i, park_key, park, args)
            for i, chain in enumerate(chains, 1)
        ]

    _console.print()
    _print_avail_status_banner(avail_status, park["display_name"], len(chains))

    display_chains = chains  # scoped by districts (--detail-limit) and chain count (--limit)

    show_overview = args.overview or (not args.chains)
    show_chains   = args.chains   or (not args.overview)

    if show_overview:
        if args.exact_length:
            _print_flow_table(display_chains)
        else:
            _print_grouped_flow_table(display_chains, args.nights)
    if show_chains:
        _print_chain_details(display_chains)
    return None


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="wa-permits",
        description="Find multi-night backpacking permit chains in Washington State parks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join([
            "park names:  " + ", ".join(PARKS.keys()) + ", all",
            "",
            "examples:",
            "  wa-permits --list-parks",
            "  wa-permits --park north-cascades --start-date 2026-07-15 --nights 5",
            "  wa-permits --park north-cascades olympic --start-date 2026-07-15 --nights 5 --live",
            "  wa-permits --park all --start-date 2026-07-15 --nights 5 --live",
            "  wa-permits --park rainier --start-date 2026-07-22 --nights 7 --live",
        ]),
    )
    parser.add_argument(
        "--list-parks",
        action="store_true",
        default=False,
        help="Print all supported park names and exit.",
    )
    parser.add_argument(
        "--park",
        nargs="+",
        metavar="PARK",
        help=(
            f"Park(s) to search. Use 'all' to search every park. "
            f"Valid names: {', '.join(PARKS.keys())}, all."
        ),
    )
    parser.add_argument(
        "--start-date",
        type=_parse_date,
        metavar="YYYY-MM-DD",
        help="First night of the trip. Required unless --list-parks is used.",
    )
    parser.add_argument(
        "--nights",
        type=int,
        metavar="N",
        help="Number of nights. Required unless --list-parks is used.",
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
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help=(
            "Print every HTTP request URL, status code, and error body to stderr. "
            "Useful for debugging API issues. Only effective with --live."
        ),
    )
    parser.add_argument(
        "--exact-length",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "When True (default), only return chains of exactly --nights length. "
            "Use --no-exact-length to return chains of all lengths from 1 up to --nights, "
            "grouped longest-first."
        ),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Cap the number of chains returned. Applied after all filters. Default: no limit.",
    )
    parser.add_argument(
        "--detail-limit",
        type=int,
        default=25,
        metavar="N",
        dest="detail_limit",
        help=(
            "Max number of site districts to query for availability (limits live API traffic). "
            "Applied after --area filtering; only the first N remaining districts are fetched. "
            "Use --limit to cap the number of chains in the output. Default: 25."
        ),
    )
    parser.add_argument(
        "--area",
        nargs="+",
        metavar="AREA",
        default=None,
        help=(
            "Restrict search to sites in matching districts (case-insensitive substring match). "
            "Accepts one or more names: --area 'Carbon River' 'Mowich'. "
            "Reduces API calls by skipping all sites outside the named areas. "
            "List available districts with --list-areas."
        ),
    )
    parser.add_argument(
        "--list-areas",
        action="store_true",
        default=False,
        dest="list_areas",
        help=(
            "Print district names and site counts for the selected park(s). "
            "Fast — fetches site list only, no availability API calls. "
            "Combine with --live to use real site data."
        ),
    )
    parser.add_argument(
        "--list-chains",
        action="store_true",
        default=False,
        dest="list_chains",
        help=(
            "Find and display multi-night permit chains with availability. "
            "Requires --start-date and --nights. "
            "Use --live for real-time data, --area to filter by district, "
            "--limit to cap output."
        ),
    )
    parser.add_argument(
        "--list-availability",
        action="store_true",
        default=False,
        dest="list_availability",
        help=(
            "Print a flat table of every division's availability for the requested "
            "date window: Facility / District / Division / Min Avail / Nights Open / Date Range. "
            "Requires --start-date and --nights. Combine with --live and --area."
        ),
    )

    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--detail",
        action="store_true",
        default=False,
        help="Show summary table AND per-chain night-by-night detail. (Default when no output flag is set.)",
    )
    output_group.add_argument(
        "--overview",
        action="store_true",
        default=False,
        help="Show only the summary table (entry/exit site, date range, min availability).",
    )
    output_group.add_argument(
        "--chains",
        action="store_true",
        default=False,
        help="Show only the per-chain night-by-night detail, no summary table.",
    )
    output_group.add_argument(
        "--json",
        action="store_true",
        default=False,
        help=(
            "Output chain data as JSON instead of the Rich table. "
            "Progress messages go to stderr so stdout is clean JSON. "
            "Combine with --limit to cap output size. Default: off."
        ),
    )

    args = parser.parse_args()

    # Validate required args.
    if args.list_parks:
        pass  # no other args needed
    elif getattr(args, "list_chains", False):
        if not args.park:
            parser.error("--park is required for --list-chains")
        if args.start_date is None:
            parser.error("--start-date is required for --list-chains")
        if args.nights is None:
            parser.error("--nights is required for --list-chains")
    elif getattr(args, "list_availability", False):
        if not args.park:
            parser.error("--park is required for --list-availability")
        if args.start_date is None:
            parser.error("--start-date is required for --list-availability")
        if args.nights is None:
            parser.error("--nights is required for --list-availability")
    elif getattr(args, "list_areas", False):
        if not args.park:
            parser.error("--park is required for --list-areas")

    return args


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}'. Expected YYYY-MM-DD.")


# ---------------------------------------------------------------------------
# Output — built with Rich
# ---------------------------------------------------------------------------

from itertools import groupby

from rich import box as rich_box
from rich.console import Console
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

_console = Console(highlight=False)


def _avail_text(remaining: int) -> Text:
    """Single-night availability as a coloured Rich Text cell."""
    if remaining < 0:
        return Text("--", style="dim")
    if remaining == 0:
        return Text("✗ full", style="bold red")
    if remaining == 1:
        return Text("1 left", style="bold yellow")
    return Text(f"{remaining} left", style="bold green")


def _route_text(chain: Chain) -> Text:
    """
    Full campsite flow. Entry site is green, exit site is cyan,
    intermediate sites are default. Arrows are dimmed.
    """
    last = len(chain.links) - 1
    t = Text()
    for k, link in enumerate(chain.links):
        if k:
            t.append("  →  ", style="dim")
        if k == 0:
            t.append(link.site.name, style="bold green")
        elif k == last:
            t.append(link.site.name, style="bold cyan")
        else:
            t.append(link.site.name)
    return t


def _overview_table(chains: list[Chain], start_num: int = 1, show_header: bool = True) -> Table:
    """
    Numbered chain overview with route flow and area (district).

    show_header=True  — use SIMPLE_HEAD box (header line separator).
    show_header=False — no header row (used in grouped mode where group Rules act as labels).
    """
    tbl = Table(
        box=rich_box.SIMPLE_HEAD if show_header else None,
        show_header=show_header,
        header_style="bold dim",
        pad_edge=False,
        expand=False,
        padding=(0, 2),
    )
    tbl.add_column("#", justify="right", style="dim", width=4, no_wrap=True)
    tbl.add_column("Route")
    tbl.add_column("Area", style="dim", min_width=20)

    for i, chain in enumerate(chains, start_num):
        # Collect unique districts in chain order, skipping blanks.
        seen: dict[str, None] = {}
        for link in chain.links:
            d = (link.site.district or "").strip()
            if d:
                seen[d] = None
        area_str = "  /  ".join(seen.keys()) if seen else "—"
        tbl.add_row(str(i), _route_text(chain), area_str)

    return tbl


def _print_avail_status_banner(avail_status: str, park_name: str, chain_count: int) -> None:
    """Print a clear availability status line before the chain results."""
    from rich.panel import Panel as _Panel

    if avail_status == "all_booked":
        _console.print(_Panel(
            "[bold red]All permit dates are fully booked (0 remaining on every night).[/bold red]\n"
            "[dim]Chains below show all physically possible routes — none are currently bookable.\n"
            "Check back for cancellations or try different dates.[/dim]",
            title="[bold red]Fully Booked[/bold red]",
            border_style="red",
            expand=False,
        ))
    elif avail_status == "pre_season":
        _console.print(_Panel(
            "[bold yellow]Reservations have not opened yet — the API returned no availability data.[/bold yellow]\n"
            "[dim]Chains below show all physically possible routes for planning purposes.[/dim]",
            title="[bold yellow]Pre-Season[/bold yellow]",
            border_style="yellow",
            expand=False,
        ))
    elif avail_status == "mock":
        _console.print(
            f"Found [bold green]{chain_count}[/bold green] chain(s) in [bold]{park_name}[/bold]."
            f"  [dim](mock data)[/dim]"
        )
        return
    else:
        # live data with real availability
        _console.print(
            f"Found [bold green]{chain_count}[/bold green] chain(s) in [bold]{park_name}[/bold]."
        )
        return

    _console.print(
        f"\n[dim]{chain_count} possible route{'s' if chain_count != 1 else ''} for [bold]{park_name}[/bold]:[/dim]"
    )


def _print_flow_table(chains: list[Chain]) -> None:
    """Flat overview for exact-length results (with column headers)."""
    _console.print(_overview_table(chains, show_header=True))


def _print_grouped_flow_table(chains: list[Chain], max_nights: int) -> None:
    """Chains grouped by length (longest first), numbered continuously.
    Each group is headed by a Rule — no per-table headers needed."""
    counter = 1
    for nights_len, group in groupby(chains, key=lambda c: c.num_nights):
        group_list = list(group)
        start_d = group_list[0].start_date
        end_d   = group_list[0].end_date
        label   = (
            f"[bold yellow]{nights_len} night{'s' if nights_len != 1 else ''}[/bold yellow]"
            f"  [dim]{start_d} → {end_d}  ·  {len(group_list)} chains[/dim]"
        )
        _console.print(Rule(label, style="yellow dim"))
        _console.print(_overview_table(group_list, start_num=counter, show_header=False))
        counter += len(group_list)


def _print_chain_details(chains: list[Chain]) -> None:
    """Night-by-night breakdown for every chain."""
    for i, chain in enumerate(chains, 1):
        _console.print()
        _console.print(Rule(
            f"[bold]Chain #{i}[/bold]"
            f"  [bold blue]{chain.num_nights} night{'s' if chain.num_nights != 1 else ''}[/bold blue]"
            f"  [dim]{chain.start_date} → {chain.end_date}[/dim]",
            style="blue",
        ))

        tbl = Table(
            box=rich_box.SIMPLE_HEAD,
            show_header=True,
            header_style="bold dim",
            pad_edge=True,
        )
        tbl.add_column("Night", justify="right", width=5)
        tbl.add_column("Date", width=12, style="dim")
        tbl.add_column("Site", min_width=28)
        tbl.add_column("Area", min_width=22, style="dim")
        tbl.add_column("Avail", justify="right", width=8)

        for j, link in enumerate(chain.links, 1):
            is_entry = j == 1
            is_exit  = j == chain.num_nights

            if is_entry:
                night_str = Text(str(j), style="green")
                site_text = Text(link.site.name, style="bold green")
            elif is_exit:
                night_str = Text(str(j), style="cyan")
                site_text = Text(link.site.name, style="bold cyan")
            else:
                night_str = Text(str(j))
                site_text = Text(link.site.name)

            area_str = (link.site.district or "").strip() or "—"
            tbl.add_row(
                night_str,
                str(link.night_date),
                site_text,
                area_str,
                _avail_text(link.remaining),
            )

        _console.print(tbl)


# ---------------------------------------------------------------------------
# JSON output builder
# ---------------------------------------------------------------------------

def _build_chain_json(
    chain: Chain,
    chain_id: int,
    park_key: str,
    park: dict,
    args: argparse.Namespace,
) -> dict:
    """Serialize one Chain to the map-compatible JSON schema."""
    links = chain.links
    lats = [l.site.lat for l in links]
    lons = [l.site.lon for l in links]

    min_rem = chain.min_remaining()
    if min_rem == -1:
        avail_status = "unknown"
    elif min_rem == 0:
        avail_status = "booked"
    elif all(l.remaining > 0 for l in links):
        avail_status = "available"
    else:
        avail_status = "partial"

    night1 = links[0].night_date.strftime("%Y-%m-%d")
    booking_url = (
        f"https://www.recreation.gov/permits/{park['facility_id']}"
        f"/registration/detailed-availability?date={night1}"
    )

    nights_detail = []
    for j, link in enumerate(links, 1):
        rem = link.remaining if link.remaining >= 0 else None
        if rem is None:
            ns = "unknown"
        elif rem == 0:
            ns = "booked"
        else:
            ns = "available"
        nights_detail.append({
            "night": j,
            "date": str(link.night_date),
            "site": {
                "division_id": link.site.division_id,
                "name": link.site.name,
                "lat": link.site.lat,
                "lon": link.site.lon,
                "district": link.site.district,
                "rec_gov_url": f"https://www.recreation.gov/permits/{park['facility_id']}",
            },
            "availability": {
                "remaining": rem,
                "status": ns,
            },
        })

    coordinates = [[l.site.lon, l.site.lat] for l in links]
    geojson_features = [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coordinates},
            "properties": {
                "type": "route",
                "chain_id": chain_id,
                "nights": chain.num_nights,
                "note": "Straight-line segments between campsites; actual trail polylines not stored",
            },
        }
    ]
    for j, (link, nd) in enumerate(zip(links, nights_detail), 1):
        geojson_features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [link.site.lon, link.site.lat]},
            "properties": {
                "type": "campsite",
                "night": j,
                "date": nd["date"],
                "division_id": link.site.division_id,
                "name": link.site.name,
                "district": link.site.district,
                "availability_remaining": nd["availability"]["remaining"],
                "availability_status": nd["availability"]["status"],
                "is_entry": j == 1,
                "is_exit": j == chain.num_nights,
            },
        })

    return {
        "chain_id": chain_id,
        "nights": chain.num_nights,
        "start_date": str(chain.start_date),
        "end_date": str(chain.end_date),
        "availability_status": avail_status,
        "min_availability": min_rem if min_rem >= 0 else None,
        "bounding_box": {
            "min_lat": min(lats),
            "min_lon": min(lons),
            "max_lat": max(lats),
            "max_lon": max(lons),
        },
        "booking_url": booking_url,
        "entry_site": {
            "name": links[0].site.name,
            "lat": links[0].site.lat,
            "lon": links[0].site.lon,
        },
        "exit_site": {
            "name": links[-1].site.name,
            "lat": links[-1].site.lat,
            "lon": links[-1].site.lon,
        },
        "nights_detail": nights_detail,
        "geojson": {"type": "FeatureCollection", "features": geojson_features},
    }


if __name__ == "__main__":
    sys.exit(main())
