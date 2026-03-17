# PermitFinder — SE Contribution Plan

This document tracks planned contributions to demonstrate software engineering
ability across testing, type safety, CI/CD, and code quality.

---

## Required (Must-Do — Core SE Signal)

### 1. Add GitHub Actions CI Pipeline
**File:** `.github/workflows/ci.yml` *(create)*

No automated test run exists on any push or PR. This turns the repo from
"code that exists" into "maintained software" in any reviewer's eyes.

**Tasks:**
- [ ] Create workflow triggered on `push` and `pull_request` to `main`
- [ ] Step: checkout code
- [ ] Step: set up Python 3.10
- [ ] Step: `pip install -e ".[dev]"`
- [ ] Step: `pytest --cov=permit_engine --cov-fail-under=80`
- [ ] Step: publish coverage report as workflow artifact
- [ ] (Optional) Add a coverage badge to README

```yaml
# .github/workflows/ci.yml skeleton
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      - run: pip install -e ".[dev]"
      - run: pytest --cov=permit_engine --cov-fail-under=80
```

---

### 2. Add Type Annotations to `api.py` and `cli.py`
**Files:**
- `src/permit_engine/api.py`
- `src/permit_engine/cli.py`

These are the two largest files with the most complex return shapes and have
zero type hints. Standard Python SE practice in 2025 is to type-annotate all
public function signatures and use `TypedDict` for complex dict return shapes.

**Tasks:**
- [ ] Define `TypedDict` classes for the Recreation.gov and OSM API response
  shapes (Site dict, Availability dict, Trail dict)
- [ ] Add return type annotations to all functions in `api.py`
- [ ] Add parameter and return type annotations to all functions in `cli.py`
- [ ] Add `mypy` as a dev dependency in `pyproject.toml`
- [ ] Run `mypy src/` and fix all reported errors
- [ ] Add `mypy` step to the CI pipeline (after #1)

---

### 3. Remove Dead Code — `_is_group_site()`
**File:** `src/permit_engine/api.py`

`_is_group_site()` is defined but never called anywhere in the codebase.
Dead code in a portfolio project signals inattention to detail.

**Tasks:**
- [ ] Search all files to confirm it is truly unused: `grep -r "_is_group_site" src/`
- [ ] Delete the function
- [ ] Run the full test suite to confirm nothing broke

---

### 4. Write Tests for the ZONE Code Path (Enchantments)
**Files:**
- `src/permit_engine/mock.py` — add ZONE-type mock data
- `tests/test_search.py` or `tests/test_mock.py` — add ZONE tests

The Enchantments / ZONE availability endpoint is fully implemented in `api.py`
but has zero test coverage. The mock data only covers North Cascades (ITINERARY
type). Adding ZONE coverage closes a real correctness gap.

**Tasks:**
- [ ] Extend `mock.py` to include a ZONE-type park with synthetic site and
  availability data that mirrors the live API response shape
- [ ] Write tests in `tests/test_mock.py` asserting ZONE mock data shape is valid
- [ ] Write a test in `tests/test_search.py` that runs `find_chains()` against
  ZONE-type data and asserts correct results
- [ ] Confirm `filter_by_availability()` works correctly with ZONE availability counts

---

## Nice to Have (Differentiators)

### 5. Add Coverage Badge to README
**Files:** `README.md`, `pyproject.toml`

A coverage badge is a visible, immediate quality signal to any engineer or
recruiter looking at the repo.

**Tasks:**
- [ ] Add coverage configuration to `pyproject.toml`:
  ```toml
  [tool.coverage.run]
  source = ["permit_engine"]
  [tool.coverage.report]
  fail_under = 80
  ```
- [ ] Use `coverage-badge` or GitHub Actions + shields.io to generate badge
- [ ] Embed badge in README next to existing build status badge (once CI is up)

---

### 6. Enable `mypy` Strict Mode
**Files:** `pyproject.toml`, all source files

After completing the basic type annotations in Required #2, push further with
`--strict` mode. This catches missing return types, untyped function parameters,
and implicit `Any` usage.

**Tasks:**
- [ ] Add `mypy` strict config to `pyproject.toml`:
  ```toml
  [tool.mypy]
  strict = true
  ```
- [ ] Run `mypy --strict src/` and fix all reported errors
- [ ] Update CI pipeline to run mypy in strict mode

---

### 7. Add `requirements.txt`
**File:** `requirements.txt` *(create)*

Many engineers and employers default to looking for `requirements.txt`. It can
be auto-generated from `pyproject.toml` using `pip-tools`.

**Tasks:**
- [ ] Install `pip-tools`: `pip install pip-tools`
- [ ] Run `pip-compile pyproject.toml -o requirements.txt`
- [ ] Commit `requirements.txt`
- [ ] Add a note to README that `pyproject.toml` is the source of truth and
  `requirements.txt` is auto-generated

---

### 8. Add Structured Logging
**File:** `src/permit_engine/api.py`

The current `_vlog()` / `_verbose` flag provides debug output but is not
structured, has no log levels, and is not configurable for CI or production use.
Replace it with Python's standard `logging` module.

**Tasks:**
- [ ] Replace `_vlog()` calls with `logging.getLogger(__name__).debug()`
- [ ] Replace any warning-level output with `logger.warning()`
- [ ] Remove the `_verbose` module-level flag
- [ ] Configure log level via CLI `--verbose` flag using `logging.basicConfig`
- [ ] Add logging config to `cli.py` entry point

---

## Summary Checklist

| # | Task | Type | Status |
|---|------|------|--------|
| 1 | Add GitHub Actions CI pipeline | Required | [ ] |
| 2 | Add type annotations + mypy to `api.py` and `cli.py` | Required | [ ] |
| 3 | Remove dead `_is_group_site()` function | Required | [ ] |
| 4 | Write ZONE code path tests + mock data | Required | [ ] |
| 5 | Add coverage badge to README | Nice to Have | [ ] |
| 6 | Enable mypy strict mode | Nice to Have | [ ] |
| 7 | Add `requirements.txt` | Nice to Have | [ ] |
| 8 | Add structured logging | Nice to Have | [ ] |
