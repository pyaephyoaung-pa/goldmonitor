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
