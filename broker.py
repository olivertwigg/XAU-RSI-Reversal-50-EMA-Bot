"""
OANDA v20 execution layer for the XAUUSD bot.

- Market orders with the SL attached server-side (broker enforces your stop
  even if this bot/Mac dies mid-trade).
- RSI exits close the position at market.
- EXECUTE flag + DRY_RUN mode + kill-switch file for safety.

Setup: create an OANDA account -> Manage API Access -> generate token.
START WITH A PRACTICE ACCOUNT (api-fxpractice). Only change OANDA_ENV to
"live" after weeks of verified demo behaviour.
"""

import requests
from config import OANDA_TOKEN, OANDA_ACCOUNT_ID, OANDA_ENV, UNITS
import os

HOSTS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}
INSTRUMENT = "XAU_USD"
KILL_SWITCH = "STOP_TRADING"   # create this file in the bot folder to halt entries


def _headers():
    return {"Authorization": f"Bearer {OANDA_TOKEN}",
            "Content-Type": "application/json"}


def _base():
    return HOSTS[OANDA_ENV]


def kill_switch_on() -> bool:
    return os.path.exists(KILL_SWITCH)


def open_position(direction: str, sl_price: float) -> dict:
    """Market order with stop loss attached. Returns OANDA response."""
    units = UNITS if direction == "long" else -UNITS
    order = {
        "order": {
            "type": "MARKET",
            "instrument": INSTRUMENT,
            "units": str(units),
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
            "stopLossOnFill": {"price": f"{sl_price:.2f}"},
        }
    }
    r = requests.post(f"{_base()}/v3/accounts/{OANDA_ACCOUNT_ID}/orders",
                      json=order, headers=_headers(), timeout=20)
    r.raise_for_status()
    return r.json()


def close_position(direction: str) -> dict:
    """Close the whole XAU_USD position on the given side at market."""
    body = ({"longUnits": "ALL"} if direction == "long"
            else {"shortUnits": "ALL"})
    r = requests.put(
        f"{_base()}/v3/accounts/{OANDA_ACCOUNT_ID}/positions/{INSTRUMENT}/close",
        json=body, headers=_headers(), timeout=20)
    r.raise_for_status()
    return r.json()


def position_open() -> bool:
    """True if any XAU_USD position is currently open on the account."""
    r = requests.get(
        f"{_base()}/v3/accounts/{OANDA_ACCOUNT_ID}/openPositions",
        headers=_headers(), timeout=20)
    r.raise_for_status()
    return any(p["instrument"] == INSTRUMENT
               for p in r.json().get("positions", []))
