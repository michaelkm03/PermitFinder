# wa-permits

A Python CLI that finds valid multi-night backpacking chains in Washington State national parks where every campsite has available permits. Built on real-time data from Recreation.gov and OpenStreetMap — no account or API key required.

## How it works

1. **Trail graph** — fetches all permit campsites from Recreation.gov (`/api/permitcontent`) and hiking trails from the OpenStreetMap Overpass API. Sites that snap within ~200m of a shared trail polyline are connected as adjacent graph nodes. Trailhead-only connections (two trails meeting at a parking lot) are distinguished from genuine mid-trail junctions and excluded by default.

2. **Availability** — fetches per-night permit quota from Recreation.gov for each connected site. ITINERARY parks use `/api/permititinerary/.../availability/month`; ZONE parks (Enchantments) use `/api/permitinyo/.../availabilityv2`. An in-process cache avoids repeat calls within a session.

3. **DFS search** — walks the trail graph to find every valid multi-night sequence, annotating each link with the remaining permit count for that specific night. Results can be filtered, sorted, capped, and output as structured JSON.

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
wa-permits --park north-cascades --list-chains --start-date 2026-07-15 --nights 5

# Same query with live Recreation.gov + OpenStreetMap data
wa-permits --park north-cascades --list-chains --start-date 2026-07-15 --nights 5 --live

# Only show chains where every site has >= 2 permits remaining
wa-permits --park olympic --list-chains --start-date 2026-07-15 --nights 5 --live \
    --permit-count 2 --available

# Search all parks and export as JSON
wa-permits --park all --list-chains --start-date 2026-07-15 --nights 5 --live \
    --limit 50 --json > chains.json
```

## Commands

### `--list-parks`

Print all supported park keys and exit.

```bash
wa-permits --list-parks
```

### `--list-areas`

Show district names and site counts for a park. Fast — fetches site list only, no availability calls.

```bash
wa-permits --park olympic --list-areas
wa-permits --park olympic --list-areas --live   # use real site data
```

### `--list-availability`

Flat table of every campsite's per-night permit counts: District / Division / one column per night. Above the table, a summary line breaks down the full site count:

- **N fully open** — every night in the window has at least 1 permit remaining; bookable on any night
- **N partial** — some nights open, some fully booked; useful depending on which specific nights you need
- **N fully booked** — every night is at 0 remaining; dead ends for these dates

```bash
wa-permits --park olympic --list-availability --start-date 2026-07-15 --nights 5
wa-permits --park olympic --list-availability --start-date 2026-07-15 --nights 5 --live --area Hoh
```

### `--list-chains`

Find and display multi-night permit chains. Requires `--park`, `--start-date`, and `--nights`.

```bash
wa-permits --park rainier --list-chains --start-date 2026-07-22 --nights 7
wa-permits --park rainier --list-chains --start-date 2026-07-22 --nights 7 --live
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
| `--trailhead` | off | Include connections between sites that share a trailhead parking lot |
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

**With `--available`**: only chains where every night has `remaining >= permit_count` are shown. Use this when actively trying to book.

### `--trailhead`

By default, connections between sites on separate trails that share a trailhead parking lot are excluded — a hiker must exit the trail system to make that transition. Pass `--trailhead` to include them.

Genuine mid-trail junctions (a spur branching off a main trail mid-route) are always included regardless of this flag.

### API traffic management

Live queries make one Recreation.gov call per connected site (with a 0.5s rate limit). Two optimizations reduce total calls:

- **Probe-first**: the first site in a district is fetched, and if every target date is fully booked, all remaining sites in that district are assumed booked — no further calls needed.
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
| **Chain** | A sequence of trail-adjacent campsites, one per night, forming a continuous multi-night route. Every site in a chain must be reachable from the previous one by trail. |
| **Availability** | The number of permits still remaining at a site for a given night. Zero means fully booked; anything above zero means you can still book it. |
| **Lottery** | A randomized selection process run weeks before general on-sale for high-demand parks. You apply for a specific itinerary; winners get priority booking access before the public. |
| **Trail junction** | A point where two trails meet mid-route. A hiker reaches it naturally while walking the trail — no parking lot crossing required. Connections through junctions are always included. |
| **Trailhead connection** | A point where two separate trails share the same parking lot or road access. Getting from one trail to the other requires leaving the trail system. Excluded by default; use `--trailhead` to include. |

---

Washington's most popular backcountry areas — Rainier, Olympic, North Cascades, and the Enchantments — all require overnight permits. Permits are limited, issued per campsite per night, and booked through [Recreation.gov](https://www.recreation.gov). The challenge for multi-night trips is that you need a sequence of campsites where each consecutive pair is reachable by trail **and** each night's permit is actually available. Finding that sequence manually across dozens of sites and nights is tedious. That's what this tool does.

### Understanding the permit system

Each park divides its backcountry into named campsites. On Recreation.gov's website you search by campsite name (e.g. "Hoh Lake Camp"); internally the API calls these **divisions**, which is the term used in this tool's output and documentation. Every campsite has an independent nightly quota — typically 1–12 permitted groups. When a site is fully booked for a given night, no one else can stay there. A **permit chain** is a sequence of campsites, one per night, where every site is trail-adjacent to the next. You book each night of the chain as a separate reservation on Recreation.gov.

Permits open on a fixed calendar each year:

- **Lottery**: several weeks before general sale. You apply for a specific itinerary; winners get priority booking access. Not all parks run lotteries.
- **Early-access / general on-sale**: after the lottery window, remaining permits go on sale to the public, usually in late April. These sell out in minutes for the most popular parks and dates.
- **Cancellations**: permits get returned throughout the season. Checking regularly (or building a monitoring script on top of this tool's `--json` output) is often the only way to find availability after opening day.

### Scenario 1: Planning a trip from scratch

Use this workflow when you have a date range and want to know which complete multi-night routes are actually bookable.

**Step 1 — Explore the park's geography**

Start by seeing how the park is organized into areas (districts). This is fast — no availability data is fetched.

```bash
wa-permits --park olympic --list-areas
```

This shows every named district (e.g. "Hoh River", "Sol Duc") and how many permit sites are in each. Use this to decide which part of the park you want to hike through before narrowing your search.

**Step 2 — See all possible routes (offline, no network needed)**

Run a chain search against mock data first. This tells you which physical routes exist in the trail graph — useful before booking season opens when real availability data isn't available yet.

```bash
wa-permits --park olympic --list-chains --start-date 2026-07-15 --nights 5
```

The output shows every valid sequence of campsites for your date range. The route column shows the full path: `Entry Camp → Mid Camp → Exit Camp`. Availability counts are shown for each night but are synthetic (mock) at this stage — what matters here is finding routes that go through the terrain you want.

**Step 3 — Check real availability**

Once booking season opens, add `--live` and `--available` to fetch real permit counts and filter to only the routes where every single night is open.

```bash
wa-permits --park olympic --list-chains --start-date 2026-07-15 --nights 5 --live --available
```

If you're going with a group, set `--permit-count` to your party size so only routes with enough permits for everyone are shown:

```bash
wa-permits --park olympic --list-chains --start-date 2026-07-15 --nights 5 --live --available --permit-count 3
```

**Step 4 — Narrow to a specific area**

If Step 3 returns too many results, or you only want to hike a specific part of the park, filter by district name:

```bash
wa-permits --park olympic --list-chains --start-date 2026-07-15 --nights 5 --live --available --area Hoh
```

District names come from Step 1. Partial matches work — `--area Hoh` matches "Hoh River" and any other district containing "Hoh".

**Step 5 — Get the full night-by-night breakdown**

Once you've found a route you like, use `--chains` to see every night in detail: which site, which date, and how many permits remain.

```bash
wa-permits --park olympic --list-chains --start-date 2026-07-15 --nights 5 --live --available --area Hoh --chains
```

This is the view to keep open while booking on Recreation.gov. Book each night of the chain as a separate reservation — search for the exact site name and date shown in the output.

---

### Scenario 2: Completing a partial chain

Use this workflow when you've already booked some nights and need to find adjacent open campsites to connect your itinerary.

**Step 1 — Check what's available across all nights**

Run `--list-availability` for the full date window you care about. This gives you a flat table of every site in the park, with per-night permit counts — not filtered to chains yet, so you can see the raw picture.

```bash
wa-permits --park olympic --list-availability --start-date 2026-07-15 --nights 7 --live
```

Above the table a summary line shows: **N fully open** (bookable every night), **N partial** (some nights available), **N fully booked** (no availability at all). Use this to quickly gauge how competitive the window is before drilling into individual sites.

**Step 2 — Focus on the district where your existing bookings are**

If you've already booked Night 1 at "Sol Duc Falls Camp" (in the Sol Duc district), restrict availability and chain searches to that area so you only see adjacent options:

```bash
wa-permits --park olympic --list-availability --start-date 2026-07-15 --nights 7 --live --area "Sol Duc"
```

**Step 3 — Find chains that include your existing nights**

Run `--list-chains` for the same date range. Look for routes that pass through the site(s) you've already booked. The chain output shows the full entry-to-exit path, so you can visually match your existing reservation to a chain and see what the tool suggests for the remaining nights.

```bash
wa-permits --park olympic --list-chains --start-date 2026-07-15 --nights 7 --live --available --area "Sol Duc"
```

**Step 4 — Try variable-length chains if the full window isn't available**

If no complete 7-night route has every permit open, use `--no-exact-length` to find the longest possible chain that starts from your existing booking and works outward:

```bash
wa-permits --park olympic --list-chains --start-date 2026-07-15 --nights 7 --live --available --area "Sol Duc" --no-exact-length
```

Results are grouped longest-first. A 5-night chain might be fully available even if no 7-night chain is — you can then decide whether to shorten the trip or manually hunt for the remaining 2 nights on Recreation.gov.

**Step 5 — Monitor for cancellations**

Availability changes throughout the season as people cancel or modify reservations. Use `--json` to capture a snapshot and diff it over time, or run the tool on a schedule to alert you when a site you need opens up:

```bash
wa-permits --park olympic --list-chains --start-date 2026-07-15 --nights 7 --live --available --area "Sol Duc" --json > snapshot.json
```

---

### Tips

- **Book fast.** Once you identify a bookable chain, go straight to Recreation.gov. Permits at popular parks on peak summer weekends are gone within seconds of going on sale. Have the site names and dates ready before you click.
- **Check multiple parks.** Use `--park all` to search every supported park at once. If Rainier is fully booked, Olympic or North Cascades may still have openings for the same dates.
- **Pre-season planning.** The tool works without `--live`. Run it with mock data to understand the trail network and identify your preferred routes before permits go on sale — then re-run with `--live --available` on opening day.
- **Group size matters.** Many sites have quotas of 1–2 groups per night. If you're going with a large group, set `--permit-count` equal to your party size; a site showing "2 left" when you need 3 is effectively full for you.
- **Trailhead connections.** Some routes that look connected on a map actually require crossing a parking lot between two separate trailheads. The tool excludes these by default. Add `--trailhead` if you're open to car-shuttling between trailheads as part of your route.

## Mock data

Without `--live`, built-in mock data is used. It is based on real North Cascades East Bank Trail division IDs and coordinates from the rec.gov API (March 2026), with synthetic availability covering realistic booking scenarios (full nights, partial availability, trailhead junction topology). All tests run against mock data — no network calls required.

## JSON output schema

```bash
wa-permits --park olympic --list-chains --start-date 2026-07-15 --nights 5 --live --json
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
pytest              # run all 71 tests
pytest -v           # verbose output
pytest tests/test_graph.py    # graph construction and adjacency tests
pytest tests/test_search.py   # DFS chain search and availability filter tests
pytest tests/test_chain.py    # Chain dataclass property tests
pytest tests/test_mock.py     # mock data shape validation
pytest tests/test_cli_output.py  # CLI output formatting tests
```

All tests are fully offline (HTTP is mocked).

## Project structure

```
src/permit_engine/
  cli.py      — wa-permits entry point and argument parsing
  api.py      — live API calls (Recreation.gov + OpenStreetMap Overpass)
  mock.py     — offline mock data (drop-in replacement for api.py)
  graph.py    — trail graph builder (site snapping, adjacency, trailhead detection)
  search.py   — DFS chain finder and availability annotation

tests/
  conftest.py          — shared fixtures (built from mock data)
  test_graph.py        — graph structure and adjacency tests
  test_search.py       — DFS correctness and availability filtering
  test_chain.py        — Chain dataclass properties
  test_mock.py         — mock data shape validation
  test_cli_output.py   — output formatting tests
```

## Data sources

All APIs require no authentication:

| Data | Endpoint |
|---|---|
| Permit sites (names, GPS, districts) | `GET recreation.gov/api/permitcontent/{facility_id}` |
| Per-night availability (ITINERARY) | `GET recreation.gov/api/permititinerary/{facility_id}/division/{div_id}/availability/month` |
| Per-night availability (ZONE) | `GET recreation.gov/api/permitinyo/{facility_id}/availabilityv2` |
| Hiking trails | OpenStreetMap Overpass API (multiple mirrors) |

## Current status

**Version 5.0.0** — stable, all 71 tests passing.

- Enchantments (ZONE permit type) added alongside the three ITINERARY parks
- Live availability data is pre-season for most parks until mid-April 2026 (Olympic/Enchantments Apr 15, Rainier Apr 25, North Cascades Apr 29)
- The DFS search is optimized to skip isolated sites (sites with no trail neighbors) to avoid unnecessary API calls
- JSON output is pipeline-friendly: progress prints to stderr, clean JSON to stdout

## Tech stack

Python 3.10, requests, shapely 2.x, rich 13.x, pytest
