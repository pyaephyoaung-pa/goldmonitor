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

from __future__ import annotations

import requests

# Stooq primary tickers (kept for reference).
SYMBOLS = {
    "dxy": "^dxy",    # US Dollar Index
    "us10y": "^tnx",  # US 10Y yield index
    "vix": "^vix",    # CBOE Volatility Index
}

# Stooq ticker names vary, so we try several candidates per metric until one
# returns data. If a metric is still missing in a live run, find a working
# ticker with `python signals.py` (diagnose) and pin it at the front here.
SYMBOL_CANDIDATES = {
    "dxy": ["^dxy", "dx.f", "usdidx"],   # dollar index / futures
    "us10y": ["^tnx", "10usy.b"],        # 10Y yield index / bond yield
    "vix": ["^vix"],                     # volatility index
}

# Yahoo Finance — PRIMARY source (keyless, reliable). Stooq blocks many CI/
# automated clients, so it is only a secondary fallback below.
YAHOO_SYMBOLS = {
    "dxy": ["DX-Y.NYB"],   # ICE US Dollar Index
    "us10y": ["^TNX"],     # 10Y yield, already in percent (e.g. 4.53 = 4.53%)
    "vix": ["^VIX"],       # CBOE Volatility Index
}

# Stooq returns an EMPTY body to clients without a browser-like User-Agent —
# the most common cause of "macro data unavailable". Always send one.
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; GoldMonitor/1.0)"}


def _fetch_stooq_closes(symbol: str) -> list:
    """Return chronological list of daily closes for a Stooq symbol ([] on error)."""
    try:
        # Pass the symbol via params so '^' is URL-encoded correctly.
        r = requests.get(
            "https://stooq.com/q/d/l/",
            params={"s": symbol, "i": "d"},
            headers=_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        text = r.text.strip()
        lines = text.splitlines()
        # Expect CSV header: Date,Open,High,Low,Close,Volume
        if not lines or "Close" not in lines[0]:
            return []
        closes = []
        for line in lines[1:]:
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


def _fetch_yahoo_closes(symbol: str) -> list:
    """Return chronological daily closes from Yahoo Finance ([] on error)."""
    try:
        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"interval": "1d", "range": "5d"},
            headers=_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        result = r.json()["chart"]["result"][0]
        closes = result["indicators"]["quote"][0]["close"]
        return [round(float(c), 4) for c in closes if c is not None]
    except Exception as e:  # noqa: BLE001
        print(f"[signals] yahoo fetch failed for {symbol}: {e}")
        return []


def _closes_for(key: str) -> tuple:
    """Try Yahoo (reliable) first, then Stooq; return (source_symbol, closes).

    Yahoo is primary because Stooq's CSV endpoint blocks many automated/CI
    clients (returns an empty body). Stooq stays as a secondary fallback.
    """
    for sym in YAHOO_SYMBOLS.get(key, []):
        closes = _fetch_yahoo_closes(sym)
        if closes:
            return f"yahoo:{sym}", closes
    for sym in SYMBOL_CANDIDATES.get(key, [SYMBOLS.get(key, "")]):
        if not sym:
            continue
        closes = _fetch_stooq_closes(sym)
        if closes:
            return sym, closes
    return None, []


def fetch_macro() -> dict:
    """Fetch latest value + daily change for each macro metric.

    Returns {key: {"value", "change_pct", "change_abs", "symbol"}} for whatever
    succeeded (missing/failed metrics are simply absent). `change_abs` is the
    raw daily delta — used to show yields in percentage points (pp).
    """
    out = {}
    for key in YAHOO_SYMBOLS:
        sym, closes = _closes_for(key)
        if not closes:
            continue
        latest = round(closes[-1], 2)
        change_pct = change_abs = None
        if len(closes) >= 2 and closes[-2]:
            change_pct = round((closes[-1] - closes[-2]) / closes[-2] * 100, 2)
            change_abs = round(closes[-1] - closes[-2], 2)
        out[key] = {
            "value": latest,
            "change_pct": change_pct,
            "change_abs": change_abs,
            "symbol": sym,
        }
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


def _line_yield(emoji, label, metric):
    """Yields read as a level in percent with the daily move in pp (bps)."""
    val = metric.get("value")
    abs_chg = metric.get("change_abs")
    if abs_chg is not None:
        return f"  {emoji} {label}: {val}% ({abs_chg:+.2f}pp) {_arrow(abs_chg)}"
    return f"  {emoji} {label}: {val}% {_arrow(None)}"


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
        lines.append(_line_yield("🏦", "US10Y", macro["us10y"]))
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


def diagnose():
    """Print which Stooq tickers actually return data.

    Run `python signals.py` from a machine with internet access to find the
    working tickers, then pin them at the front of SYMBOL_CANDIDATES.
    """
    print("Stooq:")
    for key, cands in SYMBOL_CANDIDATES.items():
        for sym in cands:
            closes = _fetch_stooq_closes(sym)
            status = f"OK ({len(closes)} pts, last={closes[-1]})" if closes else "no data"
            print(f"  {key:6} {sym:10} -> {status}")
    print("Yahoo (fallback):")
    for key, cands in YAHOO_SYMBOLS.items():
        for sym in cands:
            closes = _fetch_yahoo_closes(sym)
            status = f"OK ({len(closes)} pts, last={closes[-1]})" if closes else "no data"
            print(f"  {key:6} {sym:12} -> {status}")
    print("\nfetch_macro() ->", fetch_macro())


if __name__ == "__main__":
    diagnose()
