#!/usr/bin/env python3
"""Write the showcase's live signal feed (signals.json) from MEFAI's signal DB.

Standalone, read-only, dependency-free (stdlib only). A self-hosted deploy runs
this on a short timer so the showcase page shows a live, always-populated feed.

Env:
  MEFAI_SIGNAL_DB   path to MEFAI's signals sqlite (required)
  SHOWCASE_OUT      output path for signals.json (default ./signals.json)
  SHOWCASE_LIMIT    max signals to emit (default 16)
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile

DB = os.environ.get("MEFAI_SIGNAL_DB", "").strip()
OUT = os.environ.get("SHOWCASE_OUT", "signals.json")
LIMIT = int(os.environ.get("SHOWCASE_LIMIT", "16"))

# Symbols surfaced first (recognisable majors), then fill with whatever is fresh.
PREFERRED = ["BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "LINK",
             "AVAX", "SUI", "TAO", "RENDER", "LDO", "1000PEPE", "HYPE", "VIRTUAL"]


def _base(sym: str) -> str:
    return (sym or "").upper().replace("USDT.P", "").replace(".P", "")


def _side(sig: str) -> str:
    s = (sig or "").lower()
    if s in ("buy", "long"):
        return "LONG"
    if s in ("sell", "short"):
        return "SHORT"
    return (sig or "").upper()


def read_latest() -> list[dict]:
    if not DB or not os.path.exists(DB):
        return []
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=2.0)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT symbol, timeframe, signal, timestamp, price FROM signals "
            "WHERE id IN (SELECT MAX(id) FROM signals GROUP BY symbol, timeframe) "
            "ORDER BY timestamp DESC LIMIT 400"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "symbol": r["symbol"],
            "timeframe": r["timeframe"],
            "side": _side(r["signal"]),
            "price": r["price"],
            "timestamp": int(r["timestamp"]),
        }
        for r in rows
    ]


def pick(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for p in PREFERRED:
        for r in rows:
            if _base(r["symbol"]) == p and r["symbol"] not in seen:
                out.append(r)
                seen.add(r["symbol"])
                break
    for r in rows:
        if len(out) >= LIMIT:
            break
        if r["symbol"] not in seen:
            out.append(r)
            seen.add(r["symbol"])
    return out[:LIMIT]


def main() -> int:
    rows = read_latest()
    if not rows:
        # Never overwrite a good feed with an empty one.
        print("no signals read; leaving existing feed untouched", file=sys.stderr)
        return 1
    payload = {"signals": pick(rows), "count": len(rows)}
    d = os.path.dirname(os.path.abspath(OUT)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    os.fchmod(fd, 0o644)  # mkstemp defaults to 0600 · the web server must be able to read the feed
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    os.replace(tmp, OUT)  # atomic
    print(f"wrote {len(payload['signals'])} signals to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
