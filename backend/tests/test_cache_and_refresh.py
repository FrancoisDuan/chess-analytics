"""Tests for the in-memory game cache, activity tracking, and background refresh.

All tests are fully offline – no chess.com API calls are made.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas import GameSummary, MoveClockEntry
from app.services.cache import _GameCache, game_cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_game(white: str = "alice", black: str = "bob") -> GameSummary:
    return GameSummary(
        url="https://chess.com/game/1",
        time_class="blitz",
        time_control="300",
        white_username=white,
        black_username=black,
        white_result="win",
        black_result="lose",
        end_time=1700000000,
        rated=True,
        move_clocks=[
            MoveClockEntry(ply=1, move_number=1, color="white", clock_after=295.0, time_spent=5.0),
        ],
    )


# ---------------------------------------------------------------------------
# _GameCache – game storage
# ---------------------------------------------------------------------------

class TestGameCacheStorage:
    def setup_method(self):
        self.cache = _GameCache()

    def test_get_returns_none_when_empty(self):
        assert self.cache.get("alice") is None

    def test_set_and_get_round_trip(self):
        games = [_make_game()]
        self.cache.set("alice", games)
        assert self.cache.get("alice") == games

    def test_get_is_case_insensitive(self):
        games = [_make_game()]
        self.cache.set("Alice", games)
        assert self.cache.get("ALICE") == games

    def test_set_overwrites_existing_entry(self):
        self.cache.set("alice", [_make_game()])
        fresh = [_make_game(), _make_game()]
        self.cache.set("alice", fresh)
        assert self.cache.get("alice") == fresh

    def test_clear_removes_all_data(self):
        self.cache.set("alice", [_make_game()])
        self.cache.touch("alice")
        self.cache.clear()
        assert self.cache.get("alice") is None
        assert self.cache.get_active_usernames(within_days=1) == []


# ---------------------------------------------------------------------------
# _GameCache – activity tracking
# ---------------------------------------------------------------------------

class TestGameCacheActivity:
    def setup_method(self):
        self.cache = _GameCache()

    def test_touch_marks_user_active(self):
        self.cache.touch("alice")
        assert "chessdotcom:alice" in self.cache.get_active_usernames(within_days=1)

    def test_touch_is_case_insensitive(self):
        self.cache.touch("Alice")
        assert "chessdotcom:alice" in self.cache.get_active_usernames(within_days=1)

    def test_no_touch_returns_empty(self):
        assert self.cache.get_active_usernames(within_days=7) == []

    def test_stale_user_excluded(self):
        # Manually back-date the last_seen timestamp to 10 days ago.
        self.cache.touch("alice")
        self.cache._last_seen["chessdotcom:alice"] = time.time() - 10 * 86400
        assert self.cache.get_active_usernames(within_days=7) == []

    def test_recent_user_included(self):
        self.cache.touch("bob")
        self.cache._last_seen["chessdotcom:bob"] = time.time() - 3 * 86400  # 3 days ago
        assert "chessdotcom:bob" in self.cache.get_active_usernames(within_days=7)

    def test_multiple_users(self):
        self.cache.touch("alice")
        self.cache.touch("bob")
        active = self.cache.get_active_usernames(within_days=1)
        assert set(active) == {"chessdotcom:alice", "chessdotcom:bob"}


# ---------------------------------------------------------------------------
# Cache integration with endpoint helpers (via game_cache singleton)
# ---------------------------------------------------------------------------

class TestGameCacheSingleton:
    """Verify that the module-level singleton is cleared by the conftest fixture."""

    def test_cache_is_empty_at_start(self):
        assert game_cache.get("anyuser") is None

    def test_set_and_get_on_singleton(self):
        games = [_make_game()]
        game_cache.set("testuser", games)
        assert game_cache.get("testuser") == games


# ---------------------------------------------------------------------------
# Background refresh logic
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_background_refresh_updates_cache():
    """_background_refresh should re-fetch games for recently-active users."""
    from app.main import _background_refresh

    fresh_game = _make_game(white="refreshed")
    game_cache.touch("alice")

    with (
        patch("app.main.config.REFRESH_INTERVAL_MINUTES", 0),
        patch("app.main.config.ACTIVE_USER_DAYS", 7),
        patch("app.main.config.CACHE_MAX_GAMES", 500),
        patch(
            "app.main.chess_com.get_user_games",
            new_callable=AsyncMock,
            return_value=[fresh_game],
        ),
    ):
        task = asyncio.create_task(_background_refresh())
        # Let the event loop run briefly so one refresh cycle executes.
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    cached = game_cache.get("alice")
    assert cached is not None
    assert cached[0].white_username == "refreshed"


@pytest.mark.asyncio
async def test_background_refresh_skips_inactive_users():
    """Users who haven't accessed the app recently should not be refreshed."""
    from app.main import _background_refresh

    mock_fetch = AsyncMock(return_value=[_make_game()])

    with (
        patch("app.main.config.REFRESH_INTERVAL_MINUTES", 0),
        patch("app.main.config.ACTIVE_USER_DAYS", 1),
        patch("app.main.config.CACHE_MAX_GAMES", 500),
        patch("app.main.chess_com.get_user_games", mock_fetch),
    ):
        # "stale" was last seen 10 days ago – outside the 1-day window.
        game_cache.touch("stale")
        game_cache._last_seen["chessdotcom:stale"] = time.time() - 10 * 86400

        task = asyncio.create_task(_background_refresh())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    mock_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_background_refresh_tolerates_chess_com_errors():
    """A chess.com error for one user must not abort the whole refresh cycle."""
    from app.main import _background_refresh

    game_cache.touch("alice")
    game_cache.touch("bob")

    call_log: list[str] = []

    async def _side_effect(username: str, **_kwargs):
        call_log.append(username)
        if username == "alice":
            raise RuntimeError("chess.com is down")
        return [_make_game(white=username)]

    with (
        patch("app.main.config.REFRESH_INTERVAL_MINUTES", 0),
        patch("app.main.config.ACTIVE_USER_DAYS", 7),
        patch("app.main.config.CACHE_MAX_GAMES", 500),
        patch("app.main.chess_com.get_user_games", side_effect=_side_effect),
    ):
        task = asyncio.create_task(_background_refresh())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Both users were attempted despite alice raising an error.
    assert set(call_log) == {"alice", "bob"}
    # Bob's games were still cached.
    assert game_cache.get("bob") is not None
