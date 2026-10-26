"""The Thai Gold Traders Association's announced price, next to the computed one.

The bot's 96.5% per-baht figures are spot x FX x purity. A shop in Thailand
quotes the Association's announcement: a buy and a sell price for bars and for
jewelry, revised and numbered through the day.
"""
import datetime as _dt
from types import SimpleNamespace

import pytest
import pytz

import bot_core
import gta
import storage

BKK = pytz.timezone("Asia/Bangkok")

# Trimmed from the live endpoint, 2026-10-26.
SAMPLE = {"goldPriceID": 88104, "asTime": "2026-10-26T16:43:00", "seq": 14,
          "bL_BuyPrice": 64150.00, "bL_SellPrice": 64350.00,
          "oM965_BuyPrice": 62868.52, "oM965_SellPrice": 65150.00,
          "goldSpot": 4019.00, "bahtPerUSD": 33.82}


class _Resp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


@pytest.fixture
def endpoint(monkeypatch):
    """The Association's endpoint: set .reply to the JSON (or an exception)."""
    ep = SimpleNamespace(reply=SAMPLE, calls=[])
    gta.reset_cache()                                  # conftest keeps it offline

    def fake_get(url, **kw):
        ep.calls.append(url)
        if isinstance(ep.reply, Exception):
            raise ep.reply
        return _Resp(ep.reply)
    monkeypatch.setattr(gta.requests, "get", fake_get)
    return ep


def test_the_announcement_is_read(endpoint):
    p = gta.fetch_latest()
    assert p["bar_buy"] == 64150.0 and p["bar_sell"] == 64350.0
    assert p["jewelry_sell"] == 65150.0 and p["seq"] == 14
    assert p["time"] == BKK.localize(_dt.datetime(2026, 10, 26, 16, 43))


def test_it_is_fetched_once_per_run(endpoint):
    gta.fetch_latest(), gta.fetch_latest()
    assert len(endpoint.calls) == 1


@pytest.mark.parametrize("reply", [
    {**SAMPLE, "bL_BuyPrice": None},
    {**SAMPLE, "bL_SellPrice": "64,350"},
    {**SAMPLE, "bL_SellPrice": 60000.0},          # sell below buy
    {**SAMPLE, "asTime": "yesterday"},
    ["not", "a", "dict"],
    ConnectionError("blocked"),
])
def test_anything_odd_leaves_the_line_out(endpoint, reply):
    endpoint.reply = reply
    assert gta.fetch_latest() is None
    assert gta.format_line(None, "en") == ""


def test_the_line_in_three_languages(endpoint):
    p = gta.fetch_latest()
    today = BKK.localize(_dt.datetime(2026, 10, 26, 18, 0))
    en = gta.format_line(p, "en", today)
    assert "#14 (16:43)" in en and "shops buy ฿64,150 · sell ฿64,350" in en
    assert "jewelry: shops sell ฿65,150" in en
    assert "ทองแท่ง: รับซื้อ ฿64,150 · ขายออก ฿64,350" in gta.format_line(p, "th", today)
    assert "ဆိုင်ဝယ် ฿64,150" in gta.format_line(p, "my", today)


def test_an_old_announcement_shows_its_date(endpoint):
    """A Sunday message must not pass Saturday's last price off as current."""
    p = gta.fetch_latest()
    sunday = BKK.localize(_dt.datetime(2026, 10, 27, 9, 0))
    assert "(10-26 16:43)" in gta.format_line(p, "en", sunday)


def test_price_command_shows_it(endpoint, monkeypatch):
    sent = []
    monkeypatch.setattr(bot_core.goldapi, "get_gold_price", lambda retries=2: (4370.0, 4019.0, 33.82))
    monkeypatch.setattr(storage, "get_price_history", lambda: [])
    monkeypatch.setattr(bot_core, "send_message", lambda text, chat_id="", **kw: sent.append(text))
    bot_core.cmd_price("someone", "en")
    assert "Thai Gold Traders Assoc. #14" in sent[0]


def test_price_command_without_it_still_works(endpoint, monkeypatch):
    endpoint.reply = ConnectionError("blocked")
    sent = []
    monkeypatch.setattr(bot_core.goldapi, "get_gold_price", lambda retries=2: (4370.0, 4019.0, 33.82))
    monkeypatch.setattr(storage, "get_price_history", lambda: [])
    monkeypatch.setattr(bot_core, "send_message", lambda text, chat_id="", **kw: sent.append(text))
    bot_core.cmd_price("someone", "en")
    assert sent and "Gold Traders" not in sent[0] and "$4,019.00" in sent[0]


def test_the_monitor_does_not_ask(monkeypatch):
    """GitHub Actions gets 403 from the site (2026-10-26); only /price asks."""
    import test_evening_privacy
    calls = []
    monkeypatch.setattr(gta, "fetch_latest", lambda: calls.append(1))
    got = test_evening_privacy._evening(monkeypatch)
    assert got["owner"] and calls == []
