import signals


CSV = """Date,Open,High,Low,Close,Volume
2026-06-06,100.0,101,99,100.0,0
2026-06-09,100.0,103,99,102.0,0
"""


class FakeResp:
    def __init__(self, text="", payload=None):
        self.text = text
        self._payload = payload
    def raise_for_status(self): pass
    def json(self): return self._payload


# ── provider parsers ────────────────────────────────────────────

def test_fetch_stooq_closes_parses(monkeypatch):
    monkeypatch.setattr(signals.requests, "get", lambda *a, **k: FakeResp(text=CSV))
    assert signals._fetch_stooq_closes("^vix") == [100.0, 102.0]


def test_fetch_stooq_closes_handles_garbage(monkeypatch):
    monkeypatch.setattr(signals.requests, "get", lambda *a, **k: FakeResp(text="<html>err</html>"))
    assert signals._fetch_stooq_closes("^vix") == []


def test_fetch_yahoo_closes_parses(monkeypatch):
    payload = {"chart": {"result": [{"indicators": {"quote": [{"close": [10.0, None, 11.0]}]}}]}}
    monkeypatch.setattr(signals.requests, "get", lambda *a, **k: FakeResp(payload=payload))
    assert signals._fetch_yahoo_closes("^VIX") == [10.0, 11.0]


# ── provider order: Yahoo primary, Stooq fallback ───────────────

def test_closes_for_prefers_yahoo(monkeypatch):
    monkeypatch.setattr(signals, "_fetch_yahoo_closes", lambda s: [10.0, 11.0])
    monkeypatch.setattr(signals, "_fetch_stooq_closes", lambda s: [99.0])
    src, closes = signals._closes_for("vix")
    assert closes == [10.0, 11.0] and src.startswith("yahoo:")


def test_closes_for_falls_back_to_stooq(monkeypatch):
    monkeypatch.setattr(signals, "_fetch_yahoo_closes", lambda s: [])
    monkeypatch.setattr(signals, "_fetch_stooq_closes", lambda s: [5.0, 6.0])
    src, closes = signals._closes_for("vix")
    assert closes == [5.0, 6.0] and not src.startswith("yahoo:")


def test_fetch_macro_builds_values(monkeypatch):
    monkeypatch.setattr(signals, "_fetch_yahoo_closes", lambda s: [100.0, 102.0])
    macro = signals.fetch_macro()
    for key in ("dxy", "us10y", "vix"):
        assert macro[key]["value"] == 102.0
        assert macro[key]["change_pct"] == 2.0
        assert macro[key]["change_abs"] == 2.0
        assert macro[key]["symbol"].startswith("yahoo:")


# ── fear score / label / bias ───────────────────────────────────

def test_fear_score_low_and_high():
    assert signals.fear_score({"vix": {"value": 12, "change_pct": 0}}) == 0.0
    assert signals.fear_score({"vix": {"value": 35, "change_pct": 0}}) == 100.0
    assert signals.fear_score({}) is None


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


# ── message block formatting ─────────────────────────────────────

def test_format_macro_block_contains_metrics():
    macro = {
        "dxy": {"value": 100.0, "change_pct": -0.05, "change_abs": -0.05},
        "us10y": {"value": 4.53, "change_pct": -0.53, "change_abs": -0.02},
        "vix": {"value": 19.87, "change_pct": 5.02, "change_abs": 0.95},
    }
    block = signals.format_macro_block(macro)
    # "&" is escaped for Telegram HTML mode; it renders as "&".
    assert "Macro &amp; Fear" in block
    assert "DXY" in block and "US10Y" in block and "VIX" in block
    assert "4.53%" in block and "pp" in block      # yield as percent + pp move
    assert "Fear:" in block and "Gold bias:" in block


def test_format_macro_block_empty(monkeypatch):
    assert signals.format_macro_block({}) == ""
    monkeypatch.setattr(signals, "fetch_macro", lambda: {})
    assert signals.format_macro_block() == ""


# ── Per-run macro cache ─────────────────────────────────────────

def test_macro_is_fetched_once_per_run(monkeypatch):
    """A run can want the block twice — the daily summary and the regime
    check — and these are DAILY closes, so the second fetch buys nothing."""
    calls = []

    def _closes(key):
        calls.append(key)
        return f"yahoo:{key}", [100.0, 101.0]

    monkeypatch.setattr(signals, "_closes_for", _closes)

    first = signals.fetch_macro()
    second = signals.fetch_macro()

    assert first == second
    assert len(calls) == len(signals.YAHOO_SYMBOLS)  # one pass, not two


def test_failed_macro_fetch_is_not_cached(monkeypatch):
    """Caching {} would suppress the macro block for the rest of the run."""
    outcome = {"closes": []}
    monkeypatch.setattr(signals, "_closes_for",
                        lambda key: (None, outcome["closes"]))

    assert signals.fetch_macro() == {}

    outcome["closes"] = [100.0, 101.0]
    assert signals.fetch_macro() != {}, "an outage was cached"


def test_reset_cache_forces_a_refetch(monkeypatch):
    calls = []
    monkeypatch.setattr(signals, "_closes_for",
                        lambda key: (calls.append(key), ("y", [1.0, 2.0]))[1])

    signals.fetch_macro()
    signals.reset_cache()
    signals.fetch_macro()

    assert len(calls) == len(signals.YAHOO_SYMBOLS) * 2
