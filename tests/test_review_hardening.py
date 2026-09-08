"""Regressions found in the whole-project review.

Each test pins one failure that was silent in production: a number that is not
a number, a command batch that ran twice, and a history row without a price.
"""
import bot_commands
import bot_core
import predictor
import storage


class _MemStore:
    def __init__(self, monkeypatch, writes_ok=True):
        self.files = {}
        self.write_calls = []
        monkeypatch.setattr(
            storage, "_read_file",
            lambda f, fresh=False: self.files.get(
                f, [] if f in (storage.PRICE_HISTORY_FILE, storage.BUY_LOG_FILE) else {}))

        def _write(f, d):
            self.write_calls.append(f)
            if writes_ok:
                self.files[f] = d
            return writes_ok

        monkeypatch.setattr(storage, "_write_file", _write)


def _capture(monkeypatch):
    sent = []
    monkeypatch.setattr(bot_core, "send_message", lambda text, cid="", **k: sent.append(text))
    return sent


# ── Non-finite numbers ──────────────────────────────────────────

def test_parse_amount_rejects_non_finite():
    assert bot_core.parse_amount("5000") == 5000.0
    assert bot_core.parse_amount(" 5,000 ") == 5000.0
    for bad in ("nan", "NaN", "inf", "-inf", "1e400", "abc", "", None):
        assert bot_core.parse_amount(bad) is None, bad


def test_alert_rejects_nan(monkeypatch):
    """`nan <= 0` and `nan <= spot` are both False, so it used to sail through."""
    _MemStore(monkeypatch)
    monkeypatch.setattr(bot_core.goldapi, "get_gold_price",
                        lambda *a, **k: (4500.0, 2400.0, 34.0))
    sent = _capture(monkeypatch)

    bot_core.cmd_alert("111", "above nan", "my")

    assert storage.get_user_alerts("111") == []
    assert "Usage" in sent[0]


def test_alert_rejects_infinity(monkeypatch):
    _MemStore(monkeypatch)
    monkeypatch.setattr(bot_core.goldapi, "get_gold_price",
                        lambda *a, **k: (4500.0, 2400.0, 34.0))
    _capture(monkeypatch)

    bot_core.cmd_alert("111", "above inf", "my")

    assert storage.get_user_alerts("111") == []


def test_setthreshold_rejects_nan(monkeypatch):
    """A NaN threshold makes `d >= threshold` false forever — alerts just stop."""
    store = _MemStore(monkeypatch)
    sent = _capture(monkeypatch)

    bot_core.cmd_setthreshold("111", "nan", "my")

    assert storage.BOT_STATE_FILE not in store.files
    assert "Usage" in sent[0]


def test_bought_rejects_infinity(monkeypatch):
    _MemStore(monkeypatch)
    monkeypatch.setattr(bot_core.goldapi, "get_gold_price",
                        lambda *a, **k: (4500.0, 2400.0, 34.0))
    _capture(monkeypatch)

    bot_core.cmd_bought("111", "inf", "my")

    assert storage._get_entries() == []


def test_bought_accepts_thousands_separator(monkeypatch):
    _MemStore(monkeypatch)
    monkeypatch.setattr(bot_core.goldapi, "get_gold_price",
                        lambda *a, **k: (4500.0, 2400.0, 34.0))
    _capture(monkeypatch)

    bot_core.cmd_bought("111", "5,000", "my")

    assert [e["amount_thb"] for e in storage._get_entries()] == [5000.0]


# ── Poller offset ───────────────────────────────────────────────

def _updates():
    return [{"update_id": 10, "message": {"text": "/price", "chat": {"id": "1"}}},
            {"update_id": 11, "message": {"text": "/price", "chat": {"id": "1"}}}]


def test_offset_is_committed_before_dispatch(monkeypatch):
    store = _MemStore(monkeypatch)
    monkeypatch.setattr(bot_core, "webhook_is_configured", lambda: False)
    monkeypatch.setattr(bot_core, "get_updates", lambda offset: _updates())

    seen = []

    def _dispatch(u):
        # The offset must already be persisted by the time a handler — which may
        # write to the portfolio — is allowed to run.
        assert store.files[storage.BOT_STATE_FILE]["update_offset"] == 12
        seen.append(u["update_id"])

    monkeypatch.setattr(bot_core, "dispatch_update", _dispatch)

    bot_commands.process_commands()

    assert seen == [10, 11]


def test_batch_is_skipped_when_offset_cannot_be_saved(monkeypatch):
    """A swallowed write used to replay every command, re-logging /bought."""
    _MemStore(monkeypatch, writes_ok=False)
    monkeypatch.setattr(bot_core, "webhook_is_configured", lambda: False)
    monkeypatch.setattr(bot_core, "get_updates", lambda offset: _updates())
    dispatched = []
    monkeypatch.setattr(bot_core, "dispatch_update", dispatched.append)

    bot_commands.process_commands()

    assert dispatched == []


# ── History rows with no price ──────────────────────────────────

_MIXED = [
    {"ts": "2026-01-01T10:00:00+07:00", "thb_gram": 4000.0, "usd_oz": 2350.0},
    {"ts": "2026-01-01T11:00:00+07:00"},                      # partial write
    {"ts": "2026-01-02T10:00:00+07:00", "thb_gram": 4020.0, "usd_oz": 2360.0},
    {"ts": "2026-01-02T11:00:00+07:00", "thb_gram": None},    # null price
    {"ts": "2026-01-03T10:00:00+07:00", "thb_gram": 4040.0, "usd_oz": 2370.0},
    {"ts": "2026-01-03T11:00:00+07:00", "thb_gram": 4045.0, "usd_oz": 2375.0},
    {"ts": "2026-01-03T12:00:00+07:00", "thb_gram": 4050.0, "usd_oz": 2380.0},
]


def test_priced_points_drops_rows_without_a_price():
    assert len(predictor.priced_points(_MIXED)) == 5
    assert predictor.priced_points([None, "x", {}]) == []


def test_analyze_and_trend_survive_a_bad_row():
    assert "error" not in predictor.analyze(_MIXED)
    assert predictor.get_trend_summary(_MIXED)["current"] == 4050.0


def test_history_command_survives_a_bad_row(monkeypatch):
    store = _MemStore(monkeypatch)
    store.files[storage.PRICE_HISTORY_FILE] = _MIXED
    sent = _capture(monkeypatch)

    bot_core.cmd_history("111", "7", "my")

    assert "2026-01-01: ฿4,000" in sent[0]
    assert "2026-01-03: ฿4,050" in sent[0]


# ── Error text is not handed to the public ──────────────────────

def test_command_error_detail_is_owner_only(monkeypatch):
    monkeypatch.setattr(bot_core, "TG_CHAT_ID", "999")
    monkeypatch.setattr(storage, "get_user_lang", lambda cid: "en")
    monkeypatch.setattr(bot_core, "cmd_price",
                        lambda cid, lang: (_ for _ in ()).throw(
                            RuntimeError("https://api.github.com/gists/SECRET_ID")))
    sent = _capture(monkeypatch)

    bot_core.dispatch_update({"message": {"text": "/price", "chat": {"id": "111"}}})
    assert "SECRET_ID" not in sent[0]

    sent.clear()
    bot_core.dispatch_update({"message": {"text": "/price", "chat": {"id": "999"}}})
    assert "SECRET_ID" in sent[0]
