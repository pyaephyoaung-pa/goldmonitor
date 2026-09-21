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

Sources, in order (both free, keyless, no registration):

  1. Google News RSS — primary. Real news-search relevance, and no meaningful
     rate limit.
  2. GDELT DOC 2.0 — fallback.

GDELT was the original primary and turned out to be unusable on its own: it
answers with HTTP 429 ("limit requests to one every 5 seconds") on most calls
from shared/serverless IPs, and even when it succeeds its relevance for this
query is poor — it returns mining-company earnings calls and unrelated market
wraps. It is kept as a fallback because it does sometimes work and costs
nothing to try.

Everything degrades to "no headlines" rather than erroring if both are down.
"""

from __future__ import annotations

import html as html_module
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import pytz
import requests

import i18n

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Google News takes a plain search string; `when:1d` scopes it to the last day.
GOOGLE_QUERY = '"gold price" OR "spot gold" OR bullion when:1d'

# Google News serves some feeds only to browser-ish clients.
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; GoldMonitor/1.0)"}

# Cap what we are willing to download — the feed is untrusted input. Enforced
# while READING (see _read_capped), because requests buffers the whole body
# before returning unless the response is streamed: the old check ran after the
# download it was meant to prevent, and covered only the RSS source.
MAX_FEED_BYTES = 2_000_000

# A DOCTYPE is the only way an XML document can define its own entities, and
# ElementTree expands them — a few hundred bytes of nested definitions become
# gigabytes in memory. MAX_FEED_BYTES cannot catch that: the payload is small
# on the wire and only blows up during parsing. RSS needs no DOCTYPE, so refuse
# any feed carrying one. Built-in entities (&amp;, &#8212;) are unaffected;
# without a DOCTYPE a custom entity is simply an "undefined entity" parse error.
_DOCTYPE_RE = re.compile(rb"<!\s*DOCTYPE", re.IGNORECASE)

# Evergreen quote/chart pages that syndicate daily under a news-shaped headline
# but carry no information: "Live Gold Price in CAD", "Gold Futures Streaming
# Chart", per-country rate listings. Matched case-insensitively on the title.
NOISE_MARKERS = (
    "live gold price", "streaming chart", "price chart",
    "gold rate today", "gold price today", "today gold price",
    "latest gold rate", "gold price in ", "gold rate in ",
    "price in india", "technical analysis for",
    "carat gold price", "22k", "24k",
)

# Two of those markers used to be plain substrings and were dropping exactly
# the headlines this module exists to surface:
#
#   "rates on "     killed "Fed cuts rates on weak jobs data, gold rallies"
#                   and "ECB holds rates on persistent inflation fears"
#   "closing price" killed "Gold closing price sets fresh record after CPI"
#
# The spam they were aimed at is a DATE listing — "Gold Rates on 20-07-2026",
# "MCX gold closing price today" — so require the date, not just the words.
# "on <month>" is not something English prose says about anything but a date.
_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
NOISE_PATTERNS = (
    re.compile(rf"\brates? on (?:\d|{_MONTHS})", re.IGNORECASE),
    re.compile(r"\bclosing price today\b", re.IGNORECASE),
)

# Structural rules, tuned against a live 100-item feed rather than guessed.
#
# Aggregator/widget spam stacks several labels into one title:
#   "Today Gold Price | Latest Gold Rate | 20-07-2026 | ... Hyderabad | YOYO TV"
# but legitimate posts do use a couple of separators:
#   "China gold market update: Strong official buying | Post by Ray Jia | Insight"
# so the cut is ABOVE two, not at two.
MAX_TITLE_PIPES = 2

# Feeds carry bare section labels ("Videos", "Markets") that are not headlines.
# Kept deliberately low: a real headline can be short ("Gold hits record high",
# 21 chars), so this only catches one- or two-word labels.
MIN_TITLE_CHARS = 15

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


def is_noise(title: str) -> bool:
    """True for evergreen quote/chart pages masquerading as headlines.

    Four passes: too short to be a headline, too many separators to be
    anything but an aggregator label stack, a date-listing pattern, or a known
    quote-page phrase.
    """
    text = (title or "").strip()
    if len(text) < MIN_TITLE_CHARS:
        return True
    if text.count("|") > MAX_TITLE_PIPES:
        return True
    if any(pattern.search(text) for pattern in NOISE_PATTERNS):
        return True
    lowered = text.lower()
    return any(marker in lowered for marker in NOISE_MARKERS)


def _split_google_title(raw: str) -> tuple:
    """Google News formats titles as "Headline - Source". Split the source off.

    rsplit on the LAST " - ", since headlines frequently contain their own
    dashes ("Gold Price Outlook: Speed Bump - Seems Unlikely - FOREX.com").
    """
    if " - " in raw:
        head, _, source = raw.rpartition(" - ")
        if head and len(source) <= 40:
            return head.strip(), source.strip()
    return raw.strip(), ""


def _read_capped(response, source: str) -> bytes | None:
    """Body bytes, or None if `source` sends more than MAX_FEED_BYTES.

    Reads in chunks and stops, so an oversized body is never fully buffered —
    which is the difference between capping a download and merely declining to
    parse one that has already arrived.
    """
    body = bytearray()
    for chunk in response.iter_content(64 * 1024):
        body += chunk
        if len(body) > MAX_FEED_BYTES:
            print(f"[news] {source} feed too large "
                  f"(over {MAX_FEED_BYTES} bytes) — ignoring")
            return None
    return bytes(body)


def _fetch_google_news(limit: int) -> list:
    """Primary source. Returns raw dicts (unescaped) or [] on failure."""
    try:
        with requests.get(
            GOOGLE_NEWS_RSS,
            params={"q": GOOGLE_QUERY, "hl": "en-US", "gl": "US", "ceid": "US:en"},
            headers=_HEADERS, timeout=REQUEST_TIMEOUT, stream=True,
        ) as r:
            r.raise_for_status()
            body = _read_capped(r, "google")
        if body is None:
            return []
        if _DOCTYPE_RE.search(body):
            print("[news] google feed declares a DOCTYPE — refusing to parse it")
            return []
        root = ET.fromstring(body)
    except Exception as e:  # noqa: BLE001 — context is optional, never fatal
        print(f"[news] google news fetch failed: {e}")
        return []

    out = []
    for item in root.findall(".//item"):
        title, source = _split_google_title(item.findtext("title") or "")
        if not title or is_noise(title):
            continue
        out.append({
            "title": title,
            "url": item.findtext("link") or "",
            "domain": source,
            "seen": _parse_rfc822(item.findtext("pubDate")),
        })
        if len(out) >= limit * 6:  # over-fetch so dedup/ranking has room
            break
    return out


def _parse_rfc822(raw: str):
    """RSS pubDate -> aware datetime, or None."""
    if not raw:
        return None
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(raw)
        return dt if dt.tzinfo else pytz.UTC.localize(dt)
    except Exception:
        return None


def _fetch_gdelt(query: str, limit: int, timespan: str) -> list:
    """Fallback source. Returns raw dicts (unescaped) or [] on failure."""
    try:
        with requests.get(
            GDELT_URL,
            params={"query": query, "mode": "artlist", "maxrecords": 40,
                    "timespan": timespan, "format": "json", "sort": "datedesc"},
            timeout=REQUEST_TIMEOUT, stream=True,
        ) as r:
            r.raise_for_status()
            body = _read_capped(r, "gdelt")
        if body is None:
            return []
        # GDELT answers overload and malformed queries with HTML or plain text
        # rather than a JSON error, so this cannot assume a parseable body.
        try:
            payload = json.loads(body)
        except ValueError:
            print(f"[news] non-JSON response from GDELT: {body[:120]!r}")
            return []
    except Exception as e:  # noqa: BLE001 — context is optional, never fatal
        print(f"[news] fetch failed: {e}")
        return []

    articles = payload.get("articles")
    if not isinstance(articles, list):
        print("[news] unexpected payload shape — no 'articles' list")
        return []

    out = []
    for a in articles:
        title = (a.get("title") or "").strip()
        if not title or is_noise(title):
            continue
        out.append({
            "title": title,
            "url": a.get("url", ""),
            "domain": a.get("domain", ""),
            "seen": _parse_seendate(a.get("seendate", "")),
        })
    return out


def fetch_headlines(query: str = DEFAULT_QUERY, limit: int = MAX_HEADLINES,
                    timespan: str = DEFAULT_TIMESPAN) -> list:
    """Recent gold-related headlines, most relevant first. [] on any failure.

    Google News first, GDELT only if it yields nothing — GDELT 429s on most
    calls from shared IPs, so trying it first made /news fail almost always.

    Returns dicts of {title, url, domain, seen}. `title` is escaped for
    Telegram HTML; ordering/dedup happen here so both sources get the same
    treatment.
    """
    raw = _fetch_google_news(limit)
    if not raw:
        print("[news] google news empty — falling back to GDELT")
        raw = _fetch_gdelt(query, limit, timespan)
    if not raw:
        return []

    cleaned = []
    for a in _dedupe(raw):
        title = _clean_title(a.get("title"))
        if not title:
            continue
        cleaned.append({
            "title": title,
            "url": a.get("url", ""),
            "domain": a.get("domain", ""),
            "seen": a.get("seen"),
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
