# XAU/USD RSI Mean-Reversion Bot

A fully automated algorithmic trading system for gold (XAU/USD), built from scratch in Python. The bot identifies mean-reversion opportunities using RSI extremes on 5-minute bars, executes orders via the OANDA v20 REST API, and delivers real-time signal notifications and weekly performance recaps via Telegram. A built-in backtester replays the live strategy over any historical window and reports risk-adjusted returns, with bootstrap Monte Carlo simulation to test how robust the results are.


## 📓 Development Journal

A running personal log kept throughout the build — initial breakdown, iteration timeline, and the thinking 
behind key decisions.

[View the journal →](https://app.notion.com/p/XAU-RSI-Reversal-50-EMA-Bot-39fe2431311e80daa39ae5cb25da86f3?source=copy_link)

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
- Red-folder news filter: ±15 minutes around all high-impact USD events (ForexFactory calendar), applied identically in live trading and backtests
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
- Any historical window: N days back from today, N days forward from a start date, or N days back from an end date
- OANDA data source — no rate limits, pulls years of history
- Historical news filter backed by a ForexFactory calendar going back to 2007
- Statistical report: win rate, profit factor, expectancy, Sharpe and Sortino ratios, max drawdown, max loss streak, avg hold time, exit type breakdown, performance by direction and hour of day
- Saves `trades.csv` and `equity_curve.csv` for further analysis
- Ctrl-C at any point prints the report for trades completed so far

**Risk-adjusted returns**
- Sharpe and Sortino are calculated on daily returns against a $1,000 notional account (the $10 stop = 1% risk per trade)
- Risk-free rate: 4.99%, the UK NS&I one-year bond rate
- Sortino only penalises downside volatility, which suits a strategy whose large moves are mostly winners

**Monte Carlo simulation**
- Bootstrap resampling: each trial redraws the same number of trades, with replacement, from the backtest's trade pool
- 10,000 trials per run, reporting average and median final balance, 5th/95th percentiles, % of profitable trials and the max drawdown distribution
- Every simulated equity path is saved to `mc_paths.npy` for further analysis
- `plot_mc.py` charts a sample of paths with the median, 5th/95th percentiles and the real backtest path overlaid

**News data pipeline**
- Historical calendar: the [Tropstan/Forex_Factory_Calendar](https://huggingface.co/datasets/Tropstan/Forex_Factory_Calendar) dataset (2007 onwards), with timestamps normalised to UTC
- Later events backfilled from a ForexFactory scraper export via `merge_apify.py`
- `update_news_csv.py` appends each week's high-impact USD events, scheduled for Sunday 21:00 by launchd so actuals are populated
- The calendar is not committed (68 MB) and has one gap, Apr–Oct 2025, still to be backfilled

---

## Architecture

```
live.py              — main loop: poll → signal → execute → notify
strategy.py          — pure signal logic (shared by live and backtest)
backtest.py          — historical replay engine, statistical report, Monte Carlo
plot_mc.py           — charts the saved Monte Carlo equity paths
data.py              — OANDA candles API (5-min and daily bars)
broker.py            — OANDA v20 order execution (open, close, status)
news.py              — ForexFactory red-folder filter + FOMC blackout
update_news_csv.py   — weekly news calendar update
merge_apify.py       — merges scraped calendar data into the historical CSV
com.xaubot.newsupdater.plist — launchd schedule for the weekly news update
config.py            — credentials and parameters (not committed)
config.example.py    — safe template for repo
```

The key architectural decision: `strategy.py` contains one pure function (`check_signal`) that takes a DataFrame and returns a signal or None. Both the live bot and the backtester call this exact function — there is no separate backtest implementation. This means backtest results directly reflect live behaviour.

---

## Backtesting Results

**Oct 2024 – Oct 2026** (730 days, 5-min XAUUSD):

| Metric | Value |
|---|---|
| Trades | 1,096 |
| Win rate | 49.5% |
| Net P&L | +195.1 R |
| Profit factor | 1.36 |
| Expectancy | +1.78 $/oz per trade |
| Sharpe ratio | 2.62 |
| Sortino ratio | ≈5 |
| Max drawdown | −265 $/oz |
| Max loss streak | 11 |
| Avg win / loss | +13.58 / −9.76 $/oz |

**2023** (range-bound gold, for comparison):

| Metric | Value |
|---|---|
| Trades | 924 |
| Win rate | 65.3% |
| Net P&L | +30.0 R |
| Profit factor | 1.15 |
| Sharpe ratio | 1.33 |
| Sortino ratio | 2.75 |
| Monte Carlo: profitable trials | 95.4% |
| Monte Carlo: 5th percentile balance | $1,008 (from $1,000) |

The strategy performs best in strongly trending markets. In 2023 it stayed profitable but the edge was thin: 4.6% of Monte Carlo trials lost money, so the result is only borderline distinguishable from zero expected value. In ranging markets the daily EMA bias lags, so the bot can keep fading moves in the wrong direction before it flips.

> Notes: results do not account for spread (~$0.30–0.50 on XAU/USD). Part of the 2024–2026 window ran without the historical news filter because of the calendar gap. The bootstrap assumes trades are independent, so it likely understates drawdowns when losses cluster. Currently running on an OANDA practice account for forward validation.

---

## Tech Stack

- **Python 3.12**
- **pandas** — bar data manipulation and RSI calculation
- **numpy** — Monte Carlo resampling
- **matplotlib** — Monte Carlo charts
- **requests** — OANDA v20 REST API, news feeds, Telegram Bot API
- **tqdm** — backtest progress bar
- **OANDA v20 REST API** — market data and order execution
- **Telegram Bot API** — signal delivery
- **macOS launchd** — 24/7 process management with auto-restart, and the weekly news update

---

## Setup

```bash
git clone https://github.com/olivertwigg/XAU-RSI-Reversal-50-EMA-Bot.git
cd XAU-RSI-Reversal-50-EMA-Bot
python3 -m venv venv && source venv/bin/activate
pip install pandas numpy requests tqdm matplotlib
cp config.example.py config.py
# fill in config.py with your OANDA and Telegram credentials
```

For the historical news filter, download `forex_factory_cache.csv` from the [Hugging Face dataset](https://huggingface.co/datasets/Tropstan/Forex_Factory_Calendar) into the project folder. Without it, backtests run with no news filter.

**Run a backtest:**
```bash
python3 backtest.py --days 365                      # 365 days back from today
python3 backtest.py --days 365 --start 2023-01-01   # 365 days from a start date
python3 backtest.py --days 365 --end 2024-01-01     # 365 days back from an end date
```

**Add a Monte Carlo simulation and chart it:**
```bash
python3 backtest.py --days 365 --start 2023-01-01 --mc
python3 plot_mc.py
```

**Run the live bot:**
```bash
python3 live.py
```

**Run 24/7 on macOS (launchd):** use a launchd plist to keep the bot alive through crashes and reboots. `com.xaubot.newsupdater.plist` is a working example for the weekly news update.

---

## Design Decisions

**Why OANDA?** Their v20 REST API supports XAU/USD with no rate limits, serves both market data and order execution from the same authenticated session, and attaches stop losses server-side — meaning the broker enforces your risk even if the machine goes offline.

**Why RSI mean-reversion?** Gold frequently exhibits short-term overextension followed by reversion, particularly when larger institutional flows push price to extremes intraday. The 5-minute timeframe captures these moves while the daily EMA filter avoids fading the dominant trend.

**Why dynamic TP instead of fixed?** A fixed TP assumes you know how far the reversion will go. Exiting on RSI normalisation lets the trade ride the actual reversion rather than leaving early or holding too long.

**Why shared strategy code?** Any discrepancy between backtest and live implementation creates false confidence. Using one function for both eliminates this category of error entirely.

**Why bootstrap Monte Carlo?** A single backtest is one path through history. Resampling trades with replacement shows the range of outcomes the same edge could have produced, and how often it would have lost money. Simply shuffling the trade order can't do that, because every shuffle ends at the same final balance.

---

## Disclaimer

This project is for educational purposes. Past backtest performance does not guarantee future results. Currently running on a practice account — not financial advice.
