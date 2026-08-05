"""
Backtester — replays historical 5-min bars through the exact same
strategy.check_signal() the live bot uses, then prints a stats report
and writes trades + equity curve to CSV.

Usage:
  python3 backtest.py --days 30
  python3 backtest.py --days 90 --news-csv red_news.csv
  (Ctrl-C at any time -> prints the report for trades so far.)

news CSV format (optional, for historical red-folder filtering):
  one UTC timestamp per line, e.g. 2026-06-06 12:30
"""

import argparse
import sys
from datetime import datetime
import pandas as pd

from data import fetch_history, fetch_daily
from tqdm import tqdm
from strategy import (StrategyState, check_signal, rsi, trend_bias,
                      resolve_bar, RSI_PERIOD, SL_DOLLARS,
                      TREND_EMA_PERIOD, TREND_FILTER)


def load_news_csv(path: str) -> list[datetime]:
    times = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                times.append(pd.Timestamp(line).to_pydatetime())
    print(f"loaded {len(times)} red-folder times from {path}")
    return times


def build_bias_map(bars: pd.DataFrame) -> dict:
    """date -> 'long'/'short' using daily EMA50 of CLOSED days only (no lookahead)."""
    if not TREND_FILTER:
        return {}
    daily = fetch_daily(limit=TREND_EMA_PERIOD + (bars.index[-1] - bars.index[0]).days + 10,
                        end=str(bars.index[-1]))
    daily.index = daily.index.tz_localize(None)
    close = daily["close"]
    biases = {}
    dates = sorted(set(bars.index.date))
    for d in dates:
        prior = close[close.index.date < d]          # only fully closed days
        biases[d] = trend_bias(prior)
    return biases


def run_backtest(bars: pd.DataFrame, news_times: list[datetime]) -> pd.DataFrame:
    state = StrategyState()
    trades = []
    open_trade = None
    bias_map = build_bias_map(bars)
    rsi_all = rsi(bars["close"])          # precompute once

    try:
        for i in tqdm(range(RSI_PERIOD + 2, len(bars)), desc='Backtesting', unit='bar'):
            window = bars.iloc[: i + 1]
            bar = bars.iloc[i]
            ts = bars.index[i].to_pydatetime()

            # resolve open trade first
            if open_trade:
                sig = open_trade
                outcome, exit_px = resolve_bar(sig, bar.high, bar.low,
                                               bar.close, float(rsi_all.iloc[i]))
                if outcome:
                    pnl = (exit_px - sig.entry if sig.direction == "long"
                           else sig.entry - exit_px)
                    won = pnl >= 0
                    state.record_result(ts, won)
                    trades.append({
                        "entry_time": sig.time, "exit_time": ts,
                        "direction": sig.direction, "entry": sig.entry,
                        "exit": exit_px,
                        "exit_type": outcome,          # "sl" or "rsi"
                        "result": "win" if won else "loss",
                        "pnl_usd": pnl,
                        "rsi_at_entry": sig.rsi_value,
                    })
                    open_trade = None

            if open_trade is None:
                bias = bias_map.get(ts.date())
                sig = check_signal(window, state, news_times, bias)
                if sig:
                    state.in_position = True
                    open_trade = sig
    except KeyboardInterrupt:
        print("\n[stopped by user — reporting trades so far]")

    return pd.DataFrame(trades)


def report(trades: pd.DataFrame, bars: pd.DataFrame):
    print("\n" + "=" * 52)
    print(" XAUUSD RSI Mean-Reversion — Backtest Report")
    print("=" * 52)
    print(f" Period: {bars.index[0]:%Y-%m-%d} -> {bars.index[-1]:%Y-%m-%d}"
          f"   ({len(bars):,} five-min bars)")

    if trades.empty:
        print(" No trades generated in this period.")
        return

    n = len(trades)
    wins = (trades.result == "win").sum()
    losses = n - wins
    win_rate = wins / n * 100
    pnl = trades.pnl_usd.sum()
    equity = trades.pnl_usd.cumsum()
    peak = equity.cummax()
    max_dd = (equity - peak).min()

    # streaks
    streak = max_loss_streak = 0
    for r in trades.result:
        streak = streak + 1 if r == "loss" else 0
        max_loss_streak = max(max_loss_streak, streak)

    gross_win = trades.loc[trades.result == "win", "pnl_usd"].sum()
    gross_loss = -trades.loc[trades.result == "loss", "pnl_usd"].sum()
    pf = gross_win / gross_loss if gross_loss else float("inf")
    expectancy = trades.pnl_usd.mean()

    hold = (pd.to_datetime(trades.exit_time) -
            pd.to_datetime(trades.entry_time)).dt.total_seconds() / 60

    print(f"\n Trades:            {n}   ({wins} W / {losses} L)")
    print(f" Win rate:          {win_rate:.1f}%   (breakeven at 1:1 = 50%)")
    print(f" Net P&L:           {pnl:+.0f} $/oz   ({pnl / SL_DOLLARS:+.1f} R)")
    print(f" Expectancy:        {expectancy:+.2f} $/oz per trade")
    print(f" Profit factor:     {pf:.2f}")
    print(f" Max drawdown:      {max_dd:.0f} $/oz")
    print(f" Max loss streak:   {max_loss_streak}")
    print(f" Avg hold time:     {hold.mean():.0f} min  (median {hold.median():.0f})")
    avg_win = trades.loc[trades.result == "win", "pnl_usd"].mean()
    avg_loss = trades.loc[trades.result == "loss", "pnl_usd"].mean()
    print(f" Avg win / loss:    {avg_win:+.2f} / {avg_loss:+.2f} $/oz")
    print(" Exit types:        " + ", ".join(
        f"{k}: {v}" for k, v in trades.exit_type.value_counts().items()))

    print("\n By direction:")
    for d, g in trades.groupby("direction"):
        wr = (g.result == "win").mean() * 100
        print(f"   {d:>5}: {len(g):>3} trades, {wr:.0f}% win, "
              f"{g.pnl_usd.sum():+.0f} $/oz")

    print("\n By hour (UTC):")
    hours = trades.assign(h=pd.to_datetime(trades.entry_time).dt.hour)
    for h, g in hours.groupby("h"):
        wr = (g.result == "win").mean() * 100
        print(f"   {h:02d}:00  {len(g):>3} trades  {wr:.0f}% win  "
              f"{g.pnl_usd.sum():+.0f} $/oz")

    trades.to_csv("trades.csv", index=False)
    equity.to_frame("equity_usd_per_oz").to_csv("equity_curve.csv")
    print("\n Saved: trades.csv, equity_curve.csv")
    print("=" * 52)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--news-csv", default=None,
                    help="optional CSV of historical red-folder times (UTC)")
    args = ap.parse_args()

    print(f"fetching {args.days} days of 5-min XAUUSD bars…")
    bars = fetch_history(args.days)

    if args.news_csv:
        news_times = load_news_csv(args.news_csv)
    else:
        from news import historical_red_folder
        news_times = historical_red_folder(
            str(bars.index[0].date()), str(bars.index[-1].date()))
    bars.index = bars.index.tz_localize(None)
    print(f"got {len(bars):,} bars. running…  (Ctrl-C to stop early)")

    trades = run_backtest(bars, news_times)
    report(trades, bars)
