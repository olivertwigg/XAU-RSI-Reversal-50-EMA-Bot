"""
Merge Apify ForexFactory JSON into forex_factory_cache.csv.
Run from the bot files folder:
  python3 merge_apify.py /path/to/apify_export.json
"""
import sys
import json
import pandas as pd

if len(sys.argv) < 2:
    print("Usage: python3 merge_apify.py <apify_export.json>")
    sys.exit(1)

json_path = sys.argv[1]
csv_path = "forex_factory_cache.csv"

# Load Apify JSON
with open(json_path) as f:
    events = json.load(f)

print(f"Loaded {len(events)} events from Apify JSON")

# Convert to DataFrame matching HF schema
rows = []
for ev in events:
    dt_raw = ev.get("datetimeISO", "")
    if not dt_raw:
        continue
    # Convert "2025-04-07T22:00:00Z" -> "2025-04-07T22:00:00+00:00"
    dt_str = dt_raw.replace("Z", "+00:00")

    impact_raw = ev.get("impactTitle", "")
    # impactTitle already matches HF: "High Impact Expected" etc.
    impact = impact_raw if impact_raw else "Non-Economic"

    rows.append({
        "DateTime": dt_str,
        "Currency": ev.get("currency", ""),
        "Impact":   impact,
        "Event":    ev.get("title", ""),
        "Actual":   ev.get("actual", ""),
        "Forecast": ev.get("forecast", ""),
        "Previous": ev.get("previous", ""),
        "Detail":   "",
    })

apify_df = pd.DataFrame(rows)
print(f"Apify rows: {len(apify_df)}")
print(f"Apify date range: {apify_df['DateTime'].min()} to {apify_df['DateTime'].max()}")

# Load existing HF CSV and normalise timestamps to UTC
hf = pd.read_csv(csv_path)
print(f"HF CSV rows before merge: {len(hf)}")

hf["DateTime"] = (
    pd.to_datetime(hf["DateTime"], utc=True)
      .dt.tz_convert("UTC")
      .dt.tz_localize(None)
      .dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
)

# Combine, sort, save
combined = pd.concat([hf, apify_df], ignore_index=True)
combined = combined.sort_values("DateTime").reset_index(drop=True)
combined.to_csv(csv_path, index=False)

print(f"Combined rows: {len(combined)}")
print(f"Full date range: {combined['DateTime'].min()} to {combined['DateTime'].max()}")
print("Done.")
