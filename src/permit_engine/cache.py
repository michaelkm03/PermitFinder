"""
SQLite-backed disk cache for stable API responses.

Used to avoid re-fetching data that rarely changes (OSM trail geometry,
rec.gov site lists, permit metadata). Each entry stores its own TTL so
different data types can expire at different rates without code changes.

Cache location
--------------
  ~/.cache/permit-finder/cache.db   (default)
  Override via PERMIT_FINDER_CACHE_DIR environment variable.

Schema
------
  table: cache
    key        TEXT PRIMARY KEY   — namespaced cache key (e.g. "trails:olympic:a3f9")
    data       TEXT               — JSON-encoded payload
    fetched_at REAL               — Unix timestamp of when data was stored
    ttl_days   REAL               — seconds / 86400; entry is stale after this many days

Recommended TTLs
----------------
  trails:<park>:<bbox_hash>   30 days   — OSM trail geometry (rarely changes)
  sites:<facility_id>          7 days   — rec.gov site/division list
  permit_meta:<facility_id>    1 day    — permit season metadata

Usage
-----
  from permit_engine.cache import Cache

  cache = Cache()                      # uses default location
  cache = Cache("/custom/path/cache.db")

  # Store
  cache.set("trails:olympic:abc123", trail_list, ttl_days=30)

  # Retrieve — returns None if missing or stale
  data = cache.get("trails:olympic:abc123")

  # Invalidate one entry
  cache.invalidate("trails:olympic:abc123")

  # Clear all entries (or by prefix)
  cache.clear()
  cache.clear(prefix="trails:")
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "permit-finder"
_DB_FILENAME = "cache.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS cache (
    key        TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    ttl_days   REAL NOT NULL
);
"""


class Cache:
    """
    Simple SQLite key-value cache with per-entry TTL.

    Thread-safety: SQLite handles concurrent reads safely. Concurrent writes
    from multiple processes are serialised by SQLite's file-level locking —
    fine for CLI usage.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            cache_dir = Path(os.environ.get("PERMIT_FINDER_CACHE_DIR", _DEFAULT_CACHE_DIR))
            self._db_path = cache_dir / _DB_FILENAME
        else:
            self._db_path = Path(db_path)
            cache_dir = self._db_path.parent

        cache_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()
        log.debug("cache  db=%s", self._db_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str) -> Any | None:
        """
        Return the cached value for key, or None if missing or stale.

        Stale entries are deleted on access (lazy eviction).
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data, fetched_at, ttl_days FROM cache WHERE key = ?", (key,)
            ).fetchone()

        if row is None:
            log.debug("cache  MISS  %s", key)
            return None

        data_json, fetched_at, ttl_days = row
        age_days = (time.time() - fetched_at) / 86400
        if age_days > ttl_days:
            log.debug("cache  STALE  %s  (age=%.1fd  ttl=%.1fd)", key, age_days, ttl_days)
            self.invalidate(key)
            return None

        log.debug("cache  HIT  %s  (age=%.1fd  ttl=%.1fd)", key, age_days, ttl_days)
        return json.loads(data_json)

    def set(self, key: str, value: Any, ttl_days: float) -> None:
        """Store value under key with the given TTL in days."""
        data_json = json.dumps(value, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cache (key, data, fetched_at, ttl_days)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    data       = excluded.data,
                    fetched_at = excluded.fetched_at,
                    ttl_days   = excluded.ttl_days
                """,
                (key, data_json, time.time(), ttl_days),
            )
        log.debug("cache  SET  %s  ttl=%.1fd", key, ttl_days)

    def invalidate(self, key: str) -> None:
        """Delete a single cache entry."""
        with self._connect() as conn:
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))
        log.debug("cache  INVALIDATE  %s", key)

    def clear(self, prefix: str | None = None) -> int:
        """
        Delete all entries, or only those whose key starts with prefix.
        Returns the number of rows deleted.
        """
        with self._connect() as conn:
            if prefix:
                cur = conn.execute(
                    "DELETE FROM cache WHERE key LIKE ?", (prefix.replace("%", "%%") + "%",)
                )
            else:
                cur = conn.execute("DELETE FROM cache")
            deleted = cur.rowcount
        log.debug("cache  CLEAR  prefix=%r  deleted=%d", prefix, deleted)
        return deleted

    def stats(self) -> dict[str, int]:
        """Return entry counts grouped by key prefix (first segment before ':')."""
        with self._connect() as conn:
            rows = conn.execute("SELECT key FROM cache").fetchall()
        counts: dict[str, int] = {}
        for (key,) in rows:
            prefix = key.split(":")[0]
            counts[prefix] = counts.get(prefix, 0) + 1
        return counts

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")  # safe concurrent reads
        return conn


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def make_key(*parts: str) -> str:
    """
    Build a namespaced cache key from parts.

    Short parts are joined with ':'. If the combined key would exceed
    200 chars (e.g. a large bbox string), the last part is hashed.

      make_key("trails", "olympic", "47.2,-124.8,48.2,-122.9")
      → "trails:olympic:c3f9a1b2"
    """
    raw = ":".join(str(p) for p in parts)
    if len(raw) <= 200:
        return raw
    # Hash the last part to keep the key short
    prefix = ":".join(str(p) for p in parts[:-1])
    suffix = hashlib.sha256(str(parts[-1]).encode()).hexdigest()[:8]
    return f"{prefix}:{suffix}"


# Module-level default instance — shared across the process.
_default_cache: Cache | None = None


def get_default_cache() -> Cache:
    """Return (and lazily create) the module-level default Cache instance."""
    global _default_cache
    if _default_cache is None:
        _default_cache = Cache()
    return _default_cache
