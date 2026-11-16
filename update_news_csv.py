"""
Weekly news CSV updater.

Fetches this week's high-impact USD events from JBlanked/ForexFactory
and appends any new rows to forex_factory_cache.csv — keeping the historical
dataset current for future backtests.

Run manually, or schedule via launchd to run every Sunday evening:
  python3 update_news_csv.py

Designed to be idempotent: will not add duplicate rows even if run twice
in the same week.
"""

import os
import sys
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

NEWS_HISTORY_CSV = "forex_factory_cache.csv"


def fetch_week_events(api_key: str) -> list[dict]:
    """Fetch all events from JBlanked and filter to the current week (USD High only).

    /calendar/week/ returns [] — /calendar/ returns full history, so we filter
    client-side to the Mon–Sun window of the current week.
    Only USD High Impact rows are kept so the CSV stays lean.
    Run on Sunday evening so actuals are populated.
    """
    url = "https://www.jblanked.com/news/api/forex-factory/calendar/"
    headers = {
        "Authorization": f"Api-Key {api_key}",
        "Content-Type": "application/json",
    }
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    all_events = resp.json()

    # Current week: Monday 00:00 UTC -> Sunday 23:59 UTC
    today = datetime.now(timezone.utc)
    week_start = (today - timedelta(days=today.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=7)

    filtered = []
    for ev in all_events:
        if str(ev.get("Impact", "")).strip() != "High":
            continue
        if str(ev.get("Currency", "")).strip() != "USD":
            continue
        raw = ev.get("Date", "")
        if not raw:
            continue
        try:
            ts = datetime.strptime(str(raw), "%Y.%m.%d %H:%M:%S").replace(tzinfo=timezone.utc)
            if week_start <= ts < week_end:
                filtered.append(ev)
        except Exception:
            continue

    print(f"[update_news] {len(filtered)} USD High Impact events this week "
          f"(from {len(all_events)} total)")
    return filtered


def events_to_df(events: list[dict]) -> pd.DataFrame:
    """Convert JBlanked /calendar/ events to the same schema as forex_factory_cache.csv."""
    rows = []
    for ev in events:
        raw = ev.get("Date", "")
        if not raw:
            continue
        try:
            ts = datetime.strptime(str(raw), "%Y.%m.%d %H:%M:%S")
            dt_str = ts.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        except Exception:
            continue

        impact_raw = str(ev.get("Impact", "")).strip()
        if impact_raw == "High":
            impact = "High Impact Expected"
        elif impact_raw == "Medium":
            impact = "Medium Impact Expected"
        elif impact_raw == "Low":
            impact = "Low Impact Expected"
        else:
            impact = "Non-Economic"

        rows.append({
            "DateTime": dt_str,
            "Currency": ev.get("Currency", ""),
            "Impact":   impact,
            "Event":    ev.get("Name", ""),
            "Actual":   ev.get("Actual", ""),
            "Forecast": ev.get("Forecast", ""),
            "Previous": ev.get("Previous", ""),
            "Detail":   "",
        })
    return pd.DataFrame(rows)


def main():
    try:
        from config import JBLANKED_KEY
        if not JBLANKED_KEY or JBLANKED_KEY.startswith("YOUR_"):
            print("[update_news] No JBLANKED_KEY in config.py — cannot update.")
            sys.exit(1)
    except ImportError:
        print("[update_news] config.py not found — run from the bot folder.")
        sys.exit(1)

    print(f"[update_news] Fetching this week's events from JBlanked…")
    try:
        events = fetch_week_events(JBLANKED_KEY)
    except Exception as e:
        print(f"[update_news] Fetch failed: {e}")
        sys.exit(1)

    new_df = events_to_df(events)
    if new_df.empty:
        print("[update_news] No events returned.")
        sys.exit(0)

    # Load existing CSV
    if os.path.exists(NEWS_HISTORY_CSV):
        existing = pd.read_csv(NEWS_HISTORY_CSV,
                               usecols=["DateTime","Currency","Impact","Event",
                                        "Actual","Forecast","Previous","Detail"])
        existing_keys = set(
            zip(existing["DateTime"], existing["Currency"], existing["Event"])
        )
        before = len(new_df)
        new_df = new_df[
            ~new_df.apply(
                lambda r: (r["DateTime"], r["Currency"], r["Event"]) in existing_keys,
                axis=1
            )
        ]
        print(f"[update_news] {before - len(new_df)} duplicate(s) skipped, "
              f"{len(new_df)} new row(s) to append")

        if new_df.empty:
            print("[update_news] CSV already up to date.")
            return

        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        print(f"[update_news] {NEWS_HISTORY_CSV} not found — creating it.")
        combined = new_df

    combined = combined.sort_values("DateTime").reset_index(drop=True)
    combined.to_csv(NEWS_HISTORY_CSV, index=False)

    latest = new_df["DateTime"].max()
    print(f"[update_news] ✅ Appended {len(new_df)} rows. "
          f"CSV now has {len(combined)} total rows. "
          f"Latest event: {latest}")


if __name__ == "__main__":
    main()
