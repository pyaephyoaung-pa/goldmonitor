"""The Thai Gold Traders Association's announced price.

The bot's own 96.5% "per baht" figures are computed: spot x FX x purity. What a
shop in Thailand actually quotes is the Association's announcement — a buy and
a sell price for 96.5% bars and for jewelry, revised through the day and
numbered (ครั้งที่ 1, 2, ...). The bar prices sit close to the computed value
with a ฿200 spread; jewelry sells at a markup the computed figure cannot show.

Source: the JSON endpoint goldtraders.or.th's own homepage loads. Its
robots.txt allows general clients ("User-agent: *  Allow: /"); it is called at
most once per command, and a failure only leaves the line out.

Only /price uses it. From GitHub Actions the site answers 403 (first seen on
2026-10-26's 20:00 BKK run) while the Vercel webhook is served, so the
monitor's morning and evening messages do not ask: a request known to be
refused is load on someone else's server for nothing. Do not route around
the block — it is the site's to set.
"""

from __future__ import annotations

from datetime import datetime

import pytz
import requests

import i18n
from gold_format import fmt

URL = "https://www.goldtraders.or.th/api/GoldPrices/Latest"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; GoldMonitor/1.0)"}
BANGKOK_TZ = pytz.timezone("Asia/Bangkok")

# The fields used, all THB per baht weight of 96.5% gold.
_PRICES = {"bar_buy": "bL_BuyPrice", "bar_sell": "bL_SellPrice",
           "jewelry_buy": "oM965_BuyPrice", "jewelry_sell": "oM965_SellPrice"}


def _parse(data) -> dict | None:
    """The announcement, or None if anything in it looks wrong."""
    if not isinstance(data, dict):
        return None
    out = {}
    for key, field in _PRICES.items():
        value = data.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return None
        out[key] = float(value)
    if out["bar_sell"] < out["bar_buy"] or out["jewelry_sell"] < out["jewelry_buy"]:
        return None
    try:
        out["time"] = BANGKOK_TZ.localize(datetime.fromisoformat(data["asTime"]))
    except (KeyError, TypeError, ValueError):
        return None
    seq = data.get("seq")
    out["seq"] = seq if isinstance(seq, int) and not isinstance(seq, bool) else None
    return out


# Per-run cache, like signals: the monitor's morning and evening messages and a
# /price command each want it once, not once per language.
_cache: dict | None = None
_fetched = False


def reset_cache():
    global _cache, _fetched
    _cache, _fetched = None, False


def fetch_latest() -> dict | None:
    """The latest announcement (see _parse), or None if it cannot be had."""
    global _cache, _fetched
    if _fetched:
        return _cache
    _fetched = True
    try:
        r = requests.get(URL, params={"readjson": "false"}, headers=_HEADERS, timeout=10)
        r.raise_for_status()
        _cache = _parse(r.json())
        if _cache is None:
            print("[gta] unexpected response shape — line left out")
    except Exception as e:  # noqa: BLE001 - optional context, never fatal
        print(f"[gta] fetch failed: {e}")
        _cache = None
    return _cache


def format_line(price: dict | None, lang: str | None = None,
                now: datetime | None = None) -> str:
    """One message line, or "" when there is no announcement to show.

    The time is shown with its date when the announcement is not from today,
    so a Sunday message cannot pass Saturday's last price off as current.
    """
    if not price:
        return ""
    now = now or datetime.now(BANGKOK_TZ)
    t = price["time"]
    when = t.strftime("%H:%M") if t.date() == now.astimezone(BANGKOK_TZ).date() \
        else t.strftime("%m-%d %H:%M")
    return i18n.t("gta.line", lang, seq=price["seq"] if price["seq"] is not None else "?",
                  when=when, bar_buy=fmt(price["bar_buy"]), bar_sell=fmt(price["bar_sell"]),
                  jewelry_sell=fmt(price["jewelry_sell"]))
