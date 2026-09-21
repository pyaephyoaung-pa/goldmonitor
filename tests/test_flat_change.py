"""A price that did not move is shown as flat, everywhere.

Six call sites spelled the arrow inline and three disagreed: the chart caption
and the weekly recap called an unchanged price a RISE, the evening summary
called it a FALL. Gold can close a day flat to the satang, so each was
reachable. They all go through gold_format.change_arrow now.

Also here: gold_monitor._bot_state is bound before the try that fills it.
"""
import datetime as _dt
import importlib

import pytz

import bot_core
import gold_monitor
import goldapi
import storage
from gold_format import change_arrow

BKK = pytz.timezone("Asia/Bangkok")


class _Store:
    def __init__(self, monkeypatch):
        self.files = {}
        monkeypatch.setattr(
            storage, "_read_file",
            lambda f, fresh=False: self.files.get(
                f, [] if f in (storage.PRICE_HISTORY_FILE, storage.BUY_LOG_FILE) else {}))
        monkeypatch.setattr(storage, "_write_file",
                            lambda f, d: self.files.__setitem__(f, d) or True)


# ── The shared helper ───────────────────────────────────────────

def test_change_arrow():
    assert change_arrow(0.5) == "📈"
    assert change_arrow(-0.5) == "📉"
    assert change_arrow(0) == "➡️"
    assert change_arrow(0.0) == "➡️"
    assert change_arrow(None) == "➡️"


def test_no_call_site_spells_it_inline():
    """Keeping six copies in step is what failed the first time."""
    import pathlib
    root = pathlib.Path(gold_monitor.__file__).parent
    offenders = []
    for name in ("bot_core.py", "gold_monitor.py", "signals.py"):
        for i, line in enumerate((root / name).read_text().splitlines(), 1):
            if "📈" in line and "if" in line:
                offenders.append(f"{name}:{i}")
    assert not offenders, offenders


# ── The three sites that were wrong ─────────────────────────────

def test_chart_caption_is_flat_when_price_did_not_move(monkeypatch):
    store = _Store(monkeypatch)
    store.files[storage.PRICE_HISTORY_FILE] = [
        {"ts": f"2026-09-21T{i:02d}:00:00+07:00", "thb_gram": 4000.0,
         "usd_oz": 2400.0} for i in range(24)
    ]
    monkeypatch.setattr(bot_core, "_quickchart_short_url", lambda cfg: "https://q/c")
    captions = []
    monkeypatch.setattr(
        bot_core, "send_photo",
        lambda url, caption, cid="": captions.append(caption) or {"ok": True})

    bot_core.cmd_chart("111", "1", "my")

    assert "➡️ +0.00%" in captions[0], captions[0]


def test_weekly_recap_is_flat_when_the_week_did_not_move():
    now = _dt.datetime.now(BKK)
    flat = [{"ts": (now - _dt.timedelta(hours=167 - i)).isoformat(),
             "thb_gram": 4000.0, "usd_oz": 2400.0} for i in range(168)]

    block = gold_monitor.build_weekly_block(flat, "en")

    assert "➡️ Week: +0.00%" in block, block


def test_evening_summary_is_flat_when_the_day_did_not_move(monkeypatch):
    store = _Store(monkeypatch)
    at = BKK.localize(_dt.datetime(2026, 9, 21, 20, 0))

    class _FakeDateTime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return at if tz is None else at.astimezone(tz)

    store.files[storage.DAY_STATE_FILE] = {
        "date": "2026-09-21", "open_price": 4500.0, "day_low": 4500.0,
        "day_high": 4500.0, "prev_close": 4500.0, "last_price": 4500.0,
        "morning_sent": True, "evening_sent": False, "notified_gap": True,
    }
    monkeypatch.setattr(storage, "get_subscribers_and_prefs", lambda: ([], {}))
    monkeypatch.setattr(storage, "pop_triggered_alerts", lambda *p: [])
    monkeypatch.setattr(goldapi, "get_gold_price", lambda retries=2: (4500.0, 2400.0, 34.0))
    monkeypatch.setattr(storage, "datetime", _FakeDateTime)
    monkeypatch.setattr(gold_monitor, "datetime", _FakeDateTime)
    monkeypatch.setattr(gold_monitor, "TG_BOT_TOKEN", "x")
    monkeypatch.setattr(gold_monitor, "TG_CHAT_ID", "999")
    monkeypatch.setattr(gold_monitor.signals, "format_macro_block", lambda *a, **k: "")
    monkeypatch.setattr(bot_core, "warn_owner_if_webhook_broken", lambda st: False)
    sent = []
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="": (sent.append(text), {"ok": True})[1])

    gold_monitor.main()

    evening = next(m for m in sent if "Evening" in m or "ညနေ" in m)
    assert "➡️ ယနေ့ change : +0.00%" in evening, evening
    # Not "-0.00%": `change = -d` negated a zero drop into negative zero, which
    # printed a minus sign right beside the flat arrow.
    assert "-0.00%" not in evening


# ── _bot_state survives a storage failure ───────────────────────

def test_bot_state_is_bound_even_when_storage_fails(monkeypatch):
    """main() hands _bot_state to the webhook watchdog at the end of a run.
    Binding it only inside the try meant a NameError there instead — losing
    the check that spots a webhook swallowing every command, exactly when
    storage was already unhealthy."""
    monkeypatch.setattr(storage, "load_bot_state",
                        lambda: (_ for _ in ()).throw(RuntimeError("gist down")))
    try:
        reloaded = importlib.reload(gold_monitor)
        assert reloaded._bot_state == {}
        assert reloaded.DROP_THRESHOLD > 0      # fell back to the default
    finally:
        monkeypatch.undo()
        importlib.reload(gold_monitor)
