# PermitFinder — Product & Engineering Backlog
**Version:** 1.0
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
**Epic:** Notifications
**Type:** Feature
**Points:** 5
**Priority:** P0

**Product Request:**
> "The most common feedback we get is 'I found a route I want but there were no
> permits available.' Users need to set an alert and get notified when a slot
> opens up — checking manually every day is not a viable workflow."
> — Product, 2026-03-10

**Background:**
Users should be able to register an alert for a specific park, date range, and
trip duration. The engine periodically polls Recreation.gov availability for
matching chains and triggers a notification when one becomes available. Initial
delivery is CLI output or a log entry; a real notification channel (email/SMS)
is out of scope for this story.

**Acceptance Criteria:**
- [ ] `wa-permits --watch` accepts `--park`, `--nights`, `--from`, `--to` and polls on a configurable interval (default 15 min)
- [ ] When a matching chain is found that was not present in the previous poll, the result is printed and marked as new
- [ ] The watch loop handles Recreation.gov rate limit responses (HTTP 429) gracefully with exponential backoff
- [ ] `--watch` exits cleanly on `Ctrl+C` with a summary of how many alerts fired

**Files:**
`src/permit_engine/cli.py`, `src/permit_engine/search.py`

---

### PF-102 · Multi-Park Search
**Epic:** Search
**Type:** Feature
**Points:** 3
**Priority:** P0

**Product Request:**
> "A lot of users are flexible on which park they go to — they just want permits
> for a given date range. Right now they have to run three separate searches.
> Let them search across all supported parks in one command."
> — Product, 2026-03-08

**Background:**
`--list-chains` currently requires a single `--park` argument. This story adds
a `--all-parks` flag that runs the chain search across every park in the
supported parks config and merges the results into a single ranked output.

**Acceptance Criteria:**
- [ ] `wa-permits --list-chains --all-parks --nights 4` returns chains from all supported parks
- [ ] Results are sorted by `min_remaining` availability descending so the most bookable chains appear first
- [ ] Each result row includes a `park` column so the user knows which park the chain belongs to
- [ ] `--all-parks` and `--park` are mutually exclusive; using both returns a clear error

**Files:**
`src/permit_engine/cli.py`, `src/permit_engine/api.py`

---

### PF-103 · JSON Output for All Commands
**Epic:** Integrations
**Type:** Feature
**Points:** 2
**Priority:** P1

**Product Request:**
> "Power users want to pipe PermitFinder output into their own scripts and
> dashboards. The current Rich table output is not machine-readable. We need
> a `--json` flag on every command."
> — Product, 2026-03-09

**Background:**
`--list-chains` already supports JSON output via `chains.json`. This story
standardises `--json` as a flag across all CLI commands — `--list-parks`,
`--list-areas`, and `--list-availability` — returning structured output
instead of Rich-formatted tables.

**Acceptance Criteria:**
- [ ] `--json` flag is supported on all four CLI commands
- [ ] JSON output is valid, pretty-printed, and written to stdout
- [ ] Rich table rendering is fully suppressed when `--json` is active
- [ ] `--json` and `--output <file>` can be combined to write JSON to a file

**Files:**
`src/permit_engine/cli.py`

---

## Platform Sprint 1 — Engineering
**Sprint Goal:** Establish CI and address the two code quality gaps that affect
reliability of the live data path.
> These are internal engineering tasks. They are not user-facing but are
> required for the team to ship features reliably.

---

### PF-110 · CI Pipeline (GitHub Actions)
**Epic:** Platform
**Type:** Engineering
**Points:** 2
**Priority:** P0

**Acceptance Criteria:**
- [ ] Workflow triggers on `push` and `pull_request` to `main`
- [ ] Pipeline installs dependencies and runs `pytest --cov=permit_engine --cov-fail-under=80`
- [ ] A failing check causes the pipeline to report failure
- [ ] README displays CI status badge

**Files:** `.github/workflows/ci.yml` *(new)*

---

### PF-111 · Add Type Annotations and mypy
**Epic:** Platform
**Type:** Engineering
**Points:** 3
**Priority:** P1

**Background:**
`api.py` and `cli.py` have zero type annotations despite having complex return
shapes. `TypedDict` definitions are needed for the Recreation.gov and OSM
response structures. `mypy` is added as a dev dependency and run in CI.

**Acceptance Criteria:**
- [ ] `TypedDict` classes defined for Site, Availability, and Trail response shapes
- [ ] All public functions in `api.py` and `cli.py` have parameter and return type annotations
- [ ] `mypy src/` passes with no errors
- [ ] `mypy` runs as a CI step

---

### PF-112 · Remove Dead Code — `_is_group_site()`
**Epic:** Platform
**Type:** Engineering
**Points:** 1
**Priority:** P1

**Acceptance Criteria:**
- [ ] `_is_group_site()` is deleted from `api.py`
- [ ] No references to it exist anywhere in the codebase

**Files:** `src/permit_engine/api.py`

---

## Backlog — Approved, Not Yet Scheduled

---

### PF-201 · Saved Searches
**Epic:** Search
**Type:** Feature
**Points:** 5

**Product Request:**
> "Users run the same search every weekend morning. Let them save a search
> configuration by name and re-run it with a single command rather than
> typing out all the flags every time."

**Acceptance Criteria:**
- [ ] `wa-permits --save-search <name>` saves the current flag combination to a local config file (`~/.wa-permits/searches.json`)
- [ ] `wa-permits --run-search <name>` re-executes a saved search with its stored parameters
- [ ] `wa-permits --list-searches` displays all saved searches with their parameters
- [ ] `wa-permits --delete-search <name>` removes a saved search
- [ ] Saving a search with an existing name prompts the user to confirm overwrite

---

### PF-202 · Trip Export — iCal and Plain Text
**Epic:** Trip Planning
**Type:** Feature
**Points:** 3

**Product Request:**
> "Once a user finds a permit chain they want, they need to go book it. Right
> now they're copying site names out of a terminal table. Let them export the
> chain as an iCal file or a formatted plain-text itinerary they can print."

**Acceptance Criteria:**
- [ ] `wa-permits --list-chains --export ical` generates a `.ics` file with one event per night, titled with the campsite name and location
- [ ] `wa-permits --list-chains --export text` generates a formatted plain-text itinerary with dates, site names, and permit details
- [ ] Export targets the first result by default; `--chain-index <n>` selects a specific result
- [ ] The exported file is written to the current directory and the path is printed to stdout

---

### PF-203 · Enchantments (ZONE) Full Support
**Epic:** Search
**Type:** Feature
**Points:** 5

**Product Request:**
> "The Enchantments is the most sought-after permit in Washington and we don't
> support it properly. ZONE permits work differently from ITINERARY permits —
> we need full support including correct availability display and chain search."

**Background:**
The ZONE availability endpoint is partially implemented in `api.py` but the
mock data, graph construction, and CLI display have not been validated against
the ZONE response shape. This story completes the Enchantments integration end
to end.

**Acceptance Criteria:**
- [ ] `--park enchantments` returns correct availability data from the ZONE endpoint
- [ ] Zone-type availability counts are displayed correctly in `--list-availability` output
- [ ] `--list-chains` correctly constructs and returns permit chains for ZONE-type parks
- [ ] Mock data for the Enchantments is added to `mock.py` mirroring the live ZONE response shape
- [ ] The Enchantments appears in `--list-parks` output with its correct permit type labeled as `ZONE`
