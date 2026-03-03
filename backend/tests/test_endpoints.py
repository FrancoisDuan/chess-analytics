"""Integration tests for the FastAPI endpoints using TestClient.

Chess.com API calls are mocked so tests run fully offline.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import GameSummary, MoveClockEntry

client = TestClient(app)

# A minimal fake game
_FAKE_CLOCKS = [
    MoveClockEntry(ply=1, move_number=1, color="white", clock_after=295.0, time_spent=5.0),
    MoveClockEntry(ply=2, move_number=1, color="black", clock_after=298.0, time_spent=2.0),
    MoveClockEntry(ply=3, move_number=2, color="white", clock_after=290.0, time_spent=5.0),
    MoveClockEntry(ply=4, move_number=2, color="black", clock_after=293.0, time_spent=5.0),
]

_FAKE_GAME = GameSummary(
    url="https://chess.com/game/1",
    time_class="blitz",
    time_control="300",
    white_username="testuser",
    black_username="opponent",
    white_result="win",
    black_result="lose",
    end_time=1700000000,
    rated=True,
    move_clocks=_FAKE_CLOCKS,
)


@pytest.fixture(autouse=True)
def mock_chess_com():
    """Patch chess_com.get_user_games to return fake data for all tests."""
    with patch(
        "app.services.chess_com.get_user_games",
        new_callable=AsyncMock,
        return_value=[_FAKE_GAME],
    ) as m:
        yield m


class TestRoot:
    def test_health(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestGamesEndpoint:
    def test_get_games_ok(self):
        resp = client.get("/api/games/testuser")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["white_username"] == "testuser"

    def test_get_games_with_time_class(self):
        resp = client.get("/api/games/testuser?time_class=blitz")
        assert resp.status_code == 200

    def test_get_games_no_results(self, mock_chess_com):
        mock_chess_com.return_value = []
        resp = client.get("/api/games/nobody")
        assert resp.status_code == 404

    def test_get_games_api_error(self, mock_chess_com):
        mock_chess_com.side_effect = Exception("network error")
        resp = client.get("/api/games/baduser")
        assert resp.status_code == 502


class TestAnalyticsEndpoints:
    def test_move_time_stats(self):
        resp = client.get("/api/analytics/testuser/move-time")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        assert data[0]["move_number"] >= 1
        assert "avg_seconds" in data[0]

    def test_move_time_stats_with_move_limit(self):
        resp = client.get("/api/analytics/testuser/move-time?move_limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert all(d["move_number"] <= 1 for d in data)

    def test_move_time_trend(self):
        resp = client.get("/api/analytics/testuser/move-time-trend")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        assert "date" in data[0]
        assert "avg_seconds" in data[0]

    def test_move_time_trend_specific_moves(self):
        resp = client.get("/api/analytics/testuser/move-time-trend?move_numbers=1,2")
        assert resp.status_code == 200
        data = resp.json()
        assert all(d["move_number"] in [1, 2] for d in data)

    def test_compare_users(self, mock_chess_com):
        opponent_game = _FAKE_GAME.model_copy(
            update={
                "white_username": "opponent",
                "black_username": "testuser",
                "white_result": "lose",
                "black_result": "win",
            }
        )

        async def side_effect(username, **kwargs):
            if username == "testuser":
                return [_FAKE_GAME]
            return [opponent_game]

        mock_chess_com.side_effect = side_effect
        resp = client.get("/api/analytics/compare/testuser/opponent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["username1"] == "testuser"
        assert data["username2"] == "opponent"
        assert "move_time_stats1" in data
        assert "move_time_stats2" in data
