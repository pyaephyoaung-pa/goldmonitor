"""
Headline context for Gold Monitor.

Tier 3 of the news-awareness work, and deliberately the most limited of the
three. events.py knows what is scheduled; regime.py knows when a move is
unusual; this module answers the follow-up question those two provoke —
"something just happened, WHAT was it?" — by showing recent gold-related
headlines.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT THIS MODULE DOES NOT DO, ON PURPOSE

  * It does not score sentiment.
  * It does not infer a direction from a headline.
  * It never feeds a buy/sell signal, an alert threshold or an ML feature.

Headline sentiment maps poorly onto gold's actual reaction — the same
"conflict escalates" story can precede a rally or a fade depending on
positioning, and the sign is not stable enough to trade. Dressing that up as a
signal would contradict the honest-metrics posture the rest of this codebase
holds to (see the `⚠️no-edge` labelling in predictor.py).

So headlines are shown as READING MATERIAL next to a move the bot detected by
other means. The user interprets them; the bot does not.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Source: GDELT DOC 2.0 — free, keyless, no registration.
    https://api.gdeltproject.org/api/v2/doc/doc

NOTE: as with signals.py, the endpoint is not reachable from the build sandbox
(network allowlist), so this module is exercised by mocked unit tests. Confirm
it once in a live GitHub Actions run — everything degrades to "no headlines"
rather than erroring if the source is unavailable.
"""

from __future__ import annotations

import html as html_module
import re
from datetime import datetime, timedelta

import pytz
import requests

import i18n

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# GDELT query syntax. Kept narrow: broad "gold" alone pulls in sport medals,
# "gold standard" idioms and mining-company PR.
DEFAULT_QUERY = (
    '(gold OR bullion) '
    '(price OR prices OR rally OR selloff OR "safe haven" OR futures) '
    'sourcelang:eng'
)

MAX_HEADLINES = 3
DEFAULT_TIMESPAN = "24h"
TITLE_MAX_CHARS = 110
REQUEST_TIMEOUT = 10

# Ordering only — NOT sentiment. These terms mark stories more likely to be
# about a macro/geopolitical driver than about a jewellery retailer, so they
# float to the top of the list. Nothing here implies a direction.
RELEVANCE_TERMS = (
    "fed", "fomc", "rate", "inflation", "cpi", "yield", "dollar", "treasury",
    "war", "conflict", "strike", "sanction", "tariff", "election", "crisis",
    "central bank", "geopolit", "escalat", "safe haven", "recession",
)


def _parse_seendate(raw: str):
    """GDELT stamps articles as 'YYYYMMDDTHHMMSSZ'."""
    try:
        return pytz.UTC.localize(datetime.strptime(raw, "%Y%m%dT%H%M%SZ"))
    except (ValueError, TypeError):
        return None


def _clean_title(title: str) -> str:
    """Collapse whitespace, trim, and ESCAPE for Telegram HTML.

    Headlines are untrusted third-party text. An unescaped '<' or '&' would at
    best break the message (Telegram 400s on malformed HTML) and at worst let a
    remote source inject markup into the bot's output.
    """
    text = re.sub(r"\s+", " ", (title or "")).strip()
    if len(text) > TITLE_MAX_CHARS:
        text = text[:TITLE_MAX_CHARS - 1].rstrip() + "…"
    return html_module.escape(text)


def relevance(title: str) -> int:
    """How many macro/geopolitical terms a headline mentions. Ordering only."""
    lowered = (title or "").lower()
    return sum(1 for term in RELEVANCE_TERMS if term in lowered)


def _dedupe(articles: list) -> list:
    """Wire copy gets syndicated verbatim; keep one copy of each story."""
    seen, out = set(), []
    for a in articles:
        key = re.sub(r"[^a-z0-9]+", "", (a.get("title") or "").lower())[:60]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def fetch_headlines(query: str = DEFAULT_QUERY, limit: int = MAX_HEADLINES,
                    timespan: str = DEFAULT_TIMESPAN) -> list:
    """Recent gold-related headlines, most relevant first. [] on any failure.

    Returns dicts of {title, url, domain, seen}. `title` is already escaped for
    Telegram HTML.
    """
    try:
        r = requests.get(
            GDELT_URL,
            params={"query": query, "mode": "artlist", "maxrecords": 40,
                    "timespan": timespan, "format": "json", "sort": "datedesc"},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        # GDELT answers overload and malformed queries with HTML or plain text
        # rather than a JSON error, so this cannot assume a parseable body.
        try:
            payload = r.json()
        except ValueError:
            print(f"[news] non-JSON response from GDELT: {r.text[:120]!r}")
            return []
    except Exception as e:  # noqa: BLE001 — context is optional, never fatal
        print(f"[news] fetch failed: {e}")
        return []

    articles = payload.get("articles")
    if not isinstance(articles, list):
        print("[news] unexpected payload shape — no 'articles' list")
        return []

    cleaned = []
    for a in _dedupe(articles):
        title = _clean_title(a.get("title"))
        if not title:
            continue
        cleaned.append({
            "title": title,
            "url": a.get("url", ""),
            "domain": a.get("domain", ""),
            "seen": _parse_seendate(a.get("seendate", "")),
            "_score": relevance(a.get("title", "")),
        })

    # Most relevant first, newest as the tie-break. Stable within each group.
    cleaned.sort(key=lambda h: (h["_score"],
                                h["seen"] or pytz.UTC.localize(datetime.min)),
                 reverse=True)
    return cleaned[:limit]


def format_block(headlines: list, lang: str | None = None) -> str:
    """Headline block for a message. "" when there is nothing to show."""
    if not headlines:
        return ""
    lines = [i18n.t("news.header", lang)]
    for h in headlines:
        source = f" — <i>{html_module.escape(h['domain'])}</i>" if h.get("domain") else ""
        if h.get("url"):
            lines.append(f"  • <a href=\"{html_module.escape(h['url'], quote=True)}\">"
                         f"{h['title']}</a>{source}")
        else:
            lines.append(f"  • {h['title']}{source}")
    lines.append(i18n.t("news.footer", lang))
    return "\n" + "\n".join(lines)
