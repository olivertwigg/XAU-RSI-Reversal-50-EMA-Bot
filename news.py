"""
News filter — red folder (high impact USD) events.

LIVE BOT:
  Fetches this week's Forex Factory events once at startup and once per day
  (via JBlanked free API — 1 req/day limit is fine). Caches to news_cache.json
  so restarts don't burn the daily credit.

BACKTESTER:
  Pass the community-collated Forex Factory CSV (2007-Apr 2025) via the
  --news-csv argument, OR drop the file at the path in NEWS_HISTORY_CSV
  and historical_red_folder() will find it automatically.

  Obtain the file from: https://huggingface.co/datasets/Tropstan/Forex_Factory_Calendar
  (download forex_factory_cache.csv)

  Coverage: 2007 – April 2025. Dates after that run without the filter
  (live bot filters correctly in real time for those bars).

Setup (live bot):
  1. Sign up at jblanked.com -> profile -> generate API key
  2. Add to config.py:  JBLANKED_KEY = "your-key-here"
"""

import json
import os
import time
from datetime import datetime, timezone, timedelta
import requests

CACHE_FILE       = "news_cache.json"
CACHE_HOURS      = 23          # refresh once per day
CURRENCIES       = {"USD"}
NEWS_BUFFER_MIN  = 15

# Drop the Hugging Face CSV here and backtests pick it up automatically.
# Override with --news-csv on the command line.
NEWS_HISTORY_CSV = "forex_factory_cache.csv"


def _fetch_from_api(api_key: str) -> list[datetime]:
    """Fetch this week's high-impact USD events from JBlanked/ForexFactory."""
    url = "https://www.jblanked.com/news/api/forex-factory/calendar/"
    headers = {
        "Authorization": f"Api-Key {api_key}",
        "Content-Type": "application/json",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    events = resp.json()

    times = []
    for ev in events:
        # filter: high impact USD only
        if str(ev.get("Impact", "")).strip() != "High":
            continue
        currency = ev.get("Currency", "")
        if CURRENCIES and currency not in CURRENCIES:
            continue
        # Date field: "2026.10.23 17:00:00" (UTC)
        raw = ev.get("Date", "")
        if not raw:
            continue
        try:
            ts = datetime.strptime(str(raw), "%Y.%m.%d %H:%M:%S")
            times.append(ts)  # already UTC, no tzinfo needed
        except Exception:
            pass
    return times


def _load_cache() -> tuple[list[datetime], float]:
    """Load cached times and fetch timestamp. Returns (times, fetched_at)."""
    try:
        with open(CACHE_FILE) as f:
            data = json.load(f)
        times = [datetime.fromisoformat(t) for t in data["times"]]
        return times, data["fetched_at"]
    except Exception:
        return [], 0.0


def _save_cache(times: list[datetime]):
    with open(CACHE_FILE, "w") as f:
        json.dump({
            "fetched_at": time.time(),
            "times": [t.isoformat() for t in times],
        }, f)


def red_folder_times() -> list[datetime]:
    """
    Returns this week's high-impact USD event times (UTC, naive).
    Uses cache; only hits the API once per day.
    """
    cached_times, fetched_at = _load_cache()
    age_hours = (time.time() - fetched_at) / 3600

    if cached_times and age_hours < CACHE_HOURS:
        return cached_times

    # try to refresh
    try:
        from config import JBLANKED_KEY
        if not JBLANKED_KEY or JBLANKED_KEY.startswith("YOUR_"):
            raise ValueError("no key")
        times = _fetch_from_api(JBLANKED_KEY)
        _save_cache(times)
        print(f"[news] refreshed: {len(times)} high-impact USD events this week")
        return times
    except Exception as e:
        print(f"[news] refresh failed ({e}); using cache ({len(cached_times)} events)")
        return cached_times


def near_news(ts: datetime, news_times: list[datetime],
              buffer_min: int = NEWS_BUFFER_MIN) -> bool:
    buf = timedelta(minutes=buffer_min)
    return any(abs(ts - n) <= buf for n in news_times)


def historical_red_folder(start: str, end: str,
                           csv_path: str | None = None) -> list[datetime]:
    """
    Load historical high-impact USD events from the community-collated
    Forex Factory CSV (Hugging Face: Tropstan/Forex_Factory_Calendar).

    Filters to the requested date range and returns UTC naive datetimes.
    Falls back gracefully if the file is not present.
    """
    import pandas as pd

    path = csv_path or NEWS_HISTORY_CSV
    if not os.path.exists(path):
        print(f"[news] {path} not found — backtest runs without news filter")
        print("       Download from: https://huggingface.co/datasets/Tropstan/Forex_Factory_Calendar")
        return []

    try:
        df = pd.read_csv(path, usecols=["DateTime", "Currency", "Impact"])

        # Keep only high-impact USD events
        df = df[
            (df["Currency"] == "USD") &
            (df["Impact"] == "High Impact Expected")
        ].copy()

        # Parse timestamps — CSV uses local Iranian time (+03:30); convert to UTC
        df["dt_utc"] = (
            pd.to_datetime(df["DateTime"], utc=True)
              .dt.tz_convert("UTC")
              .dt.tz_localize(None)
        )

        # Filter to requested backtest window (with a 1-day buffer each side)
        t0 = pd.Timestamp(start) - pd.Timedelta(days=1)
        t1 = pd.Timestamp(end)   + pd.Timedelta(days=1)
        df = df[(df["dt_utc"] >= t0) & (df["dt_utc"] <= t1)]

        times = df["dt_utc"].dt.to_pydatetime().tolist()

        # Warn if the CSV doesn't cover the full backtest window
        csv_end = pd.Timestamp("2025-04-07")  # known end of Hugging Face dataset
        if pd.Timestamp(end) > csv_end:
            uncovered_days = (pd.Timestamp(end) - csv_end).days
            print(f"[news] loaded {len(times)} high-impact USD events from {path}")
            print(f"       ⚠  CSV ends {csv_end:%Y-%m-%d} — last {uncovered_days} days "
                  f"of the backtest run without the news filter")
        else:
            print(f"[news] loaded {len(times)} high-impact USD events from {path}")

        return times

    except Exception as e:
        print(f"[news] failed to load {path}: {e} — backtest runs without news filter")
        return []
