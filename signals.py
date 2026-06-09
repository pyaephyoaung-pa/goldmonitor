"""
Macro & fear-factor signals for Gold Monitor (Tier 1 — context only).

Gold is driven mostly by external forces, so this module surfaces the three
that matter most, as *context* shown in the daily messages (not as a forecast):

  • DXY   — US Dollar Index (gold trades inversely to the dollar)
  • US10Y — US 10-year Treasury yield proxy (rising yields pressure gold)
  • VIX   — equity volatility, the classic "fear gauge"

Data source: Stooq daily CSV — free, no API key:
    https://stooq.com/q/d/l/?s=<symbol>&i=d

NOTE: Stooq symbols and the network are not reachable from the build sandbox
(allowlist), so this module is exercised by mocked unit tests. The symbols below
are the most likely Stooq tickers; if a metric shows as unavailable in a live
run, adjust SYMBOLS to match Stooq's catalogue. Everything degrades gracefully:
a failed fetch simply omits that metric (and the block) rather than erroring.
"""

import requests

# Stooq tickers. Tweak here if Stooq renames one.
SYMBOLS = {
    "dxy": "^dxy",    # US Dollar Index
    "us10y": "^tnx",  # US 10Y yield index
    "vix": "^vix",    # CBOE Volatility Index
}


def _fetch_stooq_closes(symbol: str) -> list:
    """Return chronological list of daily closes for a Stooq symbol ([] on error)."""
    try:
        r = requests.get(
            f"https://stooq.com/q/d/l/?s={symbol}&i=d", timeout=10
        )
        r.raise_for_status()
        text = r.text.strip()
        # Expect CSV: Date,Open,High,Low,Close,Volume
        if not text or "Close" not in text.splitlines()[0]:
            return []
        closes = []
        for line in text.splitlines()[1:]:
            cols = line.split(",")
            if len(cols) < 5:
                continue
            raw = cols[4].strip()
            if raw in ("", "N/D"):
                continue
            try:
                closes.append(float(raw))
            except ValueError:
                continue
        return closes
    except Exception as e:  # noqa: BLE001
        print(f"[signals] stooq fetch failed for {symbol}: {e}")
        return []


def fetch_macro() -> dict:
    """Fetch latest value + daily % change for each macro symbol.

    Returns {key: {"value": float, "change_pct": float|None}} for whatever
    succeeded (missing/failed symbols are simply absent).
    """
    out = {}
    for key, sym in SYMBOLS.items():
        closes = _fetch_stooq_closes(sym)
        if not closes:
            continue
        latest = round(closes[-1], 2)
        change_pct = None
        if len(closes) >= 2 and closes[-2]:
            change_pct = round((closes[-1] - closes[-2]) / closes[-2] * 100, 2)
        out[key] = {"value": latest, "change_pct": change_pct}
    return out


def _clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def fear_score(macro: dict) -> float | None:
    """Composite 0–100 fear score (higher = more fear, gold-supportive).

    Driven by the VIX level (12 = calm → ~0, 35 = stressed → ~100) and nudged by
    its daily move. Returns None if VIX is unavailable.
    """
    vix = macro.get("vix", {})
    val = vix.get("value")
    if val is None:
        return None
    level = _clamp((val - 12) / (35 - 12) * 100)
    chg = vix.get("change_pct") or 0.0
    return round(_clamp(level + chg * 0.5), 1)


def fear_label(score: float | None) -> str:
    if score is None:
        return "n/a"
    if score < 25:
        return "Calm"
    if score < 50:
        return "Normal"
    if score < 75:
        return "Elevated"
    return "High fear"


def gold_bias(macro: dict) -> str | None:
    """Qualitative read of dollar + yield direction as a gold tailwind/headwind."""
    dxy = macro.get("dxy", {}).get("change_pct")
    y = macro.get("us10y", {}).get("change_pct")
    if dxy is None and y is None:
        return None

    DB_D, DB_Y = 0.05, 0.10  # deadbands to ignore noise
    dollar_down = dxy is not None and dxy < -DB_D
    dollar_up = dxy is not None and dxy > DB_D
    yields_down = y is not None and y < -DB_Y
    yields_up = y is not None and y > DB_Y

    if (dollar_down or yields_down) and not (dollar_up or yields_up):
        return "tailwind (dollar/yields easing)"
    if (dollar_up or yields_up) and not (dollar_down or yields_down):
        return "headwind (dollar/yields rising)"
    return "mixed"


def _arrow(chg):
    if chg is None:
        return "➡️"
    return "📈" if chg > 0 else "📉" if chg < 0 else "➡️"


def _line(emoji, label, metric):
    val = metric.get("value")
    chg = metric.get("change_pct")
    chg_str = f" ({chg:+.2f}%)" if chg is not None else ""
    return f"  {emoji} {label}: {val}{chg_str} {_arrow(chg)}"


def format_macro_block(macro: dict | None = None) -> str:
    """Build the 'Macro & Fear' message block. Fetches if `macro` is None.

    Returns "" when no data is available so the caller can append it
    unconditionally without breaking the message.
    """
    if macro is None:
        try:
            macro = fetch_macro()
        except Exception as e:  # noqa: BLE001
            print(f"[signals] fetch_macro failed: {e}")
            macro = {}
    if not macro:
        return ""

    lines = ["🌍 <b>Macro & Fear</b>"]
    if "dxy" in macro:
        lines.append(_line("💵", "DXY", macro["dxy"]))
    if "us10y" in macro:
        lines.append(_line("🏦", "US10Y", macro["us10y"]))
    if "vix" in macro:
        lines.append(_line("😱", "VIX", macro["vix"]))

    score = fear_score(macro)
    if score is not None:
        lines.append(f"  🌡 Fear: {score}/100 ({fear_label(score)})")

    bias = gold_bias(macro)
    if bias:
        lines.append(f"  🧭 Gold bias: {bias}")

    # Only return a block if we have more than just the header.
    return "\n".join(lines) if len(lines) > 1 else ""
