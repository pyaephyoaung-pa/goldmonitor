"""
Shared formatting helpers for Gold Monitor.

Previously duplicated across gold_monitor.py, bot_commands.py and api/webhook.py.
Single source of truth now lives here.
"""

# 1 บาททอง (1 baht of gold) = 15.244 grams
BAHT_WEIGHT_GRAMS = 15.244

# Thai gold purity constants
PURITY_PURE = 99.99
PURITY_JEWELRY = 96.50


def fmt(n) -> str:
    """Format a THB amount: 12345.6 -> '฿12,346'."""
    return f"฿{n:,.0f}"


def fmt_usd(n) -> str:
    """Format a USD amount: 3352.409 -> '$3,352.41'.

    Two decimals, unlike THB: a dollar move that matters to gold is often
    smaller than a whole dollar per ounce.
    """
    return f"${n:,.2f}"


def fmt_target(price, unit: str) -> str:
    """Render a level-alert target in the unit it was set in.

    /alert takes USD/oz. Records written before that switch carry no unit and
    are still THB/gram — see storage.alert_unit.
    """
    return f"{fmt_usd(price)}/oz" if unit == "usd" else f"{fmt(price)}/g"


def usd_oz_suffix(usd_oz) -> str:
    """Format spot as ' | $3,352.41/oz', to sit next to a THB/gram figure.

    Every place that shows a live THB/gram price also shows the USD/oz price it
    was derived from, so a move can be read as gold moving vs the baht moving.
    Returns '' when spot is unknown (older history entries have no `usd_oz`),
    which lets callers append it unconditionally.
    """
    return f" | {fmt_usd(usd_oz)}/oz" if usd_oz else ""


def gold_breakdown(thb_gram_9999: float) -> dict:
    """Calculate gold prices for 99.99% (pure) and 96.50% (jewelry) purity.

    Args:
        thb_gram_9999: price of 1 gram of 99.99% gold in THB.
    Returns:
        dict with per-gram and per-baht-weight prices for both purities.
    """
    baht_9999 = round(thb_gram_9999 * BAHT_WEIGHT_GRAMS, 2)
    gram_9650 = round(thb_gram_9999 * (PURITY_JEWELRY / PURITY_PURE), 2)
    baht_9650 = round(gram_9650 * BAHT_WEIGHT_GRAMS, 2)
    return {
        "gram_9999": thb_gram_9999,
        "baht_9999": baht_9999,
        "gram_9650": gram_9650,
        "baht_9650": baht_9650,
    }
