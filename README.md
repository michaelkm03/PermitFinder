# wa-permits

A Python CLI that finds valid multi-night backpacking chains in Washington State national parks where every campsite has available permits. Built on real-time data from Recreation.gov and OpenStreetMap — no account or API key required.

## How it works

1. **Fetch campsites** — calls Recreation.gov's internal API (`/api/permitcontent/{facility_id}`) to get all permitted campsites with their GPS coordinates, names, and district. Results are cached locally for 30 days.

2. **Fetch trail geometry** — calls OpenStreetMap's Overpass API to get trail polylines (sequences of GPS points) for all hiking trails inside a bounding box around the park. Results are cached locally for 30 days.

3. **Build the trail graph** — snaps each campsite to its nearest point on any trail polyline (within ~200 m). Then:
   - **Within-trail edges**: sorts all sites snapped to the same trail by their position along the trail, and connects consecutive pairs
   - **Cross-trail edges**: finds trail pairs that share an OSM node ID; if the shared node is mid-trail on one trail it is a genuine trail junction (always included); if it is an endpoint on both trails it is a trailhead connection (parking-lot crossing, excluded by default — enable with `--trailhead`)
   - Sites with missing GPS coordinates (`lat=0, lon=0`) are added as isolated nodes with no edges

4. **Fetch availability** — calls Recreation.gov's per-night quota API for each connected site in the graph. Values: `>0` = permits remaining, `0` = fully booked, `-2` = walk-up / in-station only.

5. **DFS chain search** — walks the adjacency graph to find every valid multi-night sequence, annotating each night with the remaining permit count for that site and date.

6. **Filter** — removes chains where any night has fewer available permits than `--permit-count`.

## Supported parks

| Key | Park | Permit Type |
|---|---|---|
| `rainier` | Mount Rainier | ITINERARY |
| `north-cascades` | North Cascades | ITINERARY |
| `olympic` | Olympic National Park | ITINERARY |
| `enchantments` | Enchantments (Alpine Lakes Wilderness) | ZONE |

## Installation

Requires Python 3.10+.

```bash
git clone <repo-url>
cd permit_finder
pip install -e ".[dev]"
```

Dependencies: `requests`, `shapely`, `rich`

## Quick Start

```bash
# See all supported parks
wa-permits --list-parks

# Find all 5-night chains for North Cascades (mock data, no network calls)
wa-permits --park north-cascades --start-date 2026-07-15 --nights 5

# Same query with live Recreation.gov + OpenStreetMap data
wa-permits --park north-cascades --start-date 2026-07-15 --nights 5 --live

# Only show chains where every site has >= 2 permits remaining
wa-permits --park olympic --start-date 2026-07-15 --nights 5 --live \
    --permit-count 2 --available

# Include trailhead connections (trails sharing a parking lot)
wa-permits --park north-cascades --start-date 2026-07-15 --nights 5 --live \
    --trailhead

# Search all parks and export as JSON
wa-permits --park all --start-date 2026-07-15 --nights 5 --live \
    --limit 50 --json > chains.json
```

## Commands

### `--list-parks`

Print all supported park keys and exit.

```bash
wa-permits --list-parks
```

### `--list-areas`

Show every campsite in the park, grouped by district, with type and coordinates. Fast — fetches the site list only, no availability calls.

> **Requires `--live`** to show real park data. Without it, synthetic mock sites are shown (useful for testing the tool, not for planning a trip).

```bash
wa-permits --park olympic --list-areas --live
wa-permits --park rainier --list-areas --live
```

### `--list-availability`

Shows every campsite in the park with per-night permit counts for your date window. Useful for scouting availability before running a chain search, or for understanding how competitive a date range is across the whole park.

```bash
wa-permits --park olympic --list-availability --start-date 2026-07-15 --nights 5
wa-permits --park olympic --list-availability --start-date 2026-07-15 --nights 5 --live --area Hoh
```

#### Stats panel

Above the table, a summary panel shows how contested the window is at a glance:

| Status | Meaning |
|---|---|
| **N open** | Campsites where every night has ≥1 permit remaining — bookable online any night |
| **N partial** | Campsites where some nights are open and some are full or walk-up — check per-night columns |
| **N booked** | Campsites where every night is at 0 — fully booked, no permits anywhere |
| **N walk-up** | Campsites where all dates show in-station only — no online booking; obtain at a ranger station |
| **N no data** | Campsites with no availability data returned — typically pre-season before reservations open |

If `booked` is high relative to the total, consider shifting your dates. `walk-up` sites can still be used but require visiting a ranger station on the day of your trip.

#### Table columns

| Column | Description |
|---|---|
| **District** | Named area of the park (e.g. "Hoh", "Sol Duc"). Sites are grouped and separated by district. |
| **Division** | Individual campsite name — exactly as it appears on Recreation.gov. Names often include useful context: `(No Campfires)` means fire restrictions apply, `Stock Camp` is for stock/horse parties, `Group Site` is for larger groups, and some include distance from the trailhead (e.g. `14 miles from trailhead`). |
| **Date columns** | One column per night in your window showing permit status for that site on that night. |

#### Cell values

| Value | Meaning |
|---|---|
| **`100`** (or any number) | Permits remaining for online booking. `100` typically means wide open; `1` or `2` means nearly full |
| **`full`** | 0 remaining — that night is sold out online and no walk-up quota exists |
| **`stn`** | Walk-up / in-station only — the online quota is 0, but ranger-station permits are still available. Must obtain in person at the park entrance station |
| **`·`** | No data — API returned nothing for this date (pre-season or not yet open) |

> **What is "In Station"?** Recreation.gov tracks two quota types: online reservations and ranger-station walk-ups. When the online quota hits 0 but the walk-up quota is still positive, the date shows as "In Station". This tool shows those dates as `stn` — they're not blocked but require a visit to the park entrance station, typically on the morning of your trip.

### Chain search (default)

Chain search runs automatically when `--park`, `--start-date`, and `--nights` are provided. No extra flag needed.

```bash
wa-permits --park rainier --start-date 2026-07-22 --nights 7
wa-permits --park rainier --start-date 2026-07-22 --nights 7 --live
```

## Full CLI Reference

| Flag | Default | Description |
|---|---|---|
| `--park PARK [PARK ...]` | required | Park(s) to search. Use `all` for every park. Valid: `rainier`, `north-cascades`, `olympic`, `enchantments` |
| `--start-date YYYY-MM-DD` | required | First night of the trip |
| `--nights N` | required | Number of nights |
| `--live` | off | Fetch real-time data from Recreation.gov and OpenStreetMap |
| `--available` | off | Only show chains where every night has >= `--permit-count` permits remaining |
| `--permit-count N` | `1` | Permits needed (party size). Used with `--available` |
| `--trailhead` | off | Include connections between trails that share a trailhead parking lot. Excluded by default because a hiker must leave the trail system to cross a parking lot |
| `--area AREA [AREA ...]` | all areas | Restrict to districts matching these substrings (case-insensitive). Reduces API calls |
| `--limit N` | no limit | Cap the number of chains returned. Applied after all filters |
| `--detail-limit N` | `25` | Max districts to query for availability. Reduces live API traffic |
| `--no-exact-length` | off | Return chains of all lengths from 1 up to `--nights`, grouped longest-first |
| `--verbose` | off | Print every HTTP request to stderr. Only effective with `--live` |

### Output format flags (mutually exclusive)

| Flag | Description |
|---|---|
| `--overview` | Summary table only (entry site, exit site, date range, min availability) |
| `--chains` | Per-chain night-by-night detail only |
| `--detail` | Summary table + per-chain detail (default) |
| `--json` | Structured JSON to stdout; progress messages go to stderr |

### Filtering behavior

**Without `--available`**: all physically possible chains are shown with availability counts. Useful for route planning before booking season opens.

**With `--available`**: only chains where every night has `remaining >= permit_count` permits available **online** are shown. Walk-up (`stn`) nights do not satisfy this filter. Use this flag when actively trying to book online.

### API traffic management

Live queries make one Recreation.gov call per connected site (with a 0.5s rate limit). Two optimizations reduce total calls:

- **Probe-first**: the first site in a district is fetched. If every target date is fully booked (0) or walk-up only (-2), all remaining sites in that district are assumed to match — no further calls needed.
- **Pre-season short-circuit**: an empty response means availability data doesn't exist yet; the run stops without additional calls.

Use `--area` to restrict to specific districts and `--detail-limit` to cap how many districts are queried.

## Planning Your Trip: A Camper's Guide

### Terminology

| Term | Definition |
|---|---|
| **Permit** | Authorization to camp at one specific site on one specific night. Each night of a multi-night trip requires its own permit. |
| **Campsite** | A named overnight location in the backcountry (e.g. "Hoh Lake Camp"). This is what you search for and book on Recreation.gov. |
| **Division** | Recreation.gov's internal name for a campsite. You won't see this word on their website — it's what their API calls each site, and what this tool uses in its output. |
| **District / Area** | A named zone grouping multiple campsites within a park (e.g. "Hoh River", "Sol Duc"). Used to navigate large parks and filter searches. |
| **Quota** | The maximum number of groups allowed at a campsite on a given night — typically 1–12. Once a site reaches its quota it shows as fully booked. |
| **Chain** | A sequence of trail-adjacent campsites, one per night, forming a continuous multi-night route. Every site in a chain must be reachable from the previous one by hiking trail — no road crossings or parking lots. |
| **Trail junction** | A point where two trails physically intersect on the ground. The tool detects these from shared GPS node IDs in OpenStreetMap trail data. Sites on both sides of a junction can be chained together. |
| **Trailhead connection** | Two separate trails that happen to share a parking lot at their start/end points. To move between them, a hiker must leave the trail system and cross the parking lot. Excluded from chains by default — enable with `--trailhead`. |
| **Walk-up / In-station** | A permit state where the online quota is 0 but ranger-station walk-up permits are still available. Shown as `stn` in the availability table. These cannot be booked online — you must visit the park entrance station, typically on the morning of your trip. Walk-up nights do not count as "available" for `--available` filtering. |
| **Isolated site** | A campsite whose GPS coordinates could not be matched to any trail polyline (or has no GPS coordinates at all). These sites appear in `--list-areas` but can never appear in a chain because no trail connection can be established. |
| **Availability** | The number of permits still remaining at a site for a given night. Zero means fully booked online; anything above zero means you can still book it. `-2` internally means walk-up only. |
| **Lottery** | A randomized selection process run weeks before general on-sale for high-demand parks. You apply for a specific itinerary; winners get priority booking access before the public. Not all parks run lotteries. |

---

Washington's most popular backcountry areas — Rainier, Olympic, North Cascades, and the Enchantments — all require overnight permits. Permits are limited, issued per campsite per night, and booked through [Recreation.gov](https://www.recreation.gov). The challenge for multi-night trips is that you need a sequence of campsites where each consecutive pair is reachable by trail **and** each night's permit is actually available. Finding that sequence manually across dozens of sites and nights is tedious. That's what this tool does.

### Understanding the permit system

Each park divides its backcountry into named campsites. On Recreation.gov's website you search by campsite name (e.g. "Hoh Lake Camp"); internally the API calls these **divisions**, which is the term used in this tool's output and documentation. Every campsite has an independent nightly quota — typically 1–12 permitted groups. When a site is fully booked for a given night, no one else can stay there. A **permit chain** is a sequence of campsites, one per night, where every site is trail-adjacent to the next. You book each night of the chain as a separate reservation on Recreation.gov.

Permits open on a fixed calendar each year (2026 dates):

- **Lottery**: several weeks before general sale. You apply for a specific itinerary; winners get priority booking access. Not all parks run lotteries.
- **Early-access / general on-sale**: after the lottery window, remaining permits go on sale to the public in mid-to-late April (Olympic and Enchantments Apr 15, Rainier Apr 25, North Cascades Apr 29). These sell out in minutes for the most popular parks and dates.
- **Cancellations**: permits get returned throughout the season as people cancel. Checking regularly — or building a monitoring script on top of this tool's `--json` output — is often the only way to find availability after opening day.

### First-time setup: warming the cache

The first time you run `--live` for a park, the tool fetches two things: campsite data from Recreation.gov and trail geometry from OpenStreetMap. The OpenStreetMap fetch can take 30–60 seconds depending on the Overpass mirror. Both are cached locally for 30 days, so every subsequent run skips these network calls and builds the graph instantly.

```bash
# First run — expect 30–60 seconds while OSM trail data is fetched and cached
wa-permits --park olympic --start-date 2026-07-15 --nights 3 --live

# All subsequent runs within 30 days — graph builds from disk, near-instant
wa-permits --park olympic --start-date 2026-07-20 --nights 3 --live
```

### Scenario 1: Planning a trip from scratch

Use this workflow when you have a date range and want to know which complete multi-night routes are actually bookable.

**Step 1 — Explore the park's geography**

See how the park is organized into areas (districts). Fast — fetches the site list only, no availability data.

```bash
wa-permits --park olympic --list-areas --live
```

This shows every campsite grouped by district (e.g. "Hoh", "Sol Duc"), with its type and GPS coordinates. Note any sites labeled as isolated — these have no GPS data and cannot appear in chains. Use this to decide which part of the park you want to hike through before narrowing your search.

**Step 2 — Find all possible routes**

Run a chain search with `--live` to build the real trail graph and see every valid route for your dates. Skip `--available` for now — this shows all physically connected routes regardless of permit availability, so you can identify routes you like before checking whether they're open.

```bash
wa-permits --park olympic --start-date 2026-07-15 --nights 5 --live
```

The route column shows the full path: `Entry Camp → Mid Camp → Exit Camp`. Each night shows its current availability count. If it's pre-season and permits aren't open yet, availability will show as no data (`·`) — that's fine; the route itself is valid.

> **Mock mode** (`--live` omitted): without `--live`, the tool uses built-in synthetic data based on a North Cascades trail topology. Every park shows the same mock sites regardless of which `--park` you specify. This is only useful for testing the tool itself — always use `--live` for real trip planning.

**Step 3 — Filter to bookable routes**

Once permits go on sale, add `--available` to show only chains where every single night has an open permit online.

```bash
wa-permits --park olympic --start-date 2026-07-15 --nights 5 --live --available
```

If you're going with a group, add `--permit-count` to filter to routes where every night has enough permits for your whole party:

```bash
wa-permits --park olympic --start-date 2026-07-15 --nights 5 --live --available --permit-count 3
```

**Step 4 — Narrow to a specific area**

If Step 3 returns too many results, or you only want to hike a specific corridor, filter by district name:

```bash
wa-permits --park olympic --start-date 2026-07-15 --nights 5 --live --available --area Hoh
```

District names come from Step 1. Partial matches work — `--area Hoh` matches "Hoh River" and any other district containing "Hoh". Multiple areas: `--area Hoh "Sol Duc"`.

**Step 5 — Get the full night-by-night breakdown**

Once you've found a route you want, use `--chains` to see every night in detail: which site, which date, and exactly how many permits remain.

```bash
wa-permits --park olympic --start-date 2026-07-15 --nights 5 --live --available --area Hoh --chains
```

Keep this output open while booking on Recreation.gov. Book each night as a separate reservation — search for the exact site name and date shown in the output.

---

### Scenario 2: Completing a partial chain

Use this workflow when you've already booked some nights and need to find adjacent open campsites to complete your itinerary.

**Step 1 — Check what's available across all nights**

Run `--list-availability` for the full date window. This gives you a flat table of every site with per-night permit counts — not filtered to chains, so you can see the raw picture across the whole park.

```bash
wa-permits --park olympic --list-availability --start-date 2026-07-15 --nights 7 --live
```

The stats panel above the table shows how many sites are **open all nights**, **partial**, and **fully booked**. If most sites are fully booked, consider shifting your dates.

**Step 2 — Focus on the district where your existing bookings are**

If you've already booked Night 1 at "Sol Duc Falls Camp" (Sol Duc district), restrict to that area to see only adjacent options and cut down API calls:

```bash
wa-permits --park olympic --list-availability --start-date 2026-07-15 --nights 7 --live --area "Sol Duc"
```

**Step 3 — Find chains that pass through your booked site**

Run a chain search for the same date range and area. Look for routes that include the site you've already booked — the full entry-to-exit path is shown, so you can visually match your existing reservation to a chain and see what the tool recommends for the remaining nights.

```bash
wa-permits --park olympic --start-date 2026-07-15 --nights 7 --live --available --area "Sol Duc"
```

**Step 4 — Try shorter chains if the full window isn't available**

If no complete 7-night route is fully open, use `--no-exact-length` to find the longest partial chain that works:

```bash
wa-permits --park olympic --start-date 2026-07-15 --nights 7 --live --available --area "Sol Duc" --no-exact-length
```

Results are grouped longest-first. A 5-night chain might be fully available even if no 7-night chain is — you can then decide whether to shorten the trip or hunt for the remaining nights manually on Recreation.gov.

**Step 5 — Monitor for cancellations**

Availability shifts throughout the season as people cancel. Capture a JSON snapshot and diff it later, or pipe to a notification script:

```bash
wa-permits --park olympic --start-date 2026-07-15 --nights 7 --live --available --area "Sol Duc" --json > snapshot.json
```

---

### Tips

- **Book fast.** Once you identify a bookable chain, go straight to Recreation.gov. Permits at popular parks on peak summer weekends are gone within seconds of going on sale. Have site names and dates ready before you click.
- **Check multiple parks.** Use `--park all` to search every supported park at once. If Rainier is fully booked, Olympic or North Cascades may still have openings for the same dates.
- **Walk-up sites are an option.** Sites showing `stn` have no online permits left but ranger-station walk-up slots remain. You can build a chain around them if you're willing to visit the entrance station on the day of your trip — just be aware `--available` filtering will exclude them.
- **Group size matters.** Many sites have quotas of 1–2 groups per night. Set `--permit-count` to your party size so you only see routes where enough permits are available for everyone.
- **Trailhead connections.** By default, chains only include sites reachable without leaving the trail. Add `--trailhead` to unlock connections between separate trail systems that share a parking area — useful if you're doing a point-to-point route with a car shuttle.

## Disk cache

When `--live` is used, site and trail data are cached locally to avoid redundant network calls on repeated runs:

| Data | Cache key | TTL |
|---|---|---|
| Rec.gov site list (names, GPS, districts) | `sites:<facility_id>` | 30 days |
| OpenStreetMap trail polylines | `trails:<facility_id>` | 30 days |

**Location:** `~/.cache/permit-finder/cache.db` — a single SQLite file, no server required.

Override the directory with `PERMIT_FINDER_CACHE_DIR=/path/to/dir`.

**Behavior:**
- On the first `--live` run for a park, site data is fetched from Recreation.gov and trail polylines are fetched from OpenStreetMap's Overpass API. Both are written to the cache.
- On subsequent runs within 30 days, both are read from disk — no network calls needed. The trail graph builds instantly.
- Availability data is **never cached** — it changes daily and is always fetched live.

**Manual cache management:**

```python
from permit_engine.cache import get_default_cache

cache = get_default_cache()
cache.stats()                        # entry counts by type
cache.clear()                        # wipe the entire cache
cache.invalidate("sites:4098362")    # invalidate one park's site list
cache.invalidate("trails:4098362")   # invalidate one park's trail geometry
```

Or delete the file directly: `rm ~/.cache/permit-finder/cache.db`

**If you see 0 edges in live mode**, the cached trail data may be stale or empty. Invalidate both keys and re-run:

```bash
python -c "
from permit_engine.cache import get_default_cache
c = get_default_cache()
c.invalidate('sites:4098362')
c.invalidate('trails:4098362')
print('Cache cleared')
"
```

## Mock data

Without `--live`, built-in mock data is used. It is based on real North Cascades East Bank Trail division IDs and GPS coordinates from the rec.gov API (March 2026). Trail topology is encoded as three synthetic OSM-shaped trail polylines covering all adjacency scenarios: a linear four-camp trail, a genuine mid-trail junction (Nightmare Loop), and a trailhead connection (Copper Ridge). Availability covers realistic booking scenarios including fully-booked nights, walk-up-only nights, and sites with no GPS coordinates. All tests run against mock data — no network calls required.

## JSON output schema

```bash
wa-permits --park olympic --start-date 2026-07-15 --nights 5 --live --json
```

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-07-10T14:00:00Z",
  "query": {
    "parks": ["olympic"],
    "start_date": "2026-07-15",
    "nights": 5,
    "source": "live",
    "exact_length": true,
    "limit": null
  },
  "parks": [
    {
      "park": "olympic",
      "display_name": "Olympic National Park",
      "chains": [...]
    }
  ]
}
```

## Running tests

```bash
pytest              # run all 75 tests
pytest -v           # verbose output
pytest tests/test_graph.py       # graph construction and adjacency tests
pytest tests/test_search.py      # DFS chain search and availability filter tests
pytest tests/test_chain.py       # Chain dataclass property tests
pytest tests/test_mock.py        # mock data shape validation
pytest tests/test_cli_output.py  # CLI output formatting tests
```

All tests are fully offline (HTTP is mocked).

## Project structure

```
src/permit_engine/
  cli.py      — wa-permits entry point and argument parsing
  api.py      — live API calls (Recreation.gov + OpenStreetMap Overpass)
  mock.py     — offline mock data (drop-in replacement for api.py)
  graph.py    — trail graph builder (GPS snap to OSM polylines → adjacency)
  search.py   — DFS chain finder and availability annotation
  cache.py    — SQLite disk cache for stable API responses (sites + trails)

tests/
  conftest.py          — shared fixtures (built from mock data)
  test_graph.py        — graph structure, GPS snap, trailhead vs junction tests
  test_search.py       — DFS correctness and availability filtering
  test_chain.py        — Chain dataclass properties
  test_mock.py         — mock data shape validation
  test_cli_output.py   — output formatting tests
```

## Data sources

All APIs require no authentication:

| Data | Endpoint |
|---|---|
| Permit sites (names, GPS coordinates, districts) | `GET recreation.gov/api/permitcontent/{facility_id}` |
| Trail polylines (OSM node sequences + GPS points) | OpenStreetMap Overpass API (4 public mirrors, 30-day cache) |
| Per-night availability (ITINERARY) | `GET recreation.gov/api/permititinerary/{facility_id}/division/{div_id}/availability/month` |
| Per-night availability (ZONE) | `GET recreation.gov/api/permitinyo/{facility_id}/availabilityv2` |

## Current status

**Version 6.0.0** — stable, 75 tests passing.

- Trail adjacency determined by GPS snap to OpenStreetMap trail polylines — works for any park with OSM trail data
- Genuine trail junctions (mid-trail shared OSM node) are always connected
- Trailhead connections (parking-lot shared endpoint) are excluded by default, enabled with `--trailhead`
- Sites with missing GPS coordinates (`lat=0, lon=0`) are included as isolated nodes but never contribute edges
- Overpass mirror fallback: 4 public mirrors tried in order; only accepts results with non-empty `elements`
- Both site and trail data are cached for 30 days to minimize network calls
- JSON output is pipeline-friendly: progress prints to stderr, clean JSON to stdout

## Tech stack

Python 3.10, requests, shapely 2.x, rich 13.x, pytest
