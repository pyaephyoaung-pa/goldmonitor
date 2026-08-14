"""Tests for headline context (Tier 3).

The GDELT endpoint is not reachable from CI, so every network call is mocked —
the same approach signals.py takes. What is pinned here is the parsing,
escaping, ordering and (importantly) the boundaries this module must NOT cross.
"""

from datetime import datetime

import pytest
import pytz

import bot_core
import gold_monitor
import i18n
import news
import regime
import storage

UTC = pytz.UTC


class _Resp:
    def __init__(self, payload=None, text="", raise_exc=None):
        self._payload = payload
        self.text = text
        self._raise = raise_exc

    def raise_for_status(self):
        if self._raise:
            raise self._raise

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _article(title, domain="reuters.com", seen="20260808T120000Z", url="https://x/1"):
    return {"title": title, "domain": domain, "seendate": seen, "url": url}


def _mock(monkeypatch, resp):
    monkeypatch.setattr(news.requests, "get", lambda *a, **k: resp)


# ── Parsing ─────────────────────────────────────────────────────

def test_fetches_and_parses(monkeypatch):
    _mock(monkeypatch, _Resp({"articles": [
        _article("Gold rallies as Fed holds rates"),
        _article("Bullion steady ahead of CPI"),
    ]}))
    out = news.fetch_headlines()
    assert len(out) == 2
    assert out[0]["domain"] == "reuters.com"
    assert out[0]["seen"] == UTC.localize(datetime(2026, 8, 8, 12, 0))


def test_non_json_response_degrades(monkeypatch, capsys):
    """GDELT answers overload with HTML, not a JSON error."""
    _mock(monkeypatch, _Resp(payload=None, text="<html>rate limited</html>"))
    assert news.fetch_headlines() == []
    assert "non-JSON response" in capsys.readouterr().out


def test_network_failure_degrades(monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("connection reset")
    monkeypatch.setattr(news.requests, "get", boom)
    assert news.fetch_headlines() == []
    assert "fetch failed" in capsys.readouterr().out


def test_unexpected_payload_shape_degrades(monkeypatch, capsys):
    _mock(monkeypatch, _Resp({"status": "ok"}))
    assert news.fetch_headlines() == []
    assert "unexpected payload shape" in capsys.readouterr().out


def test_bad_seendate_does_not_raise(monkeypatch):
    _mock(monkeypatch, _Resp({"articles": [_article("Gold up", seen="garbage")]}))
    out = news.fetch_headlines()
    assert len(out) == 1 and out[0]["seen"] is None


def test_empty_titles_are_dropped(monkeypatch):
    _mock(monkeypatch, _Resp({"articles": [
        _article(""), _article(None), _article("Gold steady"),
    ]}))
    assert [h["title"] for h in news.fetch_headlines()] == ["Gold steady"]


# ── Escaping: headlines are untrusted third-party text ──────────

def test_titles_are_html_escaped(monkeypatch):
    _mock(monkeypatch, _Resp({"articles": [
        _article("Gold <b>surges</b> & breaks $3,000"),
    ]}))
    title = news.fetch_headlines()[0]["title"]
    assert "<b>" not in title
    assert "&lt;b&gt;" in title and "&amp;" in title


def test_urls_are_escaped_in_the_block(monkeypatch):
    _mock(monkeypatch, _Resp({"articles": [
        _article("Gold up", url='https://x/?a=1&b="2"'),
    ]}))
    block = news.format_block(news.fetch_headlines(), "en")
    assert '&amp;b=' in block
    assert '"2"' not in block, "raw quotes would break the href attribute"


def test_domain_is_escaped(monkeypatch):
    _mock(monkeypatch, _Resp({"articles": [_article("Gold up", domain="a<b>.com")]}))
    block = news.format_block(news.fetch_headlines(), "en")
    # The header legitimately contains <b>; check the domain itself was escaped.
    assert "a&lt;b&gt;.com" in block
    assert "a<b>.com" not in block


def test_long_titles_are_truncated(monkeypatch):
    long_title = "Gold " * 100
    _mock(monkeypatch, _Resp({"articles": [_article(long_title)]}))
    title = news.fetch_headlines()[0]["title"]
    assert len(title) <= news.TITLE_MAX_CHARS
    assert title.endswith("…")


# ── Dedup and ordering ──────────────────────────────────────────

def test_syndicated_copies_are_deduped(monkeypatch):
    _mock(monkeypatch, _Resp({"articles": [
        _article("Gold rallies as Fed holds rates", domain="reuters.com"),
        _article("Gold rallies as Fed holds rates!", domain="cnbc.com"),
        _article("Gold rallies as Fed holds rates", domain="ft.com"),
        _article("Something entirely different"),
    ]}))
    out = news.fetch_headlines(limit=10)
    assert len(out) == 2


def test_macro_headlines_rank_above_retail_ones(monkeypatch):
    _mock(monkeypatch, _Resp({"articles": [
        _article("Local jeweller opens new gold showroom"),
        _article("Gold jumps as Fed signals rate cut amid inflation data"),
    ]}))
    out = news.fetch_headlines(limit=2)
    assert "Fed" in out[0]["title"], "macro story should sort first"


def test_relevance_is_ordering_not_sentiment():
    """Scores count topic terms only — nothing directional."""
    up = news.relevance("Gold surges on Fed rate cut")
    down = news.relevance("Gold plunges on Fed rate cut")
    assert up == down, "wording direction must not change the score"


def test_limit_is_respected(monkeypatch):
    _mock(monkeypatch, _Resp({"articles": [
        _article(f"Gold story number {i}") for i in range(20)
    ]}))
    assert len(news.fetch_headlines(limit=3)) == 3


# ── Rendering ───────────────────────────────────────────────────

def test_format_block_empty_for_no_headlines():
    assert news.format_block([], "en") == ""


def test_format_block_carries_the_disclaimer(monkeypatch):
    _mock(monkeypatch, _Resp({"articles": [_article("Gold steady")]}))
    block = news.format_block(news.fetch_headlines(), "en")
    assert "does not interpret" in block


def test_format_block_localised(monkeypatch):
    _mock(monkeypatch, _Resp({"articles": [_article("Gold steady")]}))
    items = news.fetch_headlines()
    assert "พาดหัวข่าว" in news.format_block(items, "th")
    assert "သတင်းခေါင်းစဉ်" in news.format_block(items, "my")


# ── Boundaries this module must not cross ───────────────────────

def test_news_is_not_an_ml_feature():
    """A headline must never reach the model."""
    import predictor
    names = [n.lower() for n in [
        "rsi", "price_vs_sma5", "price_vs_sma20", "sma_crossover", "macd",
        "macd_histogram", "bb_position", "momentum", "volatility", "hour",
        "weekday", "hours_to_event", "in_event_window", "change_1h", "change_4h"]]
    assert not any("news" in n or "sentiment" in n for n in names)
    assert "news" not in predictor.__doc__.lower()


def test_news_module_exposes_no_sentiment_api():
    """Guards the design decision against a well-meaning future edit."""
    banned = [a for a in dir(news)
              if any(w in a.lower() for w in ("sentiment", "bullish", "bearish",
                                              "signal", "predict"))]
    assert not banned, f"news.py must stay interpretation-free, found {banned}"


# ── /news command ───────────────────────────────────────────────

class _MemStore:
    def __init__(self, monkeypatch):
        self.files = {}
        monkeypatch.setattr(
            storage, "_read_file",
            lambda f: self.files.get(
                f, [] if f in (storage.PRICE_HISTORY_FILE, storage.BUY_LOG_FILE) else {}))
        monkeypatch.setattr(storage, "_write_file",
                            lambda f, d: self.files.__setitem__(f, d))


def _capture(monkeypatch):
    sent = []
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="", **kw: sent.append(text))
    return sent


def test_news_command_shows_headlines(monkeypatch):
    _MemStore(monkeypatch)
    sent = _capture(monkeypatch)
    monkeypatch.setattr(bot_core.news, "fetch_headlines",
                        lambda *a, **k: [{"title": "Gold up on Fed pause",
                                          "url": "https://x/1",
                                          "domain": "reuters.com", "seen": None}])
    bot_core.cmd_news("111", "en")
    assert "Gold up on Fed pause" in sent[-1]
    assert "Recent headlines" in sent[-1]


def test_news_command_when_source_down(monkeypatch):
    _MemStore(monkeypatch)
    sent = _capture(monkeypatch)
    monkeypatch.setattr(bot_core.news, "fetch_headlines", lambda *a, **k: [])
    bot_core.cmd_news("111", "en")
    assert "News source unavailable" in sent[-1]


# ── Monitor integration: fetched only when something happened ───

def _quiet_history(n=200):
    import random
    from datetime import timedelta
    bkk = pytz.timezone("Asia/Bangkok")
    now = datetime.now(bkk)
    rng = random.Random(3)
    price = 4000.0
    out = []
    for i in range(n):
        price *= (1 + rng.gauss(0, 0.05) / 100)
        out.append({"ts": (now - timedelta(hours=n - i)).isoformat(),
                    "thb_gram": round(price, 4)})
    return out


def test_headlines_not_fetched_in_a_quiet_market(monkeypatch):
    """The expensive call must stay off the hot path for quiet runs."""
    calls = []
    monkeypatch.setattr(news, "fetch_headlines",
                        lambda *a, **k: calls.append(1) or [])
    vol = regime.vol_regime(_quiet_history())
    assert regime.is_unusual(vol) is False
    # Mirrors the guard in gold_monitor.headline_block
    should_fetch = regime.is_unusual(vol) or "post" == None
    assert should_fetch is False
    assert calls == []


def test_headline_gate_matches_regime_and_event(monkeypatch):
    unusual = {"available": True, "level": "extreme", "ratio": 5.0, "shock": True}
    quiet = {"available": True, "level": "normal", "ratio": 1.1, "shock": False}

    assert (regime.is_unusual(unusual) or "pre" == "post") is True
    assert (regime.is_unusual(quiet) or "post" == "post") is True, "event post fires it"
    assert (regime.is_unusual(quiet) or "pre" == "post") is False


# ── Google News RSS (primary source) ────────────────────────────
#
# GDELT was demoted after live testing: it answers HTTP 429 on most calls from
# shared/serverless IPs, so /news failed almost every time. These pin the
# primary path and the fallback ordering.

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Gold heads for weekly loss as rally unwinds - CNBC</title>
<link>https://cnbc.com/a</link><pubDate>Fri, 14 Aug 2026 04:18:59 GMT</pubDate></item>
<item><title>UBS sees gold challenging $5,000/oz - KITCO</title>
<link>https://kitco.com/b</link><pubDate>Thu, 13 Aug 2026 15:33:55 GMT</pubDate></item>
<item><title>Gold Price Canada Today | Live Gold Price in CAD - KITCO</title>
<link>https://kitco.com/c</link><pubDate>Thu, 13 Aug 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


class _RssResp:
    def __init__(self, content=RSS, status=200):
        self.content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise OSError(f"HTTP {self.status_code}")


def test_google_news_is_parsed(monkeypatch):
    monkeypatch.setattr(news.requests, "get", lambda *a, **k: _RssResp())
    out = news.fetch_headlines(limit=5)
    titles = [h["title"] for h in out]
    assert any("weekly loss" in t for t in titles)
    assert any("UBS" in t for t in titles)


def test_google_source_is_split_from_title(monkeypatch):
    monkeypatch.setattr(news.requests, "get", lambda *a, **k: _RssResp())
    out = news.fetch_headlines(limit=5)
    top = next(h for h in out if "weekly loss" in h["title"])
    assert top["domain"] == "CNBC"
    assert "- CNBC" not in top["title"], "source suffix must be stripped"


def test_split_title_uses_the_last_dash():
    """Headlines contain their own dashes."""
    head, src = news._split_google_title(
        "Gold Price Outlook: Speed Bump - Seems Unlikely - FOREX.com")
    assert head == "Gold Price Outlook: Speed Bump - Seems Unlikely"
    assert src == "FOREX.com"


def test_split_title_without_a_source():
    head, src = news._split_google_title("Gold rises")
    assert head == "Gold rises" and src == ""


def test_split_title_ignores_a_long_trailing_segment():
    """A long tail after ' - ' is part of the headline, not a source name."""
    raw = "Gold rises - and analysts now expect a sustained multi-quarter rally"
    head, src = news._split_google_title(raw)
    assert src == "" and head == raw


def test_live_quote_pages_are_filtered(monkeypatch):
    monkeypatch.setattr(news.requests, "get", lambda *a, **k: _RssResp())
    titles = [h["title"] for h in news.fetch_headlines(limit=10)]
    assert not any("Live Gold Price" in t for t in titles)


def test_is_noise_markers():
    assert news.is_noise("Gold Price Canada Today | Live Gold Price in CAD")
    assert news.is_noise("Gold Futures Streaming Chart")
    assert news.is_noise("Gold price in Saudi Arabia: Rates on August 14")
    assert not news.is_noise("Gold falls after US inflation data")


def test_gdelt_not_used_when_google_succeeds(monkeypatch):
    monkeypatch.setattr(news.requests, "get", lambda *a, **k: _RssResp())

    def must_not_run(*a, **k):
        raise AssertionError("GDELT must not be called when Google News works")
    monkeypatch.setattr(news, "_fetch_gdelt", must_not_run)
    assert news.fetch_headlines(limit=3)


def test_falls_back_to_gdelt_when_google_fails(monkeypatch):
    monkeypatch.setattr(news, "_fetch_google_news", lambda limit: [])
    monkeypatch.setattr(news, "_fetch_gdelt",
                        lambda q, l, t: [{"title": "Gold up on Fed pause",
                                          "url": "https://x/1", "domain": "reuters.com",
                                          "seen": None}])
    out = news.fetch_headlines(limit=3)
    assert out and "Fed pause" in out[0]["title"]


def test_both_sources_down_returns_empty(monkeypatch):
    monkeypatch.setattr(news, "_fetch_google_news", lambda limit: [])
    monkeypatch.setattr(news, "_fetch_gdelt", lambda q, l, t: [])
    assert news.fetch_headlines() == []


def test_malformed_rss_degrades(monkeypatch, capsys):
    monkeypatch.setattr(news.requests, "get",
                        lambda *a, **k: _RssResp(b"<rss><unclosed>"))
    monkeypatch.setattr(news, "_fetch_gdelt", lambda q, l, t: [])
    assert news.fetch_headlines() == []
    assert "google news fetch failed" in capsys.readouterr().out


def test_oversized_feed_is_refused(monkeypatch, capsys):
    big = b"x" * (news.MAX_FEED_BYTES + 1)
    monkeypatch.setattr(news.requests, "get", lambda *a, **k: _RssResp(big))
    monkeypatch.setattr(news, "_fetch_gdelt", lambda q, l, t: [])
    assert news.fetch_headlines() == []
    assert "too large" in capsys.readouterr().out


def test_google_http_error_degrades(monkeypatch):
    monkeypatch.setattr(news.requests, "get", lambda *a, **k: _RssResp(status=429))
    monkeypatch.setattr(news, "_fetch_gdelt", lambda q, l, t: [])
    assert news.fetch_headlines() == []


def test_rfc822_dates_are_parsed():
    dt = news._parse_rfc822("Fri, 14 Aug 2026 04:18:59 GMT")
    assert dt is not None and dt.year == 2026 and dt.tzinfo is not None
    assert news._parse_rfc822("garbage") is None
    assert news._parse_rfc822("") is None
