"""A frozen price source is swapped out, not just reported.

warn_owner_if_feed_stuck told the owner when spot sat still through trading
hours, but the bot kept using the frozen quote: alerts and the TA reading
stayed frozen until someone fixed the source. The second source, already there
for outages, now stands in for a source that answers with a stale price.
"""
import datetime as _dt

import pytest
import pytz

import bot_core
import gold_monitor
import goldapi
import storage

ET = pytz.timezone("US/Eastern")
NOW = ET.localize(_dt.datetime(2026, 10, 14, 14, 0))       # Wednesday afternoon
RATE = 33.0


def _frozen_history(price=4150.0, hours=5):
    return [{"ts": (NOW - _dt.timedelta(hours=h)).isoformat(), "usd_oz": price,
             "thb_gram": 1.0} for h in range(hours, 0, -1)]


@pytest.fixture
def world(monkeypatch):
    """Twelve Data stuck at 4150; gold-api.com live at 4163.25."""
    w = {"history": _frozen_history(), "alt": 4163.25, "msgs": []}
    monkeypatch.setattr(gold_monitor, "_bot_state", {})
    monkeypatch.setattr(gold_monitor, "TG_CHAT_ID", "OWNER")
    monkeypatch.setattr(storage, "get_user_lang", lambda cid: "en")
    monkeypatch.setattr(storage, "get_price_history", lambda: w["history"])
    monkeypatch.setattr(goldapi, "last_spot_source", "twelve_data")

    def fake_fetch(exclude=()):
        if "gold-api.com" in exclude or w["alt"] is None:
            return None
        goldapi.last_spot_source = "gold-api.com"
        return w["alt"]
    monkeypatch.setattr(goldapi, "fetch_spot_usd", fake_fetch)
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="", **kw: w["msgs"].append((chat_id, text)))
    return w


def _run(usd, now=NOW):
    goldapi.last_spot_source = "twelve_data"
    return gold_monitor.failover_if_frozen(goldapi.thb_per_gram(usd, RATE), usd, RATE, now)


def test_a_frozen_source_is_replaced_by_the_live_one(world):
    thb, usd, changed = _run(4150.0)
    assert usd == 4163.25 and thb == goldapi.thb_per_gram(4163.25, RATE) and changed
    assert gold_monitor._bot_state["spot_frozen"]["source"] == "twelve_data"
    assert world["msgs"][0][0] == "OWNER" and "twelve_data is stuck at $4,150.00/oz" in world["msgs"][0][1]


def test_it_stays_on_the_stand_in_without_telling_the_owner_again(world):
    """Once the stand-in's prices are stored, the frozen quote no longer
    matches the history — without the memory the bot would switch back."""
    _run(4150.0)
    world["history"] = _frozen_history(4163.25, 1)
    world["alt"] = 4165.0
    _, usd, _ = _run(4150.0)
    assert usd == 4165.0 and len(world["msgs"]) == 1


def test_the_source_moving_again_ends_the_switch(world):
    _run(4150.0)
    thb, usd, changed = _run(4152.5)
    assert usd == 4152.5 and changed and "spot_frozen" not in gold_monitor._bot_state


def test_a_moving_source_is_left_alone(world):
    world["history"] = _frozen_history(4140.0)
    assert _run(4150.0)[1:] == (4150.0, False)


def test_with_no_live_alternative_it_keeps_the_quote(world):
    """The feed watchdog will warn; there is nothing better to switch to."""
    world["alt"] = None
    assert _run(4150.0)[1:] == (4150.0, False) and world["msgs"] == []


def test_fetch_spot_usd_skips_an_excluded_source(monkeypatch):
    monkeypatch.setattr(goldapi, "_SPOT_SOURCES", (
        ("twelve_data", lambda: 4150.0), ("gold-api.com", lambda: 4163.25)))
    assert goldapi.fetch_spot_usd() == 4150.0 and goldapi.last_spot_source == "twelve_data"
    assert goldapi.fetch_spot_usd(exclude=("twelve_data",)) == 4163.25
    assert goldapi.last_spot_source == "gold-api.com"
