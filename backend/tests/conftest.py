"""Shared pytest fixtures for the backend test suite."""
from __future__ import annotations

import pytest

from app.services.cache import game_cache


@pytest.fixture(autouse=True)
def clear_game_cache():
    """Reset the in-memory game cache before (and after) every test.

    This prevents state from leaking between tests when the module-level
    ``game_cache`` singleton is populated during one test and then
    accidentally re-used in the next.
    """
    game_cache.clear()
    yield
    game_cache.clear()
