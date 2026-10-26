"""The macro block says where each metric sits against its own past year.

It showed only the daily change. A yield up 0.03pp today reads the same at a
3-month low as at its highest level in years — and the level is what weighs on
gold. On 2026-09-28 the 10-year was at its highest since 2007 and the bot said
nothing about it.
"""
import signals


def _year(last, base=100.0):
    """A flat-ish year of closes around `base`, ending at `last`."""
    return [base + (i % 7) for i in range(260)] + [last]


def test_a_new_high_is_flagged():
    pos = signals.year_position(_year(200.0))
    assert pos["year_high"] is True and pos["above_pct"] == 100


def test_the_share_of_days_is_counted_against_the_past_year_only():
    closes = [1000.0] * 500 + list(range(1, 253)) + [126.5]
    pos = signals.year_position(closes)
    assert pos["above_pct"] == 50 and pos["below_pct"] == 50   # the old 1000s are out of range
    assert not pos["year_high"] and not pos["year_low"]


def test_too_short_a_history_is_not_ranked():
    assert signals.year_position([1.0, 2.0, 3.0]) == {}


def test_only_notable_levels_get_a_line():
    assert "1-year high" in signals.level_note({"year_high": True}, "US10Y", "en")
    assert "1-year low" in signals.level_note({"year_low": True}, "VIX", "en")
    assert "96% of days" in signals.level_note({"above_pct": 96, "below_pct": 4}, "DXY", "en")
    assert "lower than on 92%" in signals.level_note({"above_pct": 8, "below_pct": 92}, "DXY", "en")
    assert signals.level_note({"above_pct": 80, "below_pct": 20}, "VIX", "en") == ""
    assert signals.level_note({}, "VIX", "en") == ""


def test_the_block_carries_the_level(monkeypatch):
    years = {"dxy": _year(150.0), "us10y": _year(103.0), "vix": _year(20.0, base=30.0)}
    monkeypatch.setattr(signals, "_closes_for", lambda key: ("test", years[key]))
    block = signals.format_macro_block(signals.fetch_macro(), "en")
    assert "📍 DXY is at a 1-year high" in block
    assert "📍 VIX is at a 1-year low" in block
    assert "US10Y is" not in block.split("US10Y:")[1].split("\n", 1)[1]  # mid-range: no note


def test_yahoo_is_asked_for_a_year(monkeypatch):
    seen = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"chart": {"result": [{"indicators": {"quote": [{"close": [1.0, 2.0]}]}}]}}

    def fake_get(url, params=None, **kw):
        seen.update(params or {})
        return _Resp()

    monkeypatch.setattr(signals.requests, "get", fake_get)
    signals._fetch_yahoo_closes("^TNX")
    assert seen["range"] == "1y"
