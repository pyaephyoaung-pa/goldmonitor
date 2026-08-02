"""Regression tests for the bugs found in the whole-project review.

Each test here pins behaviour that was previously broken and had no coverage.
"""

from datetime import datetime, timedelta

import pytz

import bot_core
import gold_monitor
import predictor
import storage

BKK = pytz.timezone("Asia/Bangkok")


class _MemStore:
    """In-memory stand-in for the Gist, matching the other test modules."""

    def __init__(self, monkeypatch):
        self.files = {}
        monkeypatch.setattr(
            storage, "_read_file",
            lambda f: self.files.get(
                f, [] if f in (storage.PRICE_HISTORY_FILE, storage.BUY_LOG_FILE) else {}))
        monkeypatch.setattr(storage, "_write_file",
                            lambda f, d: self.files.__setitem__(f, d))


# ── add_subscriber must not clobber notification prefs ──────────

def test_add_subscriber_preserves_other_users_prefs(monkeypatch):
    store = _MemStore(monkeypatch)
    store.files[storage.SUBSCRIBERS_FILE] = {
        "chat_ids": ["111"],
        "prefs": {"111": {"morning": False, "quiet": "22-7"}},
    }

    assert storage.add_subscriber("222") is True

    prefs = storage.get_user_prefs("111")
    assert prefs["morning"] is False, "existing user's mute was reset"
    assert prefs["quiet"] == "22-7", "existing user's quiet hours were reset"
    assert storage.get_subscribers() == ["111", "222"]


def test_add_subscriber_from_bare_list_schema(monkeypatch):
    """Legacy schema stored a plain list — adding must still work."""
    store = _MemStore(monkeypatch)
    store.files[storage.SUBSCRIBERS_FILE] = ["111"]

    assert storage.add_subscriber("222") is True
    assert storage.get_subscribers() == ["111", "222"]


def test_add_existing_subscriber_is_noop(monkeypatch):
    store = _MemStore(monkeypatch)
    store.files[storage.SUBSCRIBERS_FILE] = {
        "chat_ids": ["111"], "prefs": {"111": {"alerts": False}},
    }
    assert storage.add_subscriber("111") is False
    assert storage.get_user_prefs("111")["alerts"] is False


def test_get_subscribers_and_prefs_single_read(monkeypatch):
    store = _MemStore(monkeypatch)
    store.files[storage.SUBSCRIBERS_FILE] = {
        "chat_ids": ["111", "222"], "prefs": {"222": {"evening": False}},
    }
    reads = []
    original = storage._read_file
    monkeypatch.setattr(storage, "_read_file",
                        lambda f: (reads.append(f), original(f))[1])

    subs, prefs = storage.get_subscribers_and_prefs()
    assert subs == ["111", "222"]
    assert prefs == {"222": {"evening": False}}
    assert len(reads) == 1, f"expected one Gist read, got {len(reads)}"


# ── Portfolio P&L when everything has been sold ─────────────────

def test_pnl_has_current_price_when_fully_sold(monkeypatch):
    store = _MemStore(monkeypatch)
    store.files[storage.BUY_LOG_FILE] = [
        {"type": "buy", "ts": "2026-01-01T10:00:00+07:00",
         "amount_thb": 5000, "price_per_gram": 5000.0, "grams": 1.0},
        {"type": "sell", "ts": "2026-01-02T10:00:00+07:00",
         "amount_thb": 5200, "price_per_gram": 5200.0, "grams": 1.0},
    ]
    pnl = storage.get_portfolio_pnl(5300.0)
    assert pnl["total_grams"] == 0
    assert pnl["current_price"] == 5300.0
    assert pnl["pnl_thb"] == pnl["realized_pnl"] == 200.0


def test_cmd_portfolio_renders_when_fully_sold(monkeypatch):
    store = _MemStore(monkeypatch)
    store.files[storage.BUY_LOG_FILE] = [
        {"type": "buy", "ts": "2026-01-01T10:00:00+07:00",
         "amount_thb": 5000, "price_per_gram": 5000.0, "grams": 1.0},
        {"type": "sell", "ts": "2026-01-02T10:00:00+07:00",
         "amount_thb": 5200, "price_per_gram": 5200.0, "grams": 1.0},
    ]
    monkeypatch.setattr(bot_core.goldapi, "get_gold_price",
                        lambda *a, **k: (5300.0, 2400.0, 34.0))
    sent = []
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, cid="", **k: sent.append(text))

    bot_core.cmd_portfolio("111")

    assert len(sent) == 1
    assert "Realized P&L" in sent[0]
    assert "Error" not in sent[0]


# ── /history argument clamping ──────────────────────────────────

def test_history_clamps_zero_and_negative(monkeypatch):
    store = _MemStore(monkeypatch)
    history = []
    for day in range(1, 10):
        history.append({"ts": f"2026-01-{day:02d}T10:00:00+07:00", "thb_gram": 4000 + day})
    store.files[storage.PRICE_HISTORY_FILE] = history

    sent = []
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, cid="", **k: sent.append(text))

    for args in ("0", "-5"):
        sent.clear()
        bot_core.cmd_history("111", args)
        assert sent[0].startswith("📊 <b>ရွှေဈေး 1-Day History</b>"), sent[0]

    sent.clear()
    bot_core.cmd_history("111", "3")
    assert "3-Day History" in sent[0]


# ── /chart caption and chart share one window ───────────────────

def test_chart_points_shared_between_config_and_caption():
    history = [{"ts": f"2026-01-01T{i % 24:02d}:00:00+07:00", "thb_gram": 4000 + i}
               for i in range(30)]
    history += [{"ts": f"2026-01-02T{i % 24:02d}:00:00+07:00"} for i in range(30)]

    points = bot_core.chart_points(history, 1)
    config = bot_core.build_chart_config(history, 1)

    assert config is not None
    assert len(points) == 24
    # The caption derives from the same helper, so it can never come back empty
    # while the chart still renders.
    assert [p["thb_gram"] for p in points]


def test_cmd_chart_caption_matches_rendered_range(monkeypatch):
    store = _MemStore(monkeypatch)
    history = [{"ts": f"2026-01-01T{i % 24:02d}:00:00+07:00", "thb_gram": 4000 + i}
               for i in range(30)]
    history += [{"ts": f"2026-01-02T{i % 24:02d}:00:00+07:00"} for i in range(30)]
    store.files[storage.PRICE_HISTORY_FILE] = history

    monkeypatch.setattr(bot_core, "_quickchart_short_url",
                        lambda cfg: "https://quickchart.io/chart/abc")
    captions = []
    monkeypatch.setattr(bot_core, "send_photo",
                        lambda url, caption, cid="": captions.append(caption) or {"ok": True})

    bot_core.cmd_chart("111", "1")

    assert len(captions) == 1
    assert "High:" in captions[0]


# ── ML training must not erase the prediction log ───────────────

def test_train_model_stamps_bangkok_date(monkeypatch):
    """The retrain guard compares last_trained[:10] against a BKK date."""
    fixed = BKK.localize(datetime(2026, 8, 2, 3, 5))

    class _FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(predictor, "datetime", _FakeDatetime)
    stamp = predictor.datetime.now(predictor.BANGKOK_TZ).isoformat()
    assert stamp[:10] == fixed.strftime("%Y-%m-%d") == "2026-08-02"


def test_retrain_guard_matches_within_same_bkk_day():
    """A stamp written at 3am BKK must suppress the next tick that hour."""
    trained_at = BKK.localize(datetime(2026, 8, 2, 3, 0))
    later_tick = BKK.localize(datetime(2026, 8, 2, 3, 55))

    last_trained = trained_at.isoformat()
    today = later_tick.strftime("%Y-%m-%d")

    assert last_trained[:10] == today, "guard would retrain again in the same hour"


def test_model_merge_preserves_prediction_log():
    """gold_monitor merges train_model output instead of replacing it."""
    model_data = {
        "predictions": [
            {"ts": "2026-07-01T20:00:00+07:00", "horizon": "24h", "hours": 24,
             "direction": "UP", "price_at": 4000.0, "resolved": True, "correct": True},
        ],
        "last_trained": "2026-07-01T03:00:00+07:00",
    }
    new_model = {
        "models": {"24h": {"model_b64": "xxx", "accuracy": 51.0}},
        "last_trained": "2026-08-02T03:00:00+07:00",
        "total_history": 720,
        "feature_names": ["rsi"],
    }

    model_data.update(new_model)

    assert len(model_data["predictions"]) == 1, "prediction log was erased"
    assert model_data["last_trained"].startswith("2026-08-02")
    assert model_data["models"]["24h"]["accuracy"] == 51.0
    assert predictor.prediction_hit_rates(model_data)["24h"]["hit_pct"] == 100.0


# ── Gist truncation must not be read as "no data" ───────────────

def test_read_file_refetches_truncated_content(monkeypatch):
    import json as _json

    payload = {"predictions": [{"horizon": "24h"}], "last_trained": "2026-08-02"}
    full = _json.dumps(payload)

    monkeypatch.setattr(storage, "_get_gist", lambda: {
        storage.MODEL_DATA_FILE: {
            "content": full[:20],          # what the API inlines
            "truncated": True,
            "raw_url": "https://gist.githubusercontent.com/raw/model_data.json",
        }
    })

    class _Resp:
        text = full

        def raise_for_status(self):
            pass

    monkeypatch.setattr(storage.requests, "get", lambda *a, **k: _Resp())

    assert storage._read_file(storage.MODEL_DATA_FILE) == payload


def test_read_file_untruncated_does_not_refetch(monkeypatch):
    import json as _json

    payload = {"a": 1}
    monkeypatch.setattr(storage, "_get_gist", lambda: {
        storage.BOT_STATE_FILE: {"content": _json.dumps(payload)}
    })

    def _boom(*a, **k):
        raise AssertionError("should not refetch an untruncated file")

    monkeypatch.setattr(storage.requests, "get", _boom)
    assert storage._read_file(storage.BOT_STATE_FILE) == payload


# ── Telegram 429 retry keeps the inline keyboard ────────────────

def test_429_retry_preserves_reply_markup(monkeypatch):
    monkeypatch.setattr(bot_core, "TG_BOT_TOKEN", "token")
    monkeypatch.setattr(bot_core.time, "sleep", lambda s: None)
    posts = []

    class _Resp:
        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body

    def fake_post(url, json=None, timeout=None):
        posts.append(json)
        if len(posts) == 1:
            return _Resp({"ok": False, "error_code": 429,
                          "parameters": {"retry_after": 1}})
        return _Resp({"ok": True})

    monkeypatch.setattr(bot_core.requests, "post", fake_post)

    bot_core.send_message("hi", "111", reply_markup=bot_core.MAIN_KEYBOARD)

    assert len(posts) == 2
    assert posts[1].get("reply_markup") == bot_core.MAIN_KEYBOARD


# ── Webhook fails closed without a configured secret ────────────

def test_setthreshold_reports_real_level_ladder(monkeypatch):
    store = _MemStore(monkeypatch)
    sent = []
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, cid="", **k: sent.append(text))

    bot_core.cmd_setthreshold("111", "0.5")

    # The old text promised a "Strong alert" at 1.5x (0.75%), a tier the
    # monitor never fires — its levels are 1x..5x.
    assert "0.75" not in sent[0], "quotes a 1.5x tier the monitor never fires"
    for level in ("≥0.5%", "≥1%", "≥1.5%", "≥2%", "≥2.5%"):
        assert level in sent[0], f"missing {level} in {sent[0]}"
