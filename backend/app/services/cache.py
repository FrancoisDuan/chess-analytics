"""In-memory cache for user game data and activity tracking.

The cache stores the most recently fetched games for each user and records
when that user last accessed the application.  A background refresh task
uses ``get_active_usernames`` to discover who deserves a periodic update
and then calls ``set`` to store the fresh data.

Design notes
------------
* Cache keys are ``"<platform>:<username_lower>"`` so look-ups are
  case-insensitive and platform-aware.  The default platform is
  ``"chessdotcom"`` for backward-compatibility with callers that do not
  pass an explicit platform.
* The module exposes a single ``game_cache`` instance shared by the whole
  application.  Unit tests should call ``game_cache.clear()`` in a fixture
  to prevent state from leaking between tests.
* This is an asyncio-safe (single-threaded event-loop) data structure.
  It is *not* safe for use across OS threads without an explicit lock.
"""
from __future__ import annotations

import time
from typing import Optional

from app.schemas import GameSummary

_DEFAULT_PLATFORM = "chessdotcom"


def _make_key(username: str, platform: str) -> str:
    return f"{platform.lower()}:{username.lower()}"


class _GameCache:
    """In-memory store for per-user game lists and last-seen timestamps."""

    def __init__(self) -> None:
        self._games: dict[str, list[GameSummary]] = {}
        self._last_refreshed: dict[str, float] = {}  # unix ts of last fetch
        self._last_seen: dict[str, float] = {}  # unix ts of last API request

    # ------------------------------------------------------------------
    # Game data
    # ------------------------------------------------------------------

    def get(self, username: str, platform: str = _DEFAULT_PLATFORM) -> Optional[list[GameSummary]]:
        """Return the cached game list for *username*, or ``None`` if absent."""
        return self._games.get(_make_key(username, platform))

    def set(self, username: str, games: list[GameSummary], platform: str = _DEFAULT_PLATFORM) -> None:
        """Store *games* for *username* and stamp the refresh time."""
        key = _make_key(username, platform)
        self._games[key] = games
        self._last_refreshed[key] = time.time()

    # ------------------------------------------------------------------
    # Activity tracking
    # ------------------------------------------------------------------

    def touch(self, username: str, platform: str = _DEFAULT_PLATFORM) -> None:
        """Record that *username* made an API request right now."""
        self._last_seen[_make_key(username, platform)] = time.time()

    def get_active_usernames(self, within_days: int) -> list[str]:
        """Return ``"<platform>:<username>"`` keys active within *within_days* days."""
        cutoff = time.time() - within_days * 86400
        return [key for key, ts in self._last_seen.items() if ts >= cutoff]

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Remove all cached data.  Primarily useful in tests."""
        self._games.clear()
        self._last_refreshed.clear()
        self._last_seen.clear()


# Module-level singleton shared by the entire application.
game_cache = _GameCache()
