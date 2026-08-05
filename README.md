# XAUUSD RSI Signal Bot

Signals only — it tells you on Telegram, you place the trade.

## Strategy (as specified)
- Instrument: XAUUSD, 5-min bars
- SHORT when RSI(14) crosses above 63 — SL entry+$8, TP entry−$8
- LONG when RSI(14) crosses below 37 — SL entry−$8, TP entry+$8
- No entries within ±15 min of red-folder (high-impact USD) news
- 40-min cooldown after a loss; max 2 losses per day
- Both SL & TP touched in one 5-min bar → counted as a LOSS (conservative)

## Setup (on the Mac mini)

```bash
cd ~/xau-bot
python3 -m venv venv
source venv/bin/activate
pip install pandas requests
```

1. Get a free API key at twelvedata.com → put in `config.py`
2. Telegram: message @BotFather → /newbot → copy token into `config.py`
3. Message your new bot once, then visit
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
   and copy the chat id into `config.py`

## Run a backtest

```bash
python3 backtest.py --days 30        # Ctrl-C anytime -> report so far
python3 backtest.py --days 90 --news-csv red_news.csv
```

Outputs a stats report + `trades.csv` + `equity_curve.csv`.

Note: the free ForexFactory feed only covers the *current* week, so
historical backtests run with the news filter OFF unless you provide
a CSV of past red-folder timestamps (one UTC time per line).

## Run live 24/7

```bash
python3 live.py
```

To survive reboots, create `~/Library/LaunchAgents/com.oliver.xaubot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.oliver.xaubot</string>
  <key>ProgramArguments</key><array>
    <string>/Users/olivertwigg/xau-bot/venv/bin/python3</string>
    <string>/Users/olivertwigg/xau-bot/live.py</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/olivertwigg/xau-bot</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/olivertwigg/xau-bot/bot.log</string>
  <key>StandardErrorPath</key><string>/Users/olivertwigg/xau-bot/bot.log</string>
</dict></plist>
```

Then:
```bash
launchctl load ~/Library/LaunchAgents/com.oliver.xaubot.plist
```

Also: System Settings → Energy → enable "Prevent automatic sleeping".

## Honest caveats
- Backtest fills are approximate: entry at signal-bar close, exits at exact
  SL/TP levels, no spread/slippage. Gold spread (~$0.30–0.50) matters on an
  $8 bracket — expect live results a few % worse than backtest.
- A 1:1 bracket needs >50% win rate just to break even before costs.
- Past performance ≠ future results. This is a tool, not advice.

#Know Your Control Commands
# is it running?
launchctl list | grep xaubot        # a number in the first column = alive

# watch the log live
tail -f "/Users/olivertwigg/Desktop/XAU RSI bot/files/bot.log"

# stop it
launchctl unload ~/Library/LaunchAgents/com.oliver.xaubot.plist

# start it again
launchctl load ~/Library/LaunchAgents/com.oliver.xaubot.plist
