"""
Market-regime detection for Gold Monitor.

The event calendar (events.py) covers moves you can see coming. This module
covers the rest: it detects that *something happened* without needing to know
what. Two independent checks, both computed from data the bot already has —
no news feed, no new API, no key.

  1. VOLATILITY REGIME — is the price moving much harder than it normally
     does? A jump in realized volatility is the fingerprint of news landing,
     whatever the news was.

  2. DRIVER DIVERGENCE — gold usually falls when the dollar and yields rise.
     When it rises against BOTH at once, the move is not a rates story; that
     pattern is the signature of a safe-haven bid (war, sanctions, a political
     shock). signals.py already fetches DXY and US10Y, so this is free.

Neither predicts direction. #1 says "this move is unusually large"; #2 says
"this move is not explained by the usual drivers". Both are descriptions of
what already happened, and both are framed that way in the messages.
"""

from __future__ import annotations

import i18n

# ── Volatility regime ───────────────────────────────────────────────────────

SHORT_WINDOW = 6      # hours treated as "right now"
BASELINE_WINDOW = 168  # 7 days of hourly points for "normal"
MIN_BASELINE = 48      # below this the baseline is too thin to trust

# Ratio of recent volatility to baseline volatility.
CALM_BELOW = 0.6
ELEVATED_ABOVE = 1.8
EXTREME_ABOVE = 3.0

# Gold's hourly moves can round to exactly flat; a floor keeps the ratio finite
# instead of dividing by ~0 and reporting a fake spike.
VOL_FLOOR = 0.005  # percent

# |last move| / baseline sigma, above which a single bar is called a shock.
SHOCK_SIGMA = 3.0


def returns(prices: list) -> list:
    """Percent change between consecutive prices."""
    out = []
    for prev, cur in zip(prices, prices[1:]):
        if prev:
            out.append((cur - prev) / prev * 100.0)
    return out


def _stdev(values: list) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return (sum((v - mean) ** 2 for v in values) / (n - 1)) ** 0.5


def vol_regime(history: list) -> dict:
    """Compare recent realized volatility against its own recent baseline.

    The baseline deliberately EXCLUDES the recent window. Including it would
    let a spike inflate the very baseline it is being measured against, which
    is how naive versions of this end up never firing.

    Returns {"available": False, ...} when there is not enough history — the
    caller shows nothing rather than a misleading number.
    """
    prices = [h["thb_gram"] for h in history if isinstance(h, dict) and "thb_gram" in h]
    rets = returns(prices)

    if len(rets) < MIN_BASELINE + SHORT_WINDOW:
        return {"available": False, "reason": "not enough history",
                "have": len(rets),
                "need": MIN_BASELINE + SHORT_WINDOW}

    recent = rets[-SHORT_WINDOW:]
    baseline = rets[-(BASELINE_WINDOW + SHORT_WINDOW):-SHORT_WINDOW]

    recent_vol = _stdev(recent)
    baseline_vol = max(_stdev(baseline), VOL_FLOOR)
    ratio = recent_vol / baseline_vol

    if ratio >= EXTREME_ABOVE:
        level = "extreme"
    elif ratio >= ELEVATED_ABOVE:
        level = "elevated"
    elif ratio <= CALM_BELOW:
        level = "calm"
    else:
        level = "normal"

    last_move = rets[-1] if rets else 0.0
    sigma = abs(last_move) / baseline_vol

    return {
        "available": True,
        "recent_vol": round(recent_vol, 4),
        "baseline_vol": round(baseline_vol, 4),
        "ratio": round(ratio, 2),
        "level": level,
        "last_move": round(last_move, 3),
        "sigma": round(sigma, 1),
        "shock": sigma >= SHOCK_SIGMA,
    }


def is_unusual(regime: dict) -> bool:
    """True when the regime is worth telling the user about."""
    return bool(regime.get("available")) and (
        regime.get("level") in ("elevated", "extreme") or regime.get("shock"))


# ── Driver divergence ───────────────────────────────────────────────────────

# Deadbands, to keep noise from firing this.
#
# NOTE the yield one is NOT the same quantity as signals.gold_bias's DB_Y.
# That module compares the yield's PERCENT change; this one compares its move
# in PERCENTAGE POINTS, which is the unit the bond market actually quotes and
# the only one where a threshold is interpretable. For a 10Y near 4.5%, a
# 0.10 percent change is ~0.005pp — nothing. 0.03pp is 3 basis points: a
# modest but real daily move (the 10Y's daily sigma is roughly 5–7bp).
DB_GOLD = 0.15    # percent
DB_DOLLAR = 0.05  # percent
DB_YIELD = 0.03   # percentage points


def divergence(gold_change_pct: float | None, macro: dict | None) -> str | None:
    """Is gold moving AGAINST its usual drivers?

    `gold_change_pct` should be gold's ~24h change, because the macro series
    are daily closes — comparing an intraday gold move against a daily DXY
    change would be measuring two different things.

    Returns an i18n key, or None when nothing notable is happening.
    """
    if gold_change_pct is None or not macro:
        return None

    dxy = (macro.get("dxy") or {}).get("change_pct")
    # Yields move in percentage points, so use the absolute delta, not percent.
    yld = (macro.get("us10y") or {}).get("change_abs")
    if dxy is None and yld is None:
        return None

    gold_up = gold_change_pct > DB_GOLD
    gold_down = gold_change_pct < -DB_GOLD
    dollar_up = dxy is not None and dxy > DB_DOLLAR
    dollar_down = dxy is not None and dxy < -DB_DOLLAR
    yields_up = yld is not None and yld > DB_YIELD
    yields_down = yld is not None and yld < -DB_YIELD

    # Gold climbing while BOTH headwinds strengthen: not a rates story.
    if gold_up and dollar_up and yields_up:
        return "regime.div.safe_haven"
    # Gold falling while both tailwinds strengthen: usually forced selling.
    if gold_down and dollar_down and yields_down:
        return "regime.div.liquidation"
    return None


# Display caps. Against a very quiet baseline the honest arithmetic can produce
# "30x normal, 30 sigma" — true, but it reads like a broken gauge, and returns
# are fat-tailed enough that the precise multiple past a point is meaningless.
# The raw values stay in the dict for logic and logging; only the message is
# clamped.
RATIO_DISPLAY_CAP = 15.0
SIGMA_DISPLAY_CAP = 10.0


def display_ratio(ratio: float) -> str:
    return f"{RATIO_DISPLAY_CAP:.0f}+" if ratio > RATIO_DISPLAY_CAP else f"{ratio:.2g}"


def display_sigma(sigma: float) -> str:
    return f"{SIGMA_DISPLAY_CAP:.0f}+" if sigma > SIGMA_DISPLAY_CAP else f"{sigma:.1f}"


def format_block(regime: dict, div_key: str | None, lang: str | None = None) -> str:
    """Message block for an unusual regime. "" when there is nothing to say."""
    lines = []
    if is_unusual(regime):
        ratio = display_ratio(regime["ratio"])
        if regime["level"] == "extreme":
            lines.append(i18n.t("regime.vol_extreme", lang, ratio=ratio))
        elif regime["level"] == "elevated":
            lines.append(i18n.t("regime.vol_elevated", lang, ratio=ratio))
        if regime.get("shock"):
            lines.append(i18n.t("regime.shock", lang,
                                sigma=display_sigma(regime["sigma"]),
                                move=regime["last_move"]))
    if div_key:
        lines.append(i18n.t(div_key, lang))
    if not lines:
        return ""
    return "\n" + "\n".join(lines)
