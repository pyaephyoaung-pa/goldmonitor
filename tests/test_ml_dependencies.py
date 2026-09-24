"""numpy and scikit-learn are TRAINING-only dependencies.

Models are stored as plain numbers and scored with stdlib arithmetic, so
nothing on the inference path imports them — which is what lets the webhook
bundle drop them. These tests keep that true, and make a broken split loud
instead of silent.
"""
import datetime as _dt
import pathlib
import sys

import pytz

import bot_core
import gold_monitor
import goldapi
import predictor
import storage

BKK = pytz.timezone("Asia/Bangkok")
ROOT = pathlib.Path(__file__).resolve().parent.parent

ML_PACKAGES = ("numpy", "scikit-learn")


def _requirement_lines(name):
    return [ln.strip() for ln in (ROOT / name).read_text().splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]


# ── The split itself ────────────────────────────────────────────

def test_runtime_requirements_have_no_ml_packages():
    """The whole point: the webhook and the poller must not install these."""
    lines = " ".join(_requirement_lines("requirements.txt")).lower()
    for pkg in ML_PACKAGES:
        assert pkg not in lines, f"{pkg} is back in requirements.txt"


def test_ml_requirements_include_the_runtime_ones():
    lines = _requirement_lines("requirements-ml.txt")
    assert "-r requirements.txt" in lines
    joined = " ".join(lines).lower()
    for pkg in ML_PACKAGES:
        assert pkg in joined


def test_training_workflow_installs_the_ml_requirements():
    """gold_monitor.yml is the only job that trains; if it stops installing
    the extras, training stops with nothing but a log line to show for it."""
    wf = (ROOT / ".github/workflows/gold_monitor.yml").read_text()
    assert "requirements-ml.txt" in wf

    poller = (ROOT / ".github/workflows/bot_commands.yml").read_text()
    assert "requirements-ml.txt" not in poller, "the poller does not train"


# ── Inference really is stdlib ──────────────────────────────────

def test_inference_path_imports_nothing_heavy():
    """Import the modules the webhook loads with numpy and sklearn blocked."""
    blocked = ("numpy", "sklearn")

    class _Block:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in blocked:
                raise ImportError(f"{name} is blocked for this test")
            return None

    saved = {n: m for n, m in sys.modules.items() if n.split(".")[0] in blocked}
    for name in list(sys.modules):
        if name.split(".")[0] in blocked:
            del sys.modules[name]
    guard = _Block()
    sys.meta_path.insert(0, guard)
    try:
        for name in ("predictor", "bot_core", "storage", "gold_format",
                     "regime", "signals", "news", "events", "i18n", "goldapi"):
            sys.modules.pop(name, None)
            __import__(name)
        import predictor as fresh
        assert fresh.ml_available() is False
        leaf = {"left": [-1], "right": [-1], "feature": [-2],
                "threshold": [-2.0], "value": [0.8]}
        bundle = {"intercept": 0.0, "learning_rate": 1.0, "trees": [leaf]}
        assert 0.0 < fresh._score_bundle(bundle, [1.0]) < 1.0
    finally:
        sys.meta_path.remove(guard)
        sys.modules.update(saved)
        for name in ("predictor", "bot_core", "storage", "gold_format",
                     "regime", "signals", "news", "events", "i18n", "goldapi"):
            sys.modules.pop(name, None)
            __import__(name)


def test_ml_available_is_true_here():
    """The dev environment installs requirements-dev.txt, which pulls the ML
    extras in — so the tests that fit real models can run."""
    assert predictor.ml_available() is True


# ── A missing install is announced, not swallowed ───────────────

def _training_run(monkeypatch, store_files, watchdog=None):
    """Drive main() at 03:00 BKK with enough history to want training."""
    now = BKK.localize(_dt.datetime(2026, 6, 18, 3, 0))

    class _FakeDateTime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else now.astimezone(tz)

    files = dict(store_files)
    monkeypatch.setattr(
        storage, "_read_file",
        lambda f, fresh=False: files.get(
            f, [] if f in (storage.PRICE_HISTORY_FILE, storage.BUY_LOG_FILE) else {}))
    monkeypatch.setattr(storage, "_write_file",
                        lambda f, d: files.__setitem__(f, d) or True)
    monkeypatch.setattr(storage, "get_subscribers_and_prefs", lambda: ([], {}))
    monkeypatch.setattr(storage, "get_user_lang", lambda cid: "en")
    monkeypatch.setattr(storage, "pop_triggered_alerts", lambda *p: [])
    monkeypatch.setattr(goldapi, "get_gold_price", lambda retries=2: (4500.0, 2400.0, 34.0))
    monkeypatch.setattr(storage, "datetime", _FakeDateTime)
    monkeypatch.setattr(gold_monitor, "datetime", _FakeDateTime)
    monkeypatch.setattr(gold_monitor, "TG_BOT_TOKEN", "x")
    monkeypatch.setattr(gold_monitor, "TG_CHAT_ID", "999")
    monkeypatch.setattr(gold_monitor.signals, "format_macro_block", lambda *a, **k: "")
    monkeypatch.setattr(bot_core, "warn_owner_if_webhook_broken",
                        watchdog or (lambda st: False))

    sent = []
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="": (sent.append(text), {"ok": True})[1])
    gold_monitor.main()
    return sent, files


def _store_with_history():
    base = BKK.localize(_dt.datetime(2026, 6, 18, 3, 0))
    history = [{"ts": (base - _dt.timedelta(hours=150 - i)).isoformat(),
                "thb_gram": 4000.0 + i, "usd_oz": 2400.0 + i,
                "hour": i % 24, "weekday": i % 7} for i in range(150)]
    return {
        storage.PRICE_HISTORY_FILE: history,
        storage.DAY_STATE_FILE: {
            "date": "2026-06-18", "open_price": 4500.0, "day_low": 4500.0,
            "day_high": 4500.0, "prev_close": 4500.0, "last_price": 4500.0,
            "morning_sent": True, "evening_sent": True, "notified_gap": True},
    }


def test_owner_is_told_when_training_deps_are_missing(monkeypatch):
    monkeypatch.setattr(predictor, "ml_available", lambda: False)
    monkeypatch.setattr(predictor, "train_model",
                        lambda h: (_ for _ in ()).throw(
                            AssertionError("must not train without deps")))

    sent, files = _training_run(monkeypatch, _store_with_history())

    assert any("requirements-ml.txt" in m for m in sent), sent
    # Stamped so the owner is told once a day, not on all twelve 03:xx runs.
    assert files[storage.MODEL_DATA_FILE]["ml_warned_on"] == "2026-06-18"


def test_the_warning_is_not_repeated_the_same_day(monkeypatch):
    monkeypatch.setattr(predictor, "ml_available", lambda: False)
    store = _store_with_history()
    store[storage.MODEL_DATA_FILE] = {"ml_warned_on": "2026-06-18"}

    sent, _ = _training_run(monkeypatch, store)

    assert not any("requirements-ml.txt" in m for m in sent)


def test_the_webhook_watchdog_still_runs_after_the_ml_block(monkeypatch):
    """The ML branch must not return early — the watchdog lives below it."""
    monkeypatch.setattr(predictor, "ml_available", lambda: False)
    checked = []

    _training_run(monkeypatch, _store_with_history(),
                  watchdog=lambda st: bool(checked.append(1)))

    assert checked == [1]


def test_a_null_ml_warned_on_still_warns(monkeypatch):
    """model_data.json holds nulls by design ("last_trained": None on a fresh
    file). A key stored as null came back from .get() as None, and None[:10]
    raised TypeError — in the one branch whose job is to raise the alarm."""
    monkeypatch.setattr(predictor, "ml_available", lambda: False)
    store = _store_with_history()
    store[storage.MODEL_DATA_FILE] = {"ml_warned_on": None, "last_trained": None}

    sent, files = _training_run(monkeypatch, store)

    assert any("requirements-ml.txt" in m for m in sent), sent
    assert files[storage.MODEL_DATA_FILE]["ml_warned_on"] == "2026-06-18"
