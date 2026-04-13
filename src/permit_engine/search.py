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

import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta

from permit_engine.graph import Site, TrailGraph

log = logging.getLogger(__name__)


@dataclass
class ChainLink:
    site: Site
    night_date: date
    # Permits remaining at this site on night_date:
    #  > 0  available for online booking
    #    0  fully booked (no permits of any kind)
    #   -2  walk-up / in-station only — online quota is 0 but ranger-station quota remains
    #   -1  not fetched (pre-season or no API data)
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
        """
        Lowest availability count across all nights.
        Returns -1 if any night has no API data (pre-season).
        Returns -2 if all nights have data but some are walk-up only (no -1s).
        Returns 0 if any night is fully booked (no walk-up, no unknowns).
        Returns >0 if all nights have online permits remaining.
        """
        counts = [link.remaining for link in self.links]
        if any(c == -1 for c in counts):
            return -1
        return min(counts)  # may be -2 (walk-up), 0 (booked), or >0 (open)

    def meets_permit_count(self, permit_count: int) -> bool:
        """
        True if every night has at least permit_count permits available online.
        Walk-up nights (remaining == -2) do not satisfy this check since they
        cannot be booked through recreation.gov.
        """
        return all(link.remaining >= permit_count for link in self.links)


def find_chains(
    graph: TrailGraph,
    availability: dict[str, dict[str, int]],
    start_date: date,
    nights: int,
    min_nights: int | None = None,
) -> list[Chain]:
    """
    Find all valid multi-night chains in the graph.

    graph        : trail graph with sites and adjacency
    availability : division_id → {date_str → remaining_count}
                   Pass an empty dict to skip availability filtering entirely.
    start_date   : first night of the trip
    nights       : maximum (and default exact) number of nights
    min_nights   : if set, also collect chains of this length up to nights.
                   If None, only chains of exactly nights are returned.

    Returns chains sorted longest-first when min_nights is set.
    Each site appears at most once per chain (no revisiting).
    Availability is annotated on every link but does NOT filter results —
    use filter_by_availability() after this call if needed.
    """
    effective_min = min_nights if min_nights is not None else nights
    all_chains: list[Chain] = []

    t0 = time.perf_counter()
    log.debug("find_chains  %d start nodes, nights=%d, min_nights=%s, start_date=%s",
              len(graph.sites), nights, effective_min, start_date)

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
            min_nights=effective_min,
            links=links,
            visited=visited,
            all_chains=all_chains,
        )

    if min_nights is not None:
        all_chains.sort(key=lambda c: -c.num_nights)

    log.debug("find_chains  done: %d chains found  (%.3fs)", len(all_chains), time.perf_counter() - t0)
    return all_chains


def filter_by_availability(chains: list[Chain], permit_count: int) -> list[Chain]:
    """
    Return only chains where every site has at least permit_count remaining.

    Applied when --available is passed on the CLI.
    """
    result = [c for c in chains if c.meets_permit_count(permit_count)]
    log.debug("filter_by_availability  permit_count=%d  %d → %d chains",
              permit_count, len(chains), len(result))
    return result


# ---------------------------------------------------------------------------
# Internal DFS
# ---------------------------------------------------------------------------

def _dfs(
    graph: TrailGraph,
    availability: dict[str, dict[str, int]],
    current_date: date,
    nights_remaining: int,
    min_nights: int,
    links: list[ChainLink],
    visited: set[str],
    all_chains: list[Chain],
) -> None:
    """
    Recursive DFS. Records a chain whenever its length >= min_nights,
    and keeps extending until nights_remaining == 0 (max nights reached).
    """
    if len(links) >= min_nights:
        all_chains.append(Chain(links=list(links)))

    if nights_remaining == 0:
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
            min_nights=min_nights,
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
