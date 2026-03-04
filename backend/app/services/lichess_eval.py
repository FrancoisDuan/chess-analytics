"""Lichess cloud evaluation client.

Retrieves centipawn evaluations for FEN positions from the Lichess cloud-eval
API (https://lichess.org/api/cloud-eval).  Results are cached in-process with
a configurable TTL to avoid redundant API calls across requests.

All centipawn values are from White's perspective (positive = White is better).
Mate scores are mapped to ±10 000 centipawns.
"""
from __future__ import annotations

import time
from typing import Optional

import httpx

_CLOUD_EVAL_URL = "https://lichess.org/api/cloud-eval"

# How long (seconds) a cached evaluation is considered fresh.
EVAL_CACHE_TTL: int = 3600  # 1 hour

# In-process cache: fen → (cached_at_ts, cp_value_or_None)
_eval_cache: dict[str, tuple[float, Optional[float]]] = {}


def _cache_get(fen: str) -> tuple[bool, Optional[float]]:
    """Return (hit, value) for *fen*.  hit=False means cache miss or expired."""
    entry = _eval_cache.get(fen)
    if entry is None:
        return False, None
    ts, val = entry
    if time.time() - ts > EVAL_CACHE_TTL:
        return False, None
    return True, val


def _cache_set(fen: str, cp: Optional[float]) -> None:
    """Store a centipawn value (or None if unavailable) for *fen*."""
    _eval_cache[fen] = (time.time(), cp)


def clear_eval_cache() -> None:
    """Remove all cached evaluations.  Useful in tests."""
    _eval_cache.clear()


async def get_eval(fen: str, client: httpx.AsyncClient) -> Optional[float]:
    """Return centipawn evaluation for *fen*, or None if unavailable.

    The Lichess cloud-eval API is queried at most once per position per TTL
    window.  Subsequent calls within the TTL window are served from cache.

    Parameters
    ----------
    fen:
        FEN string of the position to evaluate.
    client:
        An active :class:`httpx.AsyncClient` to reuse across calls.

    Returns
    -------
    float | None
        Centipawns from White's perspective, or None when the position is not
        in the Lichess cloud database or the request fails.
    """
    hit, cached_val = _cache_get(fen)
    if hit:
        return cached_val

    cp: Optional[float] = None
    try:
        resp = await client.get(
            _CLOUD_EVAL_URL,
            params={"fen": fen, "multiPv": "1"},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            pvs = data.get("pvs", [])
            if pvs:
                pv = pvs[0]
                if "cp" in pv:
                    cp = float(pv["cp"])
                elif "mate" in pv:
                    # Convert mate-in-N to a large centipawn value.
                    cp = 10_000.0 if pv["mate"] > 0 else -10_000.0
    except Exception:  # noqa: BLE001
        pass

    _cache_set(fen, cp)
    return cp
