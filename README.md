# XAU/USD RSI Mean-Reversion Bot

A fully automated algorithmic trading system for gold (XAU/USD), built from scratch in Python. The bot identifies mean-reversion opportunities using RSI extremes on 5-minute bars, executes orders via the OANDA v20 REST API, and delivers real-time signal notifications and weekly performance recaps via Telegram. A built-in backtester validates strategy performance across historical data with statistical reporting.

---

## Strategy

The core idea is mean reversion: when price moves too far too fast in one direction, it tends to snap back. RSI quantifies this on a 5-minute timeframe.

- **Short signal:** RSI(14) crosses above 63 → fade the rally
- **Long signal:** RSI(14) crosses below 37 → fade the selloff
- **Stop loss:** fixed $10 from entry (server-side at broker)
- **Take profit:** dynamic — exit when RSI reverts to 37 (shorts) or 63 (longs)
- **Trend filter:** daily 50-EMA bias — only longs when price is above EMA, only shorts below. Aligns entries with the higher timeframe trend.
- **Risk management:** 40-minute cooldown after a loss, maximum 2 losses per session

---

## Key Features

**Live trading**
- Polls OANDA for 5-min XAUUSD bars every 20 seconds
- Signal detection on each newly closed bar
- Market orders with stop loss attached server-side at OANDA (protects capital even if the bot or machine goes offline)
- RSI-based exits closed via API; SL exits handled automatically by broker
- Hourly HTF bias refresh with Telegram notification on regime change
- Kill switch: create a `STOP_TRADING` file to halt new entries instantly without restarting

**Risk controls**
- FOMC blackout: 2 hours before and 30 minutes after every Federal Reserve rate decision (Wednesday 19:00/20:00 UTC)
- Red-folder news filter: ±15 minutes around all high-impact USD events (ForexFactory feed)
- Weekend gap protection: no new entries after 18:00 UTC Friday; any open position force-closed at 21:45 UTC before market close
- Daily session loss cap with cooldown

**Telegram integration**
- Entry ping with direction, price, SL, and TP rule
- Exit ping with outcome (✅ RSI target / ❌ SL hit / 🟡 RSI exit at loss / 🌙 weekend close) and P&L
- HTF bias change notifications
- Weekly recap every Friday at 22:00 UTC: trade list, win rate, net P&L, avg win/loss, best/worst trade, direction breakdown
- Weekly trade log persisted to JSON — survives bot restarts mid-week

**Backtester**
- Replays the identical strategy logic used by the live bot (shared `check_signal()` function — no separate backtest implementation)
- OANDA data source — no rate limits, pulls years of history
- Progress bar via `tqdm`
- Statistical report: win rate, profit factor, expectancy, Sharpe ratio, max drawdown, max loss streak, avg hold time, exit type breakdown, performance by direction and hour of day
- Saves `trades.csv` and `equity_curve.csv` for further analysis
- Ctrl-C at any point prints the report for trades completed so far

---

## Architecture

```
live.py          — main loop: poll → signal → execute → notify
strategy.py      — pure signal logic (shared by live and backtest)
backtest.py      — historical replay engine + statistical report
data.py          — OANDA candles API (5-min and daily bars)
broker.py        — OANDA v20 order execution (open, close, status)
news.py          — ForexFactory red-folder filter + FOMC blackout
config.py        — credentials and parameters (not committed)
config.example.py — safe template for repo
```

The key architectural decision: `strategy.py` contains one pure function (`check_signal`) that takes a DataFrame and returns a signal or None. Both the live bot and the backtester call this exact function — there is no separate backtest implementation. This means backtest results directly reflect live behaviour.

---

## Backtesting Results

Tested on ~1,000 days of 5-min XAUUSD data (Oct 2023 – Jul 2026):

| Metric | Value |
|---|---|
| Trades | 1,504 |
| Win rate | 55.3% |
| Net P&L | +212.8 R |
| Profit factor | 1.35 |
| Expectancy | +1.42 $/oz per trade |
| Max drawdown | −275 $/oz |
| Max loss streak | 11 |
| Avg win / loss | +9.92 / −9.12 $/oz |

Results across two independent 120-day windows (different market regimes) showed consistent performance — the strategy produced positive returns in both an uptrend (longs-only, Nov 2025 – Mar 2026) and a downtrend (shorts-dominant, Mar – Jul 2026), validating that the edge is regime-adaptive rather than regime-specific.

> Note: backtest results do not account for spread (~$0.30–0.50 on XAU/USD). Currently running on OANDA practice account for forward validation.

---

## Tech Stack

- **Python 3.12**
- **pandas** — bar data manipulation and RSI calculation
- **requests** — OANDA v20 REST API, ForexFactory feed, Telegram Bot API
- **tqdm** — backtest progress bar
- **OANDA v20 REST API** — market data and order execution
- **Telegram Bot API** — signal delivery
- **macOS launchd** — 24/7 process management with auto-restart

---

## Setup

```bash
git clone https://github.com/olivertwigg/XAU-RSI-Reversal-50-EMA-Bot.git
cd XAU-RSI-Reversal-50-EMA-Bot
python3 -m venv venv && source venv/bin/activate
pip install pandas requests tqdm
cp config.example.py config.py
# fill in config.py with your OANDA and Telegram credentials
```

**Run a backtest:**
```bash
python3 backtest.py --days 365
```

**Run the live bot:**
```bash
python3 live.py
```

**Run 24/7 on macOS (launchd):**
See the plist template in the README — keeps the bot alive through crashes and reboots.

---

## Design Decisions

**Why OANDA?** Their v20 REST API supports XAU/USD with no rate limits, serves both market data and order execution from the same authenticated session, and attaches stop losses server-side — meaning the broker enforces your risk even if the machine goes offline.

**Why RSI mean-reversion?** Gold frequently exhibits short-term overextension followed by reversion, particularly when larger institutional flows push price to extremes intraday. The 5-minute timeframe captures these moves while the daily EMA filter avoids fading the dominant trend.

**Why dynamic TP instead of fixed?** A fixed TP assumes you know how far the reversion will go. Exiting on RSI normalisation lets the trade ride the actual reversion rather than leaving early or holding too long.

**Why shared strategy code?** Any discrepancy between backtest and live implementation creates false confidence. Using one function for both eliminates this category of error entirely.

---

## Disclaimer

This project is for educational purposes. Past backtest performance does not guarantee future results. Currently running on a practice account — not financial advice.
