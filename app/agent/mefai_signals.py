"""MEFAI live-signal read tools (read-only, no chain, no signing).

This module is the agent's bridge to the MEFAI trading terminal's live signal
feed. It is exposed to the seller agent's LLM as read-only ADK FunctionTools
(see ``tools.py``) so that, once a buyer's job is verified funded on-chain, the
agent can pull MEFAI's current signals and turn them into the deliverable.

Design goals:
  * READ-ONLY. No wallet spend, no signing, no chain write. These are plain HTTP
    GETs against the MEFAI terminal running on the SAME host (localhost), so no
    Cloudflare / public rate limit is in the path.
  * NEVER-EMPTY. Every call returns a well-formed dict even on upstream failure ·
    a short in-process last-good cache serves the previous good snapshot so the
    agent never produces an empty deliverable. This mirrors MEFAI's own
    last-good serving philosophy.
  * SELF-CONTAINED. Configuration is env-driven with safe localhost defaults, so
    the open-source repo carries no secrets and no host-specific paths.

Signal source (in priority order):
  1. MEFAI_SIGNAL_DB · path to MEFAI's signals SQLite file. When set and present,
     this is the primary source: the agent reads the latest signal per
     symbol+timeframe DIRECTLY from the local DB, opened READ-ONLY. This is how a
     self-hosted agent co-located with the MEFAI terminal reads signals · no HTTP,
     no tier gate, never empty. Table: signals(id, symbol, timeframe, signal,
     timestamp, price).
  2. MEFAI_SIGNALS_URL · HTTP fallback (e.g. http://127.0.0.1:8000/signals), used
     when no DB path is configured / reachable. If the endpoint is tier-gated,
     MEFAI_SIGNALS_WALLET (a PRO/PRIME wallet) selects the full set.

Env:
  MEFAI_SIGNAL_DB       path to MEFAI signals sqlite (empty => use HTTP)
  MEFAI_SIGNALS_URL     signals endpoint (default http://127.0.0.1:8000/signals)
  MEFAI_SIGNALS_WALLET  optional PRO/PRIME wallet for the HTTP path
  MEFAI_HTTP_TIMEOUT    per-request timeout seconds (default 6)
"""
from __future__ import annotations

import os
import sqlite3
import time
from typing import Any

import requests

_SIGNAL_DB = os.environ.get("MEFAI_SIGNAL_DB", "").strip()
_SIGNALS_URL = os.environ.get("MEFAI_SIGNALS_URL", "http://127.0.0.1:8000/signals")
_WALLET = os.environ.get("MEFAI_SIGNALS_WALLET", "").strip()
_TIMEOUT = float(os.environ.get("MEFAI_HTTP_TIMEOUT", "6"))

# Short-lived last-good cache: {cache_key: (fetched_at_monotonic, payload)}.
# The signal feed updates every couple of seconds upstream; a small TTL keeps the
# agent responsive without hammering the terminal, and the stored payload doubles
# as the never-empty fallback when a fetch fails.
_CACHE_TTL = 5.0
_cache: dict[str, tuple[float, Any]] = {}


def _now() -> float:
    return time.monotonic()


def _get(url: str, cache_key: str) -> dict[str, Any]:
    """GET ``url`` with a fresh<->last-good cache. Always returns a dict.

    On success: cache and return the parsed JSON. On any failure: return the
    most recent good payload for this key if we have one (marked stale), else a
    structured empty result · never an exception, never ``None``.
    """
    cached = _cache.get(cache_key)
    if cached is not None and (_now() - cached[0]) < _CACHE_TTL:
        return cached[1]

    try:
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            _cache[cache_key] = (_now(), data)
            return data
    except Exception:  # noqa: BLE001 · a read tool must never raise into the LLM
        pass

    if cached is not None:
        stale = dict(cached[1])
        stale["stale"] = True
        return stale
    return {"signals": [], "gated": True, "source": "mefai", "error": "unavailable"}


def _read_db_latest(limit: int = 200) -> list[dict[str, Any]]:
    """Latest signal per symbol+timeframe, read READ-ONLY from the local MEFAI
    signals SQLite. Returns [] if no DB is configured/reachable · never raises."""
    if not _SIGNAL_DB or not os.path.exists(_SIGNAL_DB):
        return []
    try:
        conn = sqlite3.connect(f"file:{_SIGNAL_DB}?mode=ro", uri=True, timeout=2.0)
    except Exception:  # noqa: BLE001
        return []
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT symbol, timeframe, signal, timestamp, price FROM signals "
            "WHERE id IN (SELECT MAX(id) FROM signals GROUP BY symbol, timeframe) "
            "ORDER BY timestamp DESC LIMIT ?",
            (int(max(1, min(limit, 500))),),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:  # noqa: BLE001 · a read tool must never raise into the LLM
        return []
    finally:
        conn.close()


def _all_signals(limit: int = 200) -> tuple[list[dict[str, Any]], bool]:
    """Return (raw signal rows, stale) from the highest-priority available source.

    DB first (self-host, tier-free, always populated), then HTTP, then last-good
    cache. Each row: {symbol, timeframe, signal, timestamp, price}. ``stale`` is
    True only when both live sources failed and a cached snapshot was served.
    """
    cache_key = "all"
    cached = _cache.get(cache_key)
    if cached is not None and (_now() - cached[0]) < _CACHE_TTL:
        return cached[1], False

    rows = _read_db_latest(limit)
    if rows:
        _cache[cache_key] = (_now(), rows)
        return rows, False

    raw = _get(_SIGNALS_URL + ("?" + _urlencode(_params()) if _params() else ""), "http")
    items = raw.get("signals") if isinstance(raw, dict) else None
    if isinstance(items, list) and items:
        _cache[cache_key] = (_now(), items)
        return items, bool(raw.get("stale"))

    if cached is not None:
        return cached[1], True
    return [], False


def _params() -> dict[str, str]:
    return {"wallet": _WALLET} if _WALLET else {}


def _side_word(signal: str) -> str:
    s = (signal or "").lower()
    if s in ("buy", "long"):
        return "LONG"
    if s in ("sell", "short"):
        return "SHORT"
    return signal.upper() if signal else "FLAT"


def mefai_latest_signals(timeframe: str = "", limit: int = 40) -> dict[str, Any]:
    """Return MEFAI's current live trading signals (latest per symbol+timeframe).

    Args:
        timeframe: optional filter, e.g. "1m", "5m", "15m", "1h", "4h", "1d".
            Empty returns every timeframe MEFAI currently has a signal for.
        limit: max number of signals to return (most recent first, capped 200).

    Returns a dict with:
        signals: list of {symbol, timeframe, side(LONG/SHORT), price, timestamp}
        count:   number of signals returned
        source:  "mefai"
        stale:   present & true only if a live fetch failed and cached data was served
    """
    limit = max(1, min(int(limit or 40), 200))
    items, is_stale = _all_signals(200)

    tf = (timeframe or "").strip().lower()
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if tf and str(it.get("timeframe", "")).lower() != tf:
            continue
        out.append(
            {
                "symbol": it.get("symbol"),
                "timeframe": it.get("timeframe"),
                "side": _side_word(str(it.get("signal", ""))),
                "price": it.get("price"),
                "timestamp": it.get("timestamp"),
            }
        )

    # Most recent first when timestamps are present.
    try:
        out.sort(key=lambda x: int(x.get("timestamp") or 0), reverse=True)
    except Exception:  # noqa: BLE001
        pass

    result: dict[str, Any] = {"signals": out[:limit], "count": min(len(out), limit), "source": "mefai"}
    if is_stale:
        result["stale"] = True
    return result


def mefai_signal_for_symbol(symbol: str, timeframe: str = "") -> dict[str, Any]:
    """Return MEFAI's current signal(s) for one symbol.

    Args:
        symbol: e.g. "BTC", "BTCUSDT", or "BTCUSDT.P" (matched loosely · the
            base ticker is enough; MEFAI perp symbols carry a ".P" suffix).
        timeframe: optional, e.g. "1h". Empty returns all timeframes for the symbol.

    Returns {symbol, matches: [{symbol, timeframe, side, price, timestamp}], source}.
    """
    want = (symbol or "").strip().upper().replace("USDT.P", "").replace("USDT", "").replace(".P", "")
    all_sig = mefai_latest_signals(timeframe=timeframe, limit=200)
    matches = []
    for it in all_sig.get("signals", []):
        base = str(it.get("symbol", "")).upper().replace("USDT.P", "").replace("USDT", "").replace(".P", "")
        if base == want:
            matches.append(it)
    result: dict[str, Any] = {"symbol": symbol, "matches": matches, "source": "mefai"}
    if all_sig.get("stale"):
        result["stale"] = True
    return result


def _urlencode(params: dict[str, str]) -> str:
    from urllib.parse import urlencode

    return urlencode(params)
