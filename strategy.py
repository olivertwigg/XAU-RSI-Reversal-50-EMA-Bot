"""
XAUUSD mean-reversion strategy — shared by live bot and backtester.

Rules:
  SHORT: 5-min RSI(14) crosses ABOVE 63  -> SL = entry + $8, TP = entry - $8
  LONG:  5-min RSI(14) crosses BELOW 37  -> SL = entry - $8, TP = entry + $8
  No entries within +/-15 min of red-folder (high impact) news.
  After a losing trade: 40-min cooldown (no new entries).
  Max 2 losses per day -> done trading until next day.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from typing import Optional
import pandas as pd

# ---------- parameters ----------
RSI_PERIOD = 14
RSI_SHORT_LEVEL = 63.0
RSI_LONG_LEVEL = 37.0
SL_DOLLARS = 10.0        # fixed stop distance
# TP is no longer a fixed price: shorts exit when RSI reaches RSI_LONG_LEVEL (37),
# longs exit when RSI reaches RSI_SHORT_LEVEL (63), at that bar's close.
COOLDOWN_MIN = 40        # minutes after a loss
MAX_LOSSES_PER_DAY = 2
NEWS_BUFFER_MIN = 15     # minutes before/after red folder news
TREND_EMA_PERIOD = 50    # daily EMA for HTF bias filter
TREND_FILTER = True      # set False to disable and trade both directions always
BLOCKED_HOURS = {1, 2, 3, 4, 5, 21, 22, 23}   # UTC hours: no new entries


def rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


@dataclass
class Signal:
    direction: str          # "long" or "short"
    time: datetime
    entry: float
    sl: float
    rsi_value: float

    def __str__(self):
        arrow = "🟢 LONG" if self.direction == "long" else "🔴 SHORT"
        tp_rule = (f"TP: exit when RSI <= {RSI_LONG_LEVEL:.0f}" if self.direction == "short"
                   else f"TP: exit when RSI >= {RSI_SHORT_LEVEL:.0f}")
        return (f"{arrow} XAUUSD @ {self.entry:.2f}\n"
                f"SL: {self.sl:.2f}  |  {tp_rule}\n"
                f"RSI(14): {self.rsi_value:.1f}\n"
                f"{self.time:%Y-%m-%d %H:%M} UTC")


def resolve_bar(sig: Signal, high: float, low: float,
                close: float, cur_rsi: float):
    """
    Shared exit logic for one closed 5-min bar while a trade is open.
    Returns (outcome, exit_price) where outcome is "sl", "rsi", or None.
    SL is checked first (intrabar touch beats close-based RSI exit —
    conservative when both occur in the same bar).
    """
    if sig.direction == "long":
        if low <= sig.sl:
            return "sl", sig.sl
        if cur_rsi >= RSI_SHORT_LEVEL:
            return "rsi", close
    else:
        if high >= sig.sl:
            return "sl", sig.sl
        if cur_rsi <= RSI_LONG_LEVEL:
            return "rsi", close
    return None, None


@dataclass
class StrategyState:
    """Tracks cooldown / daily loss limits. One instance for live, one per backtest."""
    cooldown_until: Optional[datetime] = None
    losses_today: int = 0
    current_day: Optional[date] = None
    in_position: bool = False

    def new_bar_day(self, ts: datetime):
        d = ts.date()
        if d != self.current_day:
            self.current_day = d
            self.losses_today = 0

    def can_enter(self, ts: datetime) -> bool:
        self.new_bar_day(ts)
        if self.in_position:
            return False
        if self.losses_today >= MAX_LOSSES_PER_DAY:
            return False
        if self.cooldown_until and ts < self.cooldown_until:
            return False
        return True

    def record_result(self, ts: datetime, won: bool):
        self.in_position = False
        self.new_bar_day(ts)
        if not won:
            self.losses_today += 1
            self.cooldown_until = ts + timedelta(minutes=COOLDOWN_MIN)


# FOMC rate decisions: always Wednesday, 19:00 or 20:00 UTC
# Block 2 hours before (17:00/18:00) until 30 min after (19:30/20:30)
FOMC_HOURS = {19, 20}          # UTC hour of the rate decision
FOMC_PRE_MIN  = 120            # block this many minutes before
FOMC_POST_MIN = 30             # block this many minutes after


def is_fomc_window(ts: datetime) -> bool:
    """True if ts falls within the FOMC blackout on a Wednesday."""
    if ts.weekday() != 2:      # not Wednesday
        return False
    for decision_hour in FOMC_HOURS:
        decision = ts.replace(hour=decision_hour, minute=0, second=0, microsecond=0)
        pre  = decision - timedelta(minutes=FOMC_PRE_MIN)
        post = decision + timedelta(minutes=FOMC_POST_MIN)
        if pre <= ts <= post:
            return True
    return False


def near_news(ts: datetime, news_times: list[datetime],
              buffer_min: int = NEWS_BUFFER_MIN) -> bool:
    buf = timedelta(minutes=buffer_min)
    return any(abs(ts - n) <= buf for n in news_times)


def trend_bias(daily_close: pd.Series, period: int = TREND_EMA_PERIOD) -> Optional[str]:
    """
    HTF bias from daily closes: price above daily EMA -> "long" bias
    (only longs allowed), below -> "short" bias. Needs `period` daily bars.
    Pass ONLY fully closed daily bars (exclude today) to avoid lookahead.
    """
    if len(daily_close) < period:
        return None
    ema = daily_close.ewm(span=period, adjust=False).mean()
    return "long" if daily_close.iloc[-1] > ema.iloc[-1] else "short"


def check_signal(bars: pd.DataFrame, state: StrategyState,
                 news_times: list[datetime],
                 bias: Optional[str] = None) -> Optional[Signal]:
    """
    bars: DataFrame indexed by UTC datetime with columns open/high/low/close,
          in ascending time order. The LAST row is the most recently CLOSED 5-min bar.
    Returns a Signal on RSI cross, else None.
    """
    if len(bars) < RSI_PERIOD + 2:
        return None

    r = rsi(bars["close"])
    prev_rsi, cur_rsi = r.iloc[-2], r.iloc[-1]
    ts = bars.index[-1].to_pydatetime()
    price = float(bars["close"].iloc[-1])

    if not state.can_enter(ts):
        return None
    if ts.hour in BLOCKED_HOURS:
        return None
    if is_fomc_window(ts):
        return None
    if near_news(ts, news_times):
        return None

    # cross ABOVE 63 -> short
    if prev_rsi <= RSI_SHORT_LEVEL < cur_rsi:
        if TREND_FILTER and bias == "long":
            return None
        return Signal("short", ts, price, price + SL_DOLLARS, cur_rsi)
    # cross BELOW 37 -> long
    if prev_rsi >= RSI_LONG_LEVEL > cur_rsi:
        if TREND_FILTER and bias == "short":
            return None
        return Signal("long", ts, price, price - SL_DOLLARS, cur_rsi)
    return None
