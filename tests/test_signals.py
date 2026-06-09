import signals


CSV = """Date,Open,High,Low,Close,Volume
2026-06-06,100.0,101,99,100.0,0
2026-06-09,100.0,103,99,102.0,0
"""


class FakeResp:
    def __init__(self, text): self.text = text
    def raise_for_status(self): pass


def test_fetch_stooq_closes_parses(monkeypatch):
    monkeypatch.setattr(signals.requests, "get", lambda *a, **k: FakeResp(CSV))
    closes = signals._fetch_stooq_closes("^vix")
    assert closes == [100.0, 102.0]


def test_fetch_stooq_closes_handles_garbage(monkeypatch):
    monkeypatch.setattr(signals.requests, "get", lambda *a, **k: FakeResp("<html>error</html>"))
    assert signals._fetch_stooq_closes("^vix") == []


def test_fetch_macro_builds_value_and_change(monkeypatch):
    monkeypatch.setattr(signals, "_fetch_stooq_closes", lambda sym: [100.0, 102.0])
    macro = signals.fetch_macro()
    for key in ("dxy", "us10y", "vix"):
        assert macro[key]["value"] == 102.0
        assert macro[key]["change_pct"] == 2.0


def test_fear_score_low_and_high():
    low = signals.fear_score({"vix": {"value": 12, "change_pct": 0}})
    high = signals.fear_score({"vix": {"value": 35, "change_pct": 0}})
    assert low == 0.0
    assert high == 100.0
    assert signals.fear_score({}) is None  # no VIX


def test_fear_score_clamped():
    assert signals.fear_score({"vix": {"value": 60, "change_pct": 20}}) == 100.0
    assert signals.fear_score({"vix": {"value": 5, "change_pct": -50}}) == 0.0


def test_fear_label_bands():
    assert signals.fear_label(10) == "Calm"
    assert signals.fear_label(30) == "Normal"
    assert signals.fear_label(60) == "Elevated"
    assert signals.fear_label(90) == "High fear"
    assert signals.fear_label(None) == "n/a"


def test_gold_bias_directions():
    assert "tailwind" in signals.gold_bias({"dxy": {"change_pct": -0.5}, "us10y": {"change_pct": -0.3}})
    assert "headwind" in signals.gold_bias({"dxy": {"change_pct": 0.5}, "us10y": {"change_pct": 0.4}})
    assert signals.gold_bias({"dxy": {"change_pct": 0.5}, "us10y": {"change_pct": -0.4}}) == "mixed"
    assert signals.gold_bias({}) is None


def test_format_macro_block_contains_metrics():
    macro = {
        "dxy": {"value": 104.2, "change_pct": 0.3},
        "us10y": {"value": 42.1, "change_pct": -0.5},
        "vix": {"value": 18.0, "change_pct": 5.0},
    }
    block = signals.format_macro_block(macro)
    assert "Macro & Fear" in block
    assert "DXY" in block and "US10Y" in block and "VIX" in block
    assert "Fear:" in block and "Gold bias:" in block


def test_format_macro_block_empty_when_no_data(monkeypatch):
    assert signals.format_macro_block({}) == ""
    monkeypatch.setattr(signals, "fetch_macro", lambda: {})
    assert signals.format_macro_block() == ""
