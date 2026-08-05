"""
Market data via OANDA v20 candles API.

Uses the same OANDA_TOKEN and OANDA_ACCOUNT_ID already in config.py —
no extra API key, no rate limits, no daily credit caps.

Granularities used:
  M5  -> 5-min bars  (live polling + backtests)
  D   -> daily bars  (HTF trend filter)

Price type: M (midpoint) — avoids bid/ask spread bias in RSI calculation.
Max 5000 candles per request; fetch_history pages automatically.
"""

import requests
import pandas as pd
from config import OANDA_TOKEN, OANDA_ENV

HOSTS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live":     "https://api-fxtrade.oanda.com",
}
INSTRUMENT = "XAU_USD"
GRANULARITY_MAP = {"5min": "M5", "1day": "D"}


def _headers():
    return {"Authorization": f"Bearer {OANDA_TOKEN}",
            "Content-Type": "application/json"}


def _base():
    return HOSTS[OANDA_ENV]


def _parse(candles: list) -> pd.DataFrame:
    """Convert OANDA candle list to standard OHLC DataFrame, closed bars only."""
    rows = []
    for c in candles:
        if not c.get("complete", True):
            continue                       # skip the still-forming bar
        m = c["mid"]
        rows.append({
            "datetime": pd.Timestamp(c["time"]),
            "open":  float(m["o"]),
            "high":  float(m["h"]),
            "low":   float(m["l"]),
            "close": float(m["c"]),
        })
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    df = pd.DataFrame(rows).set_index("datetime").sort_index()
    df.index = df.index.tz_localize(None)
    return df


def fetch_bars(interval: str = "5min", limit: int = 300,
               start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """
    Fetch up to `limit` bars (max 5000). If start/end supplied they take
    priority over limit (used by fetch_history paging).
    """
    gran = GRANULARITY_MAP.get(interval, interval)
    params: dict = {"granularity": gran, "price": "M"}

    if start and end:
        params["from"] = pd.Timestamp(start).isoformat() + "Z"
        params["to"]   = pd.Timestamp(end).isoformat() + "Z"
    elif start:
        params["from"]  = pd.Timestamp(start).isoformat() + "Z"
        params["count"] = min(limit, 5000)
    else:
        params["count"] = min(limit, 5000)

    url = f"{_base()}/v3/instruments/{INSTRUMENT}/candles"
    resp = requests.get(url, params=params, headers=_headers(), timeout=30)
    resp.raise_for_status()
    return _parse(resp.json().get("candles", []))


def fetch_history(days: int) -> pd.DataFrame:
    """
    Fetch `days` of 5-min bars, paging in 5000-candle chunks (~17 days each).
    Used by the backtester.
    """
    end   = pd.Timestamp.utcnow().floor("min").tz_localize(None)
    start = end - pd.Timedelta(days=days)
    frames = []
    cursor_start = start

    while cursor_start < end:
        # each M5 chunk: 5000 bars = ~17.4 days
        chunk_end = min(cursor_start + pd.Timedelta(minutes=5 * 5000), end)
        df = fetch_bars(interval="5min",
                        start=str(cursor_start.tz_localize(None)),
                        end=str(chunk_end.tz_localize(None)))
        if df.empty:
            break
        frames.append(df)
        cursor_start = pd.Timestamp(df.index[-1]) + pd.Timedelta(minutes=5)
        if cursor_start >= end:
            break

    if not frames:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    out = pd.concat(frames).sort_index()
    return out[~out.index.duplicated(keep="first")]


def fetch_daily(limit: int = 120, end: str | None = None) -> pd.DataFrame:
    """Daily bars for the HTF trend filter."""
    return fetch_bars(interval="1day", limit=limit, end=end)
