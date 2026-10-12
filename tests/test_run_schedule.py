"""The monitor has to notice when GitHub does not run it on time.

Measured over 34 days in Sep–Oct 2026: the workflow asks for a run every 5
minutes, and GitHub delivered 4–8 a day — a median of 4 hours apart, up to 9.
All 200 runs succeeded, so nothing looked wrong. Price alerts landed hours
late, the evening summary was skipped on 6 of 33 days, and the 3am retrain
(which only ran inside the 03:00 hour) ran on 9.
"""
import datetime as _dt

import pytz

import bot_core
import gold_monitor
import predictor
import storage
from test_ml_dependencies import _store_with_history, _training_run

BKK = pytz.timezone("Asia/Bangkok")
NOW = BKK.localize(_dt.datetime(2026, 6, 18, 10, 0))


def _ago(**delta):
    return (NOW - _dt.timedelta(**delta)).isoformat()


def _check(monkeypatch, state):
    sent = []
    monkeypatch.setattr(gold_monitor, "TG_CHAT_ID", "999")
    monkeypatch.setattr(storage, "get_user_lang", lambda cid: "en")
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="": sent.append((chat_id, text)))
    gold_monitor.warn_owner_if_runs_lag(state, NOW)
    return sent


# ── The owner hears about a late run ────────────────────────────

def test_a_run_hours_after_the_previous_one_tells_the_owner(monkeypatch):
    state = {"last_run_at": _ago(hours=4, minutes=3)}
    sent = _check(monkeypatch, state)
    assert len(sent) == 1 and sent[0][0] == "999"
    assert "4h 3m" in sent[0][1]
    assert state["run_gap_warned_at"] == NOW.isoformat()


def test_a_run_on_schedule_says_nothing(monkeypatch):
    state = {"last_run_at": _ago(minutes=6)}
    assert _check(monkeypatch, state) == []
    assert "run_gap_warned_at" not in state


def test_the_owner_is_told_at_most_twice_a_day(monkeypatch):
    """GitHub's lag is chronic, not a one-off: one warning per run would be
    four to eight a day until the schedule is fixed."""
    state = {"last_run_at": _ago(hours=4), "run_gap_warned_at": _ago(hours=5)}
    assert _check(monkeypatch, state) == []
    state["run_gap_warned_at"] = _ago(hours=13)
    assert len(_check(monkeypatch, state)) == 1


def test_an_unreadable_warning_stamp_does_not_mute_the_warning(monkeypatch):
    state = {"last_run_at": _ago(hours=4), "run_gap_warned_at": "garbage"}
    assert len(_check(monkeypatch, state)) == 1


def test_no_previous_run_or_a_bad_stamp_is_not_an_error(monkeypatch):
    for state in ({}, {"last_run_at": None}, {"last_run_at": "garbage"},
                  {"last_run_at": 12345}):
        assert _check(monkeypatch, state) == []


# ── When the previous run happened is remembered ────────────────

def test_every_run_records_when_it_ran(monkeypatch):
    monkeypatch.setattr(predictor, "ml_available", lambda: False)
    _, files = _training_run(monkeypatch, _store_with_history())
    assert files[storage.DAY_STATE_FILE]["last_run_at"] == "2026-06-18T03:00:00+07:00"


def test_a_late_run_warns_from_inside_the_monitor(monkeypatch):
    monkeypatch.setattr(predictor, "ml_available", lambda: False)
    store = _store_with_history()
    store[storage.DAY_STATE_FILE]["last_run_at"] = "2026-06-17T21:30:00+07:00"

    sent, files = _training_run(monkeypatch, store)

    assert any("No completed check for 5h 30m" in m for m in sent), sent
    assert files[storage.DAY_STATE_FILE]["run_gap_warned_at"].startswith("2026-06-18T03:00")


def test_the_last_run_survives_midnight(monkeypatch):
    """The day state resets at midnight; when the last run happened does not."""
    yesterday = {"date": "2026-06-17", "last_price": 4000.0,
                 "last_run_at": "2026-06-17T23:58:00+07:00",
                 "run_gap_warned_at": "2026-06-17T12:00:00+07:00"}

    class _Tomorrow(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is None else NOW.astimezone(tz)

    monkeypatch.setattr(storage, "datetime", _Tomorrow)
    monkeypatch.setattr(storage, "_read_file", lambda f, fresh=False: dict(yesterday))

    state = storage.load_day_state()
    assert state["date"] == "2026-06-18" and state["prev_close"] == 4000.0
    assert state["last_run_at"] == yesterday["last_run_at"]
    assert state["run_gap_warned_at"] == yesterday["run_gap_warned_at"]


# ── The daily retrain no longer needs a run inside the 03:00 hour ──

def _at(hour):
    return BKK.localize(_dt.datetime(2026, 6, 18, hour, 0))


def _counting_trainer(monkeypatch, result):
    calls = []

    def fake(history):
        calls.append(len(history))
        return result
    monkeypatch.setattr(predictor, "train_model", fake)
    return calls


def test_the_first_run_after_3am_trains(monkeypatch):
    calls = _counting_trainer(monkeypatch, {
        "models": {}, "last_trained": _at(10).isoformat()})

    _, files = _training_run(monkeypatch, _store_with_history(), at=_at(10))

    assert len(calls) == 1
    stored = files[storage.MODEL_DATA_FILE]
    assert stored["last_trained"].startswith("2026-06-18")
    assert stored["train_attempted_on"] == "2026-06-18"
    # The TA track record rides on the same block.
    assert stored["ta_track"]["computed"].startswith("2026-06-18T10:00")


def test_nothing_trains_before_3am(monkeypatch):
    calls = _counting_trainer(monkeypatch, {"models": {}})
    _training_run(monkeypatch, _store_with_history(), at=_at(2))
    assert calls == []


def test_a_training_that_produced_nothing_is_not_redone_all_day(monkeypatch):
    """Same history, same outcome: without the stamp, every run from 03:00 to
    midnight would refit three models just to fail again."""
    calls = _counting_trainer(monkeypatch, None)

    _, files = _training_run(monkeypatch, _store_with_history(), at=_at(4))
    assert len(calls) == 1
    assert files[storage.MODEL_DATA_FILE]["train_attempted_on"] == "2026-06-18"

    store = _store_with_history()
    store[storage.MODEL_DATA_FILE] = files[storage.MODEL_DATA_FILE]
    _training_run(monkeypatch, store, at=_at(9))
    assert len(calls) == 1


def test_a_model_trained_today_is_not_retrained(monkeypatch):
    calls = _counting_trainer(monkeypatch, {"models": {}})
    store = _store_with_history()
    store[storage.MODEL_DATA_FILE] = {"last_trained": _at(3).isoformat()}
    _training_run(monkeypatch, store, at=_at(15))
    assert calls == []
