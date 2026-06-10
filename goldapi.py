"""
Gold price + FX fetching for Gold Monitor.

Single source of truth: previously this logic was copy-pasted (with subtle
differences) into gold_monitor.py, bot_commands.py and api/webhook.py.

Reliability notes:
  * Spot gold (XAU/USD): primary = Twelve Data (needs key), fallback = gold-api.com
    (free, no key). The old metals.live fallback was removed — that API has been
    shut down, so it silently failed and left the bot single-sourced.
  * FX (USD->THB): primary = exchangerate-api.com, fallback = open.er-api.com.

NOTE: the fallback endpoints could not be reached from the build sandbox
(network allowlist), so they are exercised by mocked unit tests. Confirm them
once in the live GitHub Actions environment.
"""

from __future__ import annotations

import os
import time

import requests

TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")

# Troy ounce -> gram
GRAMS_PER_TROY_OZ = 31.1035


# ── Spot gold (XAU/USD) ─────────────────────────────────────────

def _spot_from_twelve_data() -> float | None:
    if not TWELVE_DATA_API_KEY:
        return None
    r = requests.get(
        "https://api.twelvedata.com/price",
        params={"symbol": "XAU/USD", "apikey": TWELVE_DATA_API_KEY},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    # Twelve Data returns {"code": 429, ...} on rate-limit instead of raising.
    if "price" not in data:
        raise ValueError(f"Twelve Data response had no price: {data}")
    return float(data["price"])


def _spot_from_gold_api() -> float | None:
    """Free, no-key fallback. Returns USD/oz. Endpoint: api.gold-api.com."""
    r = requests.get("https://api.gold-api.com/price/XAU", timeout=10)
    r.raise_for_status()
    data = r.json()
    if "price" not in data:
        raise ValueError(f"gold-api.com response had no price: {data}")
    return float(data["price"])


_SPOT_SOURCES = (
    ("twelve_data", _spot_from_twelve_data),
    ("gold-api.com", _spot_from_gold_api),
)


def fetch_spot_usd() -> float | None:
    """Fetch spot gold in USD/oz, trying each source in order."""
    last_err = None
    for name, source in _SPOT_SOURCES:
        try:
            val = source()
            if val:
                return val
        except Exception as e:  # noqa: BLE001 - try next source
            last_err = e
            print(f"[goldapi] spot source '{name}' failed: {e}")
    print(f"[goldapi] all spot sources failed (last: {last_err})")
    return None


# ── FX (USD -> THB) ─────────────────────────────────────────────

def _fx_from_exchangerate_api() -> float | None:
    r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
    r.raise_for_status()
    return float(r.json()["rates"]["THB"])


def _fx_from_open_er_api() -> float | None:
    """Free fallback. Endpoint: open.er-api.com."""
    r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10)
    r.raise_for_status()
    return float(r.json()["rates"]["THB"])


_FX_SOURCES = (
    ("exchangerate-api", _fx_from_exchangerate_api),
    ("open.er-api", _fx_from_open_er_api),
)


def fetch_thb_rate() -> float | None:
    """Fetch USD->THB rate, trying each source in order."""
    last_err = None
    for name, source in _FX_SOURCES:
        try:
            val = source()
            if val:
                return val
        except Exception as e:  # noqa: BLE001 - try next source
            last_err = e
            print(f"[goldapi] FX source '{name}' failed: {e}")
    print(f"[goldapi] all FX sources failed (last: {last_err})")
    return None


# ── Combined ────────────────────────────────────────────────────

def get_gold_price(retries: int = 2) -> tuple:
    """Fetch gold price with retry + multi-source fallback.

    Returns (thb_gram, usd_oz, thb_rate) or (None, None, None).
    thb_gram is the price of 1 gram of 99.99% gold derived from spot + FX.
    """
    for attempt in range(retries + 1):
        usd_oz = fetch_spot_usd()
        thb_rate = fetch_thb_rate() if usd_oz is not None else None

        if usd_oz is not None and thb_rate is not None:
            thb_gram = round((usd_oz * thb_rate) / GRAMS_PER_TROY_OZ, 2)
            return thb_gram, round(usd_oz, 2), round(thb_rate, 2)

        if attempt < retries:
            print(f"[goldapi] retry {attempt + 1}/{retries} after fetch failure")
            time.sleep(10)

    return None, None, None
