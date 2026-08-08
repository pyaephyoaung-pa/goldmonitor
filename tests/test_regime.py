"""Tests for market-regime detection (volatility + driver divergence)."""

import random
from datetime import datetime, timedelta

import pytest
import pytz

import bot_core
import i18n
import regime
import storage

BKK = pytz.timezone("Asia/Bangkok")


def _history(returns_pct, start=4000.0):
    """Build a price history that realises the given sequence of % returns."""
    now = datetime.now(BKK)
    price = start
    out = [{"ts": (now - timedelta(hours=len(returns_pct))).isoformat(),
            "thb_gram": round(price, 4)}]
    for i, r in enumerate(returns_pct):
        price *= (1 + r / 100.0)
        out.append({"ts": (now - timedelta(hours=len(returns_pct) - 1 - i)).isoformat(),
                    "thb_gram": round(price, 4)})
    return out


def _calm(n, sigma=0.05, seed=1):
    rng = random.Random(seed)
    return [rng.gauss(0, sigma) for _ in range(n)]


# ── returns / stdev ─────────────────────────────────────────────

def test_returns_are_percent_changes():
    assert regime.returns([100.0, 101.0, 99.99]) == pytest.approx([1.0, -1.0], rel=1e-3)


def test_returns_skips_zero_denominator():
    assert regime.returns([0.0, 5.0, 10.0]) == pytest.approx([100.0])


def test_stdev_of_short_series_is_zero():
    assert regime._stdev([]) == 0.0
    assert regime._stdev([1.0]) == 0.0


# ── Availability ────────────────────────────────────────────────

def test_unavailable_without_enough_history():
    out = regime.vol_regime(_history(_calm(10)))
    assert out["available"] is False
    assert out["need"] == regime.MIN_BASELINE + regime.SHORT_WINDOW
    assert out["have"] < out["need"]


def test_available_once_baseline_is_long_enough():
    out = regime.vol_regime(_history(_calm(regime.MIN_BASELINE + regime.SHORT_WINDOW)))
    assert out["available"] is True


def test_ignores_malformed_entries():
    hist = _history(_calm(80))
    hist.insert(5, {"ts": "2026-01-01T00:00:00+07:00"})   # no thb_gram
    hist.insert(9, "not a dict")
    assert regime.vol_regime(hist)["available"] is True


# ── Regime classification ───────────────────────────────────────

def test_quiet_market_is_not_unusual():
    out = regime.vol_regime(_history(_calm(200)))
    assert out["level"] in ("calm", "normal")
    assert regime.is_unusual(out) is False


def test_volatility_spike_is_detected():
    """Calm baseline, then six violent hours."""
    rets = _calm(200) + [1.2, -1.5, 1.8, -1.1, 1.4, -1.6]
    out = regime.vol_regime(_history(rets))
    assert out["level"] == "extreme", out
    assert out["ratio"] > regime.EXTREME_ABOVE
    assert regime.is_unusual(out) is True


def test_baseline_excludes_the_recent_window():
    """A spike must not be allowed to inflate its own baseline.

    If the recent window were included in the baseline, the ratio would be
    pulled toward 1 and a real spike could go unreported.
    """
    rets = _calm(200) + [1.2, -1.5, 1.8, -1.1, 1.4, -1.6]
    hist = _history(rets)
    out = regime.vol_regime(hist)

    all_rets = regime.returns([h["thb_gram"] for h in hist])
    naive_ratio = regime._stdev(all_rets[-6:]) / regime._stdev(all_rets)
    assert out["ratio"] > naive_ratio, "excluded baseline must be more sensitive"


def test_flat_market_does_not_divide_by_zero():
    """Perfectly flat prices would give a zero baseline without the floor."""
    out = regime.vol_regime(_history([0.0] * 200))
    assert out["available"] is True
    assert out["baseline_vol"] == regime.VOL_FLOOR
    assert out["ratio"] == 0.0
    assert regime.is_unusual(out) is False


def test_single_bar_shock_flagged_even_when_ratio_is_moderate():
    rets = _calm(200) + [0.02, -0.01, 0.03, -0.02, 0.01, 2.5]
    out = regime.vol_regime(_history(rets))
    assert out["shock"] is True
    assert out["sigma"] >= regime.SHOCK_SIGMA
    assert regime.is_unusual(out) is True


def test_is_unusual_false_when_unavailable():
    assert regime.is_unusual({"available": False}) is False
    assert regime.is_unusual({}) is False


# ── Driver divergence ───────────────────────────────────────────

SAFE_HAVEN = {"dxy": {"change_pct": 0.40}, "us10y": {"change_abs": 0.06}}
SUPPORTIVE = {"dxy": {"change_pct": -0.40}, "us10y": {"change_abs": -0.06}}


def test_gold_up_against_both_headwinds_is_safe_haven():
    assert regime.divergence(0.9, SAFE_HAVEN) == "regime.div.safe_haven"


def test_gold_down_despite_both_tailwinds_is_liquidation():
    assert regime.divergence(-0.9, SUPPORTIVE) == "regime.div.liquidation"


def test_normal_inverse_relationship_is_not_divergence():
    """Gold down while the dollar rises is textbook — nothing to report."""
    assert regime.divergence(-0.9, SAFE_HAVEN) is None
    assert regime.divergence(0.9, SUPPORTIVE) is None


def test_small_moves_are_inside_the_deadband():
    tiny = {"dxy": {"change_pct": 0.01}, "us10y": {"change_abs": 0.01}}
    assert regime.divergence(0.05, tiny) is None


def test_divergence_needs_both_gold_and_macro():
    assert regime.divergence(None, SAFE_HAVEN) is None
    assert regime.divergence(0.9, None) is None
    assert regime.divergence(0.9, {}) is None
    assert regime.divergence(0.9, {"vix": {"change_pct": 5}}) is None


def test_yields_use_absolute_points_not_percent():
    """A 0.06pp yield move is meaningful; 0.06 PERCENT would not be.

    change_pct is deliberately ignored for yields — reading the wrong field
    would make this fire on noise.
    """
    pct_only = {"dxy": {"change_pct": 0.40},
                "us10y": {"change_pct": 5.0, "change_abs": 0.0}}
    assert regime.divergence(0.9, pct_only) is None


# ── Rendering ───────────────────────────────────────────────────

def test_format_block_empty_when_nothing_notable():
    calm = regime.vol_regime(_history(_calm(200)))
    assert regime.format_block(calm, None, "en") == ""


def test_format_block_reports_spike_and_divergence():
    rets = _calm(200) + [1.2, -1.5, 1.8, -1.1, 1.4, -1.6]
    out = regime.vol_regime(_history(rets))
    block = regime.format_block(out, "regime.div.safe_haven", "en")
    assert "Volatility" in block
    assert "safe-haven" in block


def test_format_block_localised():
    rets = _calm(200) + [1.2, -1.5, 1.8, -1.1, 1.4, -1.6]
    out = regime.vol_regime(_history(rets))
    th = regime.format_block(out, "regime.div.safe_haven", "th")
    my = regime.format_block(out, "regime.div.safe_haven", "my")
    assert "ความผันผวน" in th
    assert "ဈေးလှုပ်ရှားမှု" in my


def test_divergence_alone_renders_without_a_spike():
    calm = regime.vol_regime(_history(_calm(200)))
    block = regime.format_block(calm, "regime.div.liquidation", "en")
    assert "forced selling" in block


# ── /macro integration ──────────────────────────────────────────

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


def test_macro_includes_regime(monkeypatch):
    store = _MemStore(monkeypatch)
    store.files[storage.PRICE_HISTORY_FILE] = _history(_calm(200))
    sent = _capture(monkeypatch)
    monkeypatch.setattr(bot_core.signals, "fetch_macro",
                        lambda: {"dxy": {"value": 104.0, "change_pct": -0.1,
                                         "change_abs": -0.1}})

    bot_core.cmd_macro("111", "en")

    assert "Market Regime" in sent[-1]
    assert "Volatility" in sent[-1]


def test_macro_still_works_when_fetch_fails(monkeypatch):
    """Regime needs no network, so /macro must not go dark with macro down."""
    store = _MemStore(monkeypatch)
    store.files[storage.PRICE_HISTORY_FILE] = _history(_calm(200))
    sent = _capture(monkeypatch)
    monkeypatch.setattr(bot_core.signals, "fetch_macro", lambda: {})

    bot_core.cmd_macro("111", "en")

    assert "Market Regime" in sent[-1]
    assert "unavailable" not in sent[-1].lower()


def test_macro_reports_unavailable_when_nothing_at_all(monkeypatch):
    store = _MemStore(monkeypatch)
    store.files[storage.PRICE_HISTORY_FILE] = []
    sent = _capture(monkeypatch)
    monkeypatch.setattr(bot_core.signals, "fetch_macro", lambda: {})

    bot_core.cmd_macro("111", "en")

    assert "Could not fetch macro data" in sent[-1]


def test_macro_shows_collecting_progress(monkeypatch):
    """Short history: say how far off the baseline is, not a fake number."""
    store = _MemStore(monkeypatch)
    store.files[storage.PRICE_HISTORY_FILE] = _history(_calm(10))
    sent = _capture(monkeypatch)
    monkeypatch.setattr(bot_core.signals, "fetch_macro",
                        lambda: {"dxy": {"value": 104.0, "change_pct": -0.1,
                                         "change_abs": -0.1}})

    bot_core.cmd_macro("111", "en")

    assert "Collecting data" in sent[-1]
    assert f"/{regime.MIN_BASELINE + regime.SHORT_WINDOW}" in sent[-1]


# ── Display caps ────────────────────────────────────────────────

def test_display_caps_avoid_absurd_numbers():
    """Against a very quiet baseline the honest arithmetic gets silly."""
    assert regime.display_ratio(3.2) == "3.2"
    assert regime.display_ratio(30.2) == "15+"
    assert regime.display_sigma(4.25) == "4.2"
    assert regime.display_sigma(30.4) == "10+"


def test_capped_values_reach_the_message():
    rets = _calm(200) + [1.2, -1.5, 1.8, -1.1, 1.4, -1.6]
    out = regime.vol_regime(_history(rets))
    assert out["ratio"] > regime.RATIO_DISPLAY_CAP, "fixture should exceed the cap"
    block = regime.format_block(out, None, "en")
    assert "15+" in block
    assert str(out["ratio"]) not in block, "raw value must not leak into the text"
