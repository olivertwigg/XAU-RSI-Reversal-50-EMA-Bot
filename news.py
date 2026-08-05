"""
Red-folder (high impact) news times from ForexFactory's public weekly JSON feed.
Refreshed on a cache so we don't hammer the endpoint.

For XAUUSD, USD events are what matter most; CURRENCIES is configurable.
NOTE: this feed only covers the current week — fine for live trading.
For backtests over past data, historical red-folder times aren't in this feed;
the backtester will run without the news filter unless you supply a CSV
(see backtest.py --news-csv).
"""

import time
from datetime import datetime, timezone
import requests

FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CURRENCIES = {"USD"}          # add "ALL" behaviour by making this empty
_cache: dict = {"fetched": 0.0, "times": []}
CACHE_SECONDS = 6 * 3600      # refresh every 6 hours


def red_folder_times() -> list[datetime]:
    now = time.time()
    if now - _cache["fetched"] < CACHE_SECONDS and _cache["times"]:
        return _cache["times"]
    try:
        resp = requests.get(FEED, timeout=20,
                            headers={"User-Agent": "xau-signal-bot/1.0"})
        resp.raise_for_status()
        events = resp.json()
        times = []
        for ev in events:
            if ev.get("impact") != "High":
                continue
            if CURRENCIES and ev.get("country") not in CURRENCIES:
                continue
            # feed dates look like "2026-07-04T13:30:00-04:00"
            ts = datetime.fromisoformat(ev["date"]).astimezone(timezone.utc)
            times.append(ts.replace(tzinfo=None))
        _cache.update(fetched=now, times=times)
    except Exception as e:
        print(f"[news] feed fetch failed ({e}); using last known times")
    return _cache["times"]


def historical_red_folder(start: str, end: str) -> list[datetime]:
    """
    High-impact USD events between start/end (YYYY-MM-DD), via Financial
    Modeling Prep's economic calendar. Used by the backtester. Pages in
    ~85-day chunks (free-tier range limit). Returns UTC datetimes.
    """
    from config import FMP_KEY
    if not FMP_KEY or FMP_KEY.startswith("YOUR_"):
        print("[news] no FMP_KEY in config.py -> historical news filter OFF")
        return []
    import pandas as pd
    times = []
    cursor = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    while cursor <= end_ts:
        chunk_end = min(cursor + pd.Timedelta(days=85), end_ts)
        try:
            r = requests.get(
                "https://financialmodelingprep.com/api/v3/economic_calendar",
                params={"from": cursor.strftime("%Y-%m-%d"),
                        "to": chunk_end.strftime("%Y-%m-%d"),
                        "apikey": FMP_KEY},
                timeout=30)
            r.raise_for_status()
            for ev in r.json():
                if ev.get("impact") != "High":
                    continue
                if ev.get("country") not in ("US", "USD"):
                    continue
                times.append(pd.Timestamp(ev["date"]).to_pydatetime())
        except Exception as e:
            print(f"[news] FMP fetch failed for {cursor.date()}..{chunk_end.date()}: {e}")
        cursor = chunk_end + pd.Timedelta(days=1)
    print(f"[news] {len(times)} historical red-folder USD events loaded")
    return times
