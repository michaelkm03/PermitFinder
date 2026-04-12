# PermitFinder — Product & Engineering Backlog
**Version:** 1.1
**Status:** Approved
**Product Owner:** Michael Montgomery
**Engineering Lead:** Michael Montgomery
**Last Updated:** 2026-03-17

---

## Sign-Off

| Role | Name | Date |
|------|------|------|
| Product Owner | Michael Montgomery | 2026-03-17 |
| Engineering Lead | Michael Montgomery | 2026-03-17 |

> Stories in **Sprint 1** are approved and scheduled. Stories in the **Backlog**
> are approved by product and engineering but not yet assigned to a sprint.
> All feature stories have been reviewed for technical feasibility by the
> engineering lead.

---

## Table of Contents

⚪ Not Started &nbsp; 🔵 In Progress &nbsp; ✅ Done

### Sprint 1 — Features
| Status | Ticket | Feature | Points | Priority |
|--------|--------|---------|--------|----------|
| ⚪ | <nobr>[PF-101](#pf-101--availability-alerts--notify-when-a-permit-opens-up)</nobr> | Availability Alerts — poll Recreation.gov and notify when a permit chain opens up | 5 | P0 |
| ⚪ | <nobr>[PF-102](#pf-102--multi-park-search)</nobr> | Multi-Park Search — run a single search across all supported parks at once | 3 | P0 |
| ⚪ | <nobr>[PF-103](#pf-103--json-output-for-all-commands)</nobr> | JSON Output — machine-readable output flag for all CLI commands | 2 | P1 |

### Sprint 1 — Engineering
| Status | Ticket | Task | Points | Priority |
|--------|--------|------|--------|----------|
| ⚪ | <nobr>[PF-110](#pf-110--ci-pipeline-github-actions)</nobr> | CI Pipeline — GitHub Actions build and test on every push | 2 | P0 |
| ⚪ | <nobr>[PF-111](#pf-111--add-type-annotations-and-mypy)</nobr> | Type Annotations & mypy — annotate api.py and cli.py; add mypy to CI | 3 | P1 |
| ⚪ | <nobr>[PF-112](#pf-112--remove-dead-code--_is_group_site)</nobr> | Remove Dead Code — delete unused `_is_group_site()` from api.py | 1 | P1 |

### Backlog — Features
| Status | Ticket | Feature | Points |
|--------|--------|---------|--------|
| ⚪ | <nobr>[PF-201](#pf-201--saved-searches)</nobr> | Saved Searches — save and re-run named search configurations locally | 5 |
| ⚪ | <nobr>[PF-202](#pf-202--trip-export--ical-and-plain-text)</nobr> | Trip Export — export a permit chain as an iCal file or plain-text itinerary | 3 |
| ⚪ | <nobr>[PF-203](#pf-203--enchantments-zone-full-support)</nobr> | Enchantments ZONE Support — complete end-to-end support for ZONE-type permits | 5 |

---

## Story Point Scale

| Points | Effort |
|--------|--------|
| 1 | Trivial — under 1 hour |
| 2 | Small — half a day |
| 3 | Medium — 1 day |
| 5 | Large — 2–3 days |
| 8 | X-Large — 1 week |

---

## Sprint 1 — Search & Availability Expansion
**Sprint Goal:** Expand permit search to support multi-park queries and
availability alerts, addressing the two most common user requests from beta.

---

### PF-101 · Availability Alerts — Notify When a Permit Opens Up
| Epic | Type | Points | Priority |
|------|------|--------|----------|
| Notifications | Feature | 5 | P0 |

**Product Request:**
> "The most common feedback we get is 'I found a route I want but there were no
> permits available.' Users need to set an alert and get notified when a slot
> opens up — checking manually every day is not a viable workflow."
> — Product, 2026-03-10

**Functionality:**
A `--watch` mode runs the chain search on a configurable polling interval
(default 15 minutes). On each poll, it fetches live availability from
Recreation.gov and runs the chain search. If a matching chain is found that
was not present in the previous poll result, it is printed to the terminal
and flagged as new. The loop runs until the user exits with `Ctrl+C`, at which
point a summary of alerts fired is printed.

**Modules Affected:**

| Module | Change |
|--------|--------|
| `cli.py` | New `--watch` flag; polling loop; diff logic between poll results; summary on exit |
| `search.py` | No structural changes; `find_chains()` and `filter_by_availability()` are called per poll cycle |
| `api.py` | No changes; existing `fetch_availability()` is called on each poll |

**External APIs:**

| API | Usage |
|-----|-------|
| Recreation.gov availability endpoint | Polled on each interval; rate-limit headers respected |

**Database / Local State:** None — previous poll results are held in-memory for the duration of the watch session only.

**Kafka Topics:** N/A — CLI application.

**Happy Path:**
1. User runs `wa-permits --watch --park rainier --nights 3 --from 2026-07-01 --to 2026-07-31`
2. First poll runs immediately; results are printed; baseline is stored in memory
3. After 15 minutes, a second poll runs
4. A new chain is found that was not in the baseline → printed with a `[NEW]` label
5. User presses `Ctrl+C`; summary prints: "3 polls completed, 1 alert fired"

**Edge Cases:**
- Recreation.gov returns HTTP 429 (rate limited) → back off exponentially (e.g., 30s, 60s, 120s); do not crash; log the backoff
- Recreation.gov returns HTTP 503 or network timeout → skip the poll cycle; log the error; resume on next interval
- No chains found on any poll → continue polling silently; print a heartbeat message every N polls so the user knows the process is alive
- A chain found in a previous poll disappears (permit taken) → do not alert; only alert on new appearances
- User specifies `--interval 0` or a negative value → default to 15 minutes with a warning

**Acceptance Criteria:**
- [ ] `wa-permits --watch` accepts `--park`, `--nights`, `--from`, `--to`, and `--interval` (minutes, default 15)
- [ ] On each poll, results are diffed against the previous poll; new chains are labeled `[NEW]`
- [ ] HTTP 429 responses trigger exponential backoff; the loop does not crash
- [ ] `Ctrl+C` exits cleanly and prints a session summary
- [ ] `--watch` requires `--live`; if omitted, an error is shown explaining that watch mode requires live data

---

### PF-102 · Multi-Park Search
| Epic | Type | Points | Priority |
|------|------|--------|----------|
| Search | Feature | 3 | P0 |

**Product Request:**
> "A lot of users are flexible on which park they go to — they just want permits
> for a given date range. Right now they have to run three separate searches.
> Let them search across all supported parks in one command."
> — Product, 2026-03-08

**Functionality:**
A new `--all-parks` flag runs `find_chains()` against every park in the
supported parks configuration in sequence and merges the results into a single
ranked output. Results are sorted by `min_remaining` descending so the most
available chains appear first. Each result row includes a `park` column so the
user can identify which park it belongs to.

**Modules Affected:**

| Module | Change |
|--------|--------|
| `cli.py` | New `--all-parks` flag; loop over all parks; result merge and sort logic |
| `api.py` | No changes; called once per park in the loop |
| `search.py` | No changes; `find_chains()` called per park |

**External APIs:**

| API | Usage |
|-----|-------|
| Recreation.gov availability endpoint | Called once per supported park when `--all-parks` is active |
| OpenStreetMap Overpass | Called once per supported park to fetch trail graph |

**Database / Local State:** None.

**Kafka Topics:** N/A.

**Happy Path:**
1. User runs `wa-permits --list-chains --all-parks --nights 4 --from 2026-08-01 --to 2026-08-31 --live`
2. CLI iterates over all supported parks, fetching availability and running chain search for each
3. All results are merged and sorted by `min_remaining` descending
4. Output table includes a `Park` column; top results from the most available park appear first

**Edge Cases:**
- `--all-parks` and `--park` used together → exit with error: "use --park or --all-parks, not both"
- One park's API call fails (timeout or 404) → log the failure and continue with remaining parks; partial results are returned with a warning noting which park failed
- No chains found across any park → print "No chains found across all parks for the specified criteria"
- Supported parks list is empty (misconfiguration) → exit with a clear error
- `--all-parks` used without `--live` → runs against mock data for all parks; useful for testing

**Acceptance Criteria:**
- [ ] `wa-permits --list-chains --all-parks` returns chains from all supported parks in a single output
- [ ] Results are sorted by `min_remaining` descending
- [ ] Each result row includes a `Park` column
- [ ] `--all-parks` and `--park` are mutually exclusive; using both returns a clear error message
- [ ] If one park's API call fails, results from other parks are still returned with a warning

---

### PF-103 · JSON Output for All Commands
| Epic | Type | Points | Priority |
|------|------|--------|----------|
| Integrations | Feature | 2 | P1 |

**Product Request:**
> "Power users want to pipe PermitFinder output into their own scripts and
> dashboards. The current Rich table output is not machine-readable. We need
> a `--json` flag on every command."
> — Product, 2026-03-09

**Functionality:**
A `--json` flag is added as a global CLI option. When active, all four commands
(`--list-parks`, `--list-areas`, `--list-availability`, `--list-chains`) write
structured JSON to stdout instead of Rich-formatted tables. Rich output is fully
suppressed. Optionally, `--output <file>` writes the JSON to a file instead of
stdout.

**Modules Affected:**

| Module | Change |
|--------|--------|
| `cli.py` | Add `--json` as a global argument; branch all four output formatters to emit JSON when flag is set; suppress Rich console output |

**External APIs:** No changes — this is a pure output-layer change.

**Database / Local State:** None.

**Kafka Topics:** N/A.

**Happy Path:**
1. User runs `wa-permits --list-chains --park rainier --nights 3 --json`
2. Rich table output is suppressed
3. Valid, pretty-printed JSON is written to stdout
4. User pipes output: `wa-permits --list-chains --park rainier --nights 3 --json | jq '.chains[0]'`

**Edge Cases:**
- `--json` and `--output` used together → JSON is written to the file; nothing is written to stdout except a confirmation of the file path
- Output file path is not writable (permissions error) → print error to stderr; exit with non-zero code
- No results to output → emit valid JSON with an empty array, not an empty string or null
- `--json` used with `--watch` → each poll cycle emits a JSON object to stdout; one object per poll, not a single accumulated array (streaming-friendly)

**Acceptance Criteria:**
- [ ] `--json` flag is supported on all four CLI commands
- [ ] JSON output is valid, pretty-printed, and written to stdout
- [ ] Rich table rendering is fully suppressed when `--json` is active
- [ ] An empty result set emits valid JSON with an empty array, not an empty or null output
- [ ] `--json` and `--output <file>` can be combined to write JSON to a file

---

## Platform Sprint 1 — Engineering
**Sprint Goal:** Establish CI and address code quality gaps that affect
reliability and maintainability of the live data path.
> These are internal engineering tasks. They are not user-facing but are
> required for the team to ship features reliably.

---

### PF-110 · CI Pipeline (GitHub Actions)
| Epic | Type | Points | Priority |
|------|------|--------|----------|
| Platform | Engineering | 2 | P0 |

**Modules Affected:** All (build and test validation only — no runtime changes)

**Acceptance Criteria:**
- [ ] Workflow triggers on `push` and `pull_request` to `main`
- [ ] Pipeline installs dependencies and runs `pytest --cov=permit_engine --cov-fail-under=80`
- [ ] A failing check causes the pipeline to report failure
- [ ] README displays CI status badge

**Files:** `.github/workflows/ci.yml` *(new)*

---

### PF-111 · Add Type Annotations and mypy
| Epic | Type | Points | Priority |
|------|------|--------|----------|
| Platform | Engineering | 3 | P1 |

**Modules Affected:** `api.py`, `cli.py`

**Acceptance Criteria:**
- [ ] `TypedDict` classes defined for Site, Availability, and Trail API response shapes
- [ ] All public functions in `api.py` and `cli.py` have parameter and return type annotations
- [ ] `mypy src/` passes with no errors
- [ ] `mypy` runs as a CI step

---

### PF-112 · Remove Dead Code — `_is_group_site()`
| Epic | Type | Points | Priority |
|------|------|--------|----------|
| Platform | Engineering | 1 | P1 |

**Modules Affected:** `api.py`

**Acceptance Criteria:**
- [ ] `_is_group_site()` is deleted from `api.py`
- [ ] No references to it exist anywhere in the codebase

---

## Backlog — Approved, Not Yet Scheduled

---

### PF-201 · Saved Searches
| Epic | Type | Points |
|------|------|--------|
| Search | Feature | 5 |

**Product Request:**
> "Users run the same search every weekend morning. Let them save a search
> configuration by name and re-run it with a single command rather than
> typing out all the flags every time."

**Functionality:**
A local config file at `~/.wa-permits/searches.json` stores named search
configurations. Users save, list, run, and delete saved searches by name.
On `--run-search`, the stored flags are loaded and executed exactly as if
the user had typed them on the command line.

**Modules Affected:**

| Module | Change |
|--------|--------|
| `cli.py` | New `--save-search`, `--run-search`, `--list-searches`, `--delete-search` commands |
| `config.py` *(new)* | Read/write logic for `~/.wa-permits/searches.json` |

**External APIs:** None for save/list/delete; the configured APIs are called on `--run-search`.

**Database / Local State:** `~/.wa-permits/searches.json` — created on first save if it does not exist.

**Happy Path:**
1. User runs `wa-permits --list-chains --park rainier --nights 3 --save-search rainier-3night`
2. Config file is written with the search parameters under the key `rainier-3night`
3. User later runs `wa-permits --run-search rainier-3night`
4. Stored parameters are loaded and the search executes identically

**Edge Cases:**
- `~/.wa-permits/` directory does not exist → create it on first save
- `--save-search` used with a name that already exists → prompt user to confirm overwrite; `--force` flag skips the prompt
- `--run-search` references a name that does not exist → print available search names and exit with error
- Config file is corrupted or not valid JSON → print a clear error and the file path; do not silently discard the file

**Acceptance Criteria:**
- [ ] `--save-search <name>` saves current flags to `~/.wa-permits/searches.json`
- [ ] `--run-search <name>` re-executes a saved search with its stored parameters
- [ ] `--list-searches` displays all saved searches with their parameters
- [ ] `--delete-search <name>` removes a saved search
- [ ] Saving with an existing name prompts for confirmation unless `--force` is passed

---

### PF-202 · Trip Export — iCal and Plain Text
| Epic | Type | Points |
|------|------|--------|
| Trip Planning | Feature | 3 |

**Product Request:**
> "Once a user finds a permit chain they want, they need to go book it. Right
> now they're copying site names out of a terminal table. Let them export the
> chain as an iCal file or a formatted plain-text itinerary they can print."

**Functionality:**
A new `--export` flag on `--list-chains` takes a format argument (`ical` or
`text`). For `ical`, a `.ics` file is generated with one all-day event per
night of the trip, each titled with the campsite name and park. For `text`, a
formatted plain-text itinerary is written with dates, site names, and permit
details. The export targets the first chain result by default; `--chain-index`
selects a specific result.

**Modules Affected:**

| Module | Change |
|--------|--------|
| `cli.py` | New `--export` and `--chain-index` flags |
| `export.py` *(new)* | iCal generation (`icalendar` library or stdlib); plain-text formatter |

**External APIs:** None — export operates on search results already in memory.

**Database / Local State:** Output file written to the current working directory.

**Happy Path:**
1. User runs `wa-permits --list-chains --park rainier --nights 3 --export ical`
2. First chain result is selected
3. A `.ics` file is generated with 3 events (one per night), each with the campsite name as the title
4. File path is printed: `Exported to rainier-chain-2026-08-01.ics`

**Edge Cases:**
- No chains found → error: "No chains to export; run without --export first to verify results"
- `--chain-index` is out of range → error with the valid index range
- Output file already exists at the target path → overwrite and print a warning, or prompt; document which behavior is chosen
- Chain contains a night with unknown availability (`min_remaining = -1`) → include the night in the export with a note: "availability unconfirmed"
- `icalendar` library not installed → fall back to a manually constructed `.ics` string using stdlib only (iCal format is plain text)

**Acceptance Criteria:**
- [ ] `--export ical` generates a `.ics` file with one event per night, titled with the campsite name
- [ ] `--export text` generates a plain-text itinerary with dates, site names, and permit details
- [ ] `--chain-index <n>` selects a specific chain result; defaults to index 0
- [ ] Exported file path is printed to stdout on success
- [ ] If no chains are found, an error is shown rather than generating an empty file

---

### PF-203 · Enchantments (ZONE) Full Support
| Epic | Type | Points |
|------|------|--------|
| Search | Feature | 5 |

**Product Request:**
> "The Enchantments is the most sought-after permit in Washington and we don't
> support it properly. ZONE permits work differently from ITINERARY permits —
> we need full support including correct availability display and chain search."

**Functionality:**
The Enchantments uses a ZONE-based permit system where availability is
expressed as a per-zone capacity rather than per-campsite. The `api.py` ZONE
endpoint is partially implemented but mock data, graph construction, and CLI
display have not been validated end-to-end. This story completes the
Enchantments integration: mock data is added, the graph builder handles ZONE
sites correctly, and the CLI displays ZONE-type availability in a meaningful way.

**Modules Affected:**

| Module | Change |
|--------|--------|
| `api.py` | Validate and finalize `fetch_availability()` ZONE branch; confirm response shape handling matches live API |
| `mock.py` | Add Enchantments mock data with ZONE-type availability shape |
| `graph.py` | Ensure `build_graph()` handles ZONE site geometry correctly |
| `cli.py` | Display ZONE availability with zone name and capacity; label permit type as `ZONE` in output |

**External APIs:**

| API | Usage |
|-----|-------|
| Recreation.gov ZONE availability endpoint | Different response shape from ITINERARY; availability is per zone, not per campsite |
| OpenStreetMap Overpass | Trail data for Enchantments area |

**Database / Local State:** None.

**Happy Path:**
1. User runs `wa-permits --list-chains --park enchantments --nights 2 --live`
2. `api.py` calls the ZONE availability endpoint; response is parsed correctly
3. `build_graph()` constructs the trail graph using ZONE site coordinates
4. `find_chains()` returns valid permit chains
5. Output table shows zone names, availability counts, and labels permit type as `ZONE`

**Edge Cases:**
- ZONE endpoint returns HTTP 404 before permit season opens → handle gracefully with "permits not yet available for this season" message; do not crash
- ZONE availability response has a different shape than ITINERARY (e.g., no `remaining` field, uses `quota`) → normalize to the internal `ChainLink` availability format in `api.py` so downstream code is unaffected
- Multiple zones in the Enchantments have the same name → deduplicate by zone ID, not name
- ZONE site has no GPS coordinates in the Recreation.gov response → skip that site in graph construction; log a warning

**Acceptance Criteria:**
- [ ] `--park enchantments` returns correct availability data using the ZONE endpoint
- [ ] ZONE availability counts are displayed correctly in `--list-availability` output
- [ ] `--list-chains` constructs and returns valid permit chains for the Enchantments
- [ ] Mock data for the Enchantments is added to `mock.py` mirroring the live ZONE response shape
- [ ] The Enchantments appears in `--list-parks` output with permit type labeled as `ZONE`
- [ ] Pre-season HTTP 404 from the ZONE endpoint is handled with a user-friendly message
