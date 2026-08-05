"""
Live 24/7 signal loop.

Polls 5-min XAUUSD bars, checks the strategy on each newly closed bar,
sends entries/exits to Telegram, executes via OANDA if configured,
and sends a weekly recap every Sunday at 22:00 UTC.

Weekly trade log persists to weekly_trades.json so restarts don't
lose the week's history.
"""

import json
import time
import traceback
from datetime import datetime, timezone
import requests

from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, EXECUTE, DRY_RUN
from data import fetch_bars, fetch_daily
from news import red_folder_times
import broker
from strategy import (StrategyState, check_signal, Signal, trend_bias,
                      resolve_bar, rsi)

POLL_SECONDS = 20
WEEKLY_LOG   = "weekly_trades.json"


# ── persistence ────────────────────────────────────────────────────────────────

def _load_weekly() -> tuple[list[dict], int | None]:
    """Load persisted weekly trades and the ISO week they belong to."""
    try:
        with open(WEEKLY_LOG) as f:
            data = json.load(f)
        # convert entry/exit times back to datetime
        trades = []
        for t in data.get("trades", []):
            t["entry_time"] = datetime.fromisoformat(t["entry_time"])
            t["exit_time"]  = datetime.fromisoformat(t["exit_time"])
            trades.append(t)
        return trades, data.get("week")
    except Exception:
        return [], None


def _save_weekly(trades: list[dict], week: int | None):
    try:
        serialisable = []
        for t in trades:
            row = dict(t)
            row["entry_time"] = t["entry_time"].isoformat()
            row["exit_time"]  = t["exit_time"].isoformat()
            serialisable.append(row)
        with open(WEEKLY_LOG, "w") as f:
            json.dump({"week": week, "trades": serialisable}, f)
    except Exception as e:
        print(f"[weekly] save failed: {e}")


# ── telegram ───────────────────────────────────────────────────────────────────

def tg_send(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
                      timeout=15)
    except Exception as e:
        print(f"[tg] send failed: {e}")


# ── weekly recap ───────────────────────────────────────────────────────────────

def weekly_recap(trades: list[dict]) -> str:
    if not trades:
        return (
            "📊 Weekly Recap\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "No trades this week.\n"
            "Bot was running — just no RSI crosses hit the levels."
        )

    wins      = [t for t in trades if t["pnl"] >= 0]
    losses    = [t for t in trades if t["pnl"] < 0]
    total_pnl = sum(t["pnl"] for t in trades)
    win_rate  = len(wins) / len(trades) * 100
    avg_win   = sum(t["pnl"] for t in wins)   / len(wins)   if wins   else 0
    avg_loss  = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
    best      = max(trades, key=lambda t: t["pnl"])
    worst     = min(trades, key=lambda t: t["pnl"])
    longs     = [t for t in trades if t["direction"] == "long"]
    shorts    = [t for t in trades if t["direction"] == "short"]
    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"

    lines = [
        "📊 Weekly Recap",
        "━━━━━━━━━━━━━━━━━━━━",
        f"Trades:    {len(trades)}  ({len(wins)}W / {len(losses)}L)",
        f"Win rate:  {win_rate:.0f}%",
        f"Net P&L:   {pnl_emoji} {total_pnl:+.2f} $/oz",
        f"Avg win:   +{avg_win:.2f} $/oz",
        f"Avg loss:  {avg_loss:.2f} $/oz",
        f"Best:      +{best['pnl']:.2f}  ({best['direction'].upper()} @ {best['entry']:.2f})",
        f"Worst:     {worst['pnl']:.2f}  ({worst['direction'].upper()} @ {worst['entry']:.2f})",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    if longs:
        lw = sum(1 for t in longs if t["pnl"] >= 0) / len(longs) * 100
        lines.append(f"Longs:  {len(longs)} trades  {lw:.0f}% win  "
                     f"{sum(t['pnl'] for t in longs):+.2f} $/oz")
    if shorts:
        sw = sum(1 for t in shorts if t["pnl"] >= 0) / len(shorts) * 100
        lines.append(f"Shorts: {len(shorts)} trades  {sw:.0f}% win  "
                     f"{sum(t['pnl'] for t in shorts):+.2f} $/oz")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("Trades this week:")
    for t in trades:
        emoji = "✅" if t["pnl"] >= 0 else "❌"
        lines.append(
            f"{emoji} {t['direction'].upper():5s} "
            f"{t['entry_time']:%a %d %b %H:%M}  "
            f"entry {t['entry']:.2f}  "
            f"P&L {t['pnl']:+.2f}"
        )
    return "\n".join(lines)


# ── main loop ──────────────────────────────────────────────────────────────────

def main():
    state = StrategyState()
    open_trade: Signal | None = None
    last_bar_time = None
    bias          = None
    bias_checked  = 0.0

    # load persisted weekly log
    weekly_trades, recap_sent_week = _load_weekly()
    print(f"[weekly] loaded {len(weekly_trades)} trade(s) from this week's log")

    tg_send("🤖 XAUUSD signal bot online.")
    print("Running. Ctrl-C to stop.")

    while True:
        try:
            bars = fetch_bars(limit=100)
            latest = bars.index[-1]
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            bars.index = bars.index.tz_localize(None)

            # ── weekly recap: Sunday 22:00 UTC ───────────────────────────────
            current_week = now.isocalendar()[1]
            if (now.weekday() == 4 and now.hour == 22
                    and recap_sent_week != current_week):
                tg_send(weekly_recap(weekly_trades))
                weekly_trades   = []
                recap_sent_week = current_week
                _save_weekly(weekly_trades, recap_sent_week)
                print(f"[recap] weekly recap sent (week {current_week})")

            # ── new week detection: reset if we've rolled past Sunday ────────
            # handles the case where bot was off during Sunday 22:00
            saved_week = recap_sent_week or current_week
            if current_week != saved_week and now.weekday() != 6:
                print(f"[weekly] new week detected — resetting log")
                weekly_trades   = []
                recap_sent_week = current_week
                _save_weekly(weekly_trades, recap_sent_week)

            # ── weekend force-close: Friday 21:45 UTC ───────────────────────
            # closes any open position before the weekend gap; blocks new
            # entries after 21:00 UTC Friday (weekday 4)
            is_friday = now.weekday() == 4
            past_cutoff = now.hour == 21 and now.minute >= 45
            if is_friday and past_cutoff and open_trade is not None:
                # force close at current price
                cur_price = float(bars["close"].iloc[-1])
                pnl = (cur_price - open_trade.entry
                       if open_trade.direction == "long"
                       else open_trade.entry - cur_price)
                won = pnl >= 0
                state.record_result(now, won)
                weekly_trades.append({
                    "direction":  open_trade.direction,
                    "entry":      open_trade.entry,
                    "entry_time": open_trade.time,
                    "exit":       cur_price,
                    "exit_time":  now,
                    "exit_type":  "weekend_close",
                    "pnl":        pnl,
                })
                _save_weekly(weekly_trades, recap_sent_week)
                if EXECUTE and not DRY_RUN:
                    try:
                        if broker.position_open():
                            broker.close_position(open_trade.direction)
                    except Exception as e:
                        tg_send(f"⚠️ WEEKEND CLOSE FAILED: {e} — CLOSE MANUALLY NOW")
                tg_send(
                    f"🌙 Weekend close — {open_trade.direction.upper()} "
                    f"from {open_trade.entry:.2f}\n"
                    f"Closed @ {cur_price:.2f}  P&L: {pnl:+.2f} $/oz\n"
                    f"(position closed before weekend gap risk)"
                )
                open_trade = None
                print("[weekend] force-closed open position before weekend")

            # ── resolve open trade ───────────────────────────────────────────
            if open_trade is not None:
                cur_rsi = float(rsi(bars["close"]).iloc[-1])
                outcome, exit_px = resolve_bar(open_trade,
                                               bars["high"].iloc[-1],
                                               bars["low"].iloc[-1],
                                               float(bars["close"].iloc[-1]),
                                               cur_rsi)
                if outcome:
                    pnl = (exit_px - open_trade.entry
                           if open_trade.direction == "long"
                           else open_trade.entry - exit_px)
                    won = pnl >= 0
                    state.record_result(now, won)

                    # persist to weekly log
                    weekly_trades.append({
                        "direction":  open_trade.direction,
                        "entry":      open_trade.entry,
                        "entry_time": open_trade.time,
                        "exit":       exit_px,
                        "exit_time":  now,
                        "exit_type":  outcome,
                        "pnl":        pnl,
                    })
                    _save_weekly(weekly_trades, recap_sent_week)

                    emoji = ("✅ RSI target" if outcome == "rsi" and won else
                             "🟡 RSI exit (red)" if outcome == "rsi" else "❌ SL hit")
                    extra = f"\nP&L: {pnl:+.2f} $/oz  (exit {exit_px:.2f})"
                    if not won:
                        extra += (f"\nCooldown until "
                                  f"{state.cooldown_until:%H:%M} UTC"
                                  f" | losses today: {state.losses_today}/2")
                        if state.losses_today >= 2:
                            extra += "\n🛑 Daily loss limit reached — done for today."
                    if EXECUTE and outcome == "rsi" and not DRY_RUN:
                        try:
                            if broker.position_open():
                                broker.close_position(open_trade.direction)
                                extra += "\n🤝 position closed at broker"
                        except Exception as e:
                            extra += f"\n⚠️ CLOSE FAILED: {e} — CLOSE MANUALLY NOW"
                    elif EXECUTE and outcome == "rsi" and DRY_RUN:
                        extra += "\n🧪 DRY RUN — would close position"
                    tg_send(f"{emoji} — {open_trade.direction.upper()} "
                            f"from {open_trade.entry:.2f}{extra}")
                    open_trade = None

            # ── refresh HTF bias hourly ──────────────────────────────────────
            if time.time() - bias_checked > 3600:
                try:
                    daily = fetch_daily(limit=80)
                    new_bias = trend_bias(daily["close"].iloc[:-1])
                    if new_bias != bias:
                        tg_send(f"📊 HTF bias now: {new_bias or 'none'} "
                                f"(daily EMA50 filter)")
                    bias = new_bias
                except Exception as e:
                    print(f"[bias] refresh failed: {e}")
                bias_checked = time.time()

            # ── check for new signal ─────────────────────────────────────────
            if latest != last_bar_time:
                last_bar_time = latest
                # no new entries Friday after 21:00 UTC
                if is_friday and now.hour >= 19:
                    sig = None
                else:
                    sig = check_signal(bars, state, red_folder_times(), bias)
                if sig:
                    state.in_position = True
                    open_trade = sig
                    exec_note = ""
                    if EXECUTE:
                        if broker.kill_switch_on():
                            exec_note = "\n⛔ kill switch ON — NOT executed"
                        elif DRY_RUN:
                            exec_note = "\n🧪 DRY RUN — would place order (not sent)"
                        else:
                            try:
                                broker.open_position(sig.direction, sig.sl)
                                exec_note = "\n🤝 order placed (SL attached at broker)"
                            except Exception as e:
                                exec_note = f"\n⚠️ ORDER FAILED: {e} — treat as signal-only"
                    tg_send(str(sig) + exec_note)
                    print(f"signal: {sig.direction} @ {sig.entry}{exec_note}")

        except KeyboardInterrupt:
            tg_send("🤖 bot stopped.")
            raise
        except Exception:
            traceback.print_exc()

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
