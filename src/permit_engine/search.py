"""
DFS chain search over a trail graph with per-night permit availability.

A chain is a sequence of sites visited on consecutive nights. Site N is
visited on (start_date + N-1 days). Each site must be reachable from the
previous site via a single trail edge in the graph.

Availability annotation
-----------------------
Every link in the chain records the number of permits remaining at that site
on that specific night. A count of -1 means availability was not fetched
(offline / pre-season mode).

Filtering with --available
--------------------------
Without --available : all physically possible chains are returned, with
                      availability counts shown for reference.
With --available    : only chains where every site has remaining >= permit_count
                      are returned.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from permit_engine.graph import Site, TrailGraph


@dataclass
class ChainLink:
    site: Site
    night_date: date
    # Permits remaining at this site on night_date. -1 = not fetched.
    remaining: int


@dataclass
class Chain:
    links: list[ChainLink]

    @property
    def start_date(self) -> date:
        return self.links[0].night_date

    @property
    def end_date(self) -> date:
        return self.links[-1].night_date

    @property
    def num_nights(self) -> int:
        return len(self.links)

    def min_remaining(self) -> int:
        """Lowest availability count across all nights. -1 if any is unknown."""
        counts = [link.remaining for link in self.links]
        if any(c == -1 for c in counts):
            return -1
        return min(counts)

    def meets_permit_count(self, permit_count: int) -> bool:
        """True if every night has at least permit_count permits remaining."""
        return all(link.remaining >= permit_count for link in self.links)


def find_chains(
    graph: TrailGraph,
    availability: dict[str, dict[str, int]],
    start_date: date,
    nights: int,
) -> list[Chain]:
    """
    Find all valid multi-night chains in the graph.

    graph        : trail graph with sites and adjacency
    availability : division_id → {date_str → remaining_count}
                   Pass an empty dict to skip availability filtering entirely.
    start_date   : first night of the trip
    num_nights   : total number of nights

    Returns all chains of exactly num_nights length. Each site appears at
    most once per chain (no revisiting the same campsite on the same trip).
    Availability is annotated on every link but does NOT filter results here —
    use filter_by_availability() after this call if needed.
    """
    all_chains: list[Chain] = []

    for start_site_id in graph.sites:
        visited: set[str] = {start_site_id}
        links: list[ChainLink] = [
            ChainLink(
                site=graph.sites[start_site_id],
                night_date=start_date,
                remaining=_remaining(availability, start_site_id, start_date),
            )
        ]
        _dfs(
            graph=graph,
            availability=availability,
            current_date=start_date,
            nights_remaining=nights - 1,
            links=links,
            visited=visited,
            all_chains=all_chains,
        )

    return all_chains


def filter_by_availability(chains: list[Chain], permit_count: int) -> list[Chain]:
    """
    Return only chains where every site has at least permit_count remaining.

    Applied when --available is passed on the CLI.
    """
    return [c for c in chains if c.meets_permit_count(permit_count)]


# ---------------------------------------------------------------------------
# Internal DFS
# ---------------------------------------------------------------------------

def _dfs(
    graph: TrailGraph,
    availability: dict[str, dict[str, int]],
    current_date: date,
    nights_remaining: int,
    links: list[ChainLink],
    visited: set[str],
    all_chains: list[Chain],
) -> None:
    """
    Recursive DFS. Extends the current chain by one night at a time until
    num_nights is reached, then records the completed chain.
    """
    if nights_remaining == 0:
        all_chains.append(Chain(links=list(links)))
        return

    current_site_id = links[-1].site.division_id
    next_date = current_date + timedelta(days=1)

    for neighbor_id in graph.adjacency.get(current_site_id, []):
        if neighbor_id in visited:
            continue  # do not revisit a site already in this chain

        visited.add(neighbor_id)
        links.append(
            ChainLink(
                site=graph.sites[neighbor_id],
                night_date=next_date,
                remaining=_remaining(availability, neighbor_id, next_date),
            )
        )

        _dfs(
            graph=graph,
            availability=availability,
            current_date=next_date,
            nights_remaining=nights_remaining - 1,
            links=links,
            visited=visited,
            all_chains=all_chains,
        )

        links.pop()
        visited.discard(neighbor_id)


def _remaining(
    availability: dict[str, dict[str, int]],
    division_id: str,
    night_date: date,
) -> int:
    """
    Look up permit availability for one site on one night.

    Returns the remaining count, or -1 if availability was not fetched.
    """
    date_str = night_date.strftime("%Y-%m-%d")
    site_avail = availability.get(division_id)
    if site_avail is None:
        return -1  # availability not fetched for this site
    return site_avail.get(date_str, -1)  # -1 if date not in response
