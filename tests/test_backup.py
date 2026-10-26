"""The owner's data had one copy: the Gist. A deleted or corrupted Gist, or a
bad write, would have taken the ledger, the subscribers and their settings
with it. The owner now gets a backup file every week, and on /backup, and
restore_backup.py puts one back.
"""
import datetime as _dt
import json

import pytest
import pytz

import bot_core
import gold_monitor
import restore_backup
import storage

BKK = pytz.timezone("Asia/Bangkok")

GIST = {
    storage.BUY_LOG_FILE: [{"type": "buy", "grams": 1.0}, {"type": "buy", "grams": 2.0}],
    storage.SUBSCRIBERS_FILE: {"chat_ids": ["a", "b", "c"], "prefs": {"a": {"lang": "my"}}},
    storage.LEVEL_ALERTS_FILE: {"a": [{"dir": "above", "price": 4500}]},
    storage.BOT_STATE_FILE: {"update_offset": 900, "drop_threshold": 0.7},
    storage.PRICE_HISTORY_FILE: [{"ts": "2026-10-26T10:00:00+07:00", "thb_gram": 4500.0}],
    storage.MODEL_DATA_FILE: {"models": {"24h": {}}},
}


@pytest.fixture
def gist(monkeypatch):
    files = json.loads(json.dumps(GIST))
    monkeypatch.setattr(storage, "GITHUB_TOKEN", "t")
    monkeypatch.setattr(storage, "GIST_ID", "g")
    monkeypatch.setattr(storage, "_read_file", lambda f, fresh=False: files.get(
        f, [] if f in (storage.PRICE_HISTORY_FILE, storage.BUY_LOG_FILE) else {}))
    return files


@pytest.fixture
def telegram(monkeypatch):
    sent = {"docs": [], "msgs": []}
    monkeypatch.setattr(bot_core, "send_document",
                        lambda cid, name, data, caption="": sent["docs"].append(
                            (cid, name, json.loads(data), caption)) or {"ok": True})
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="", **kw: sent["msgs"].append(text))
    return sent


# ── What goes in it ─────────────────────────────────────────────

def test_the_snapshot_holds_what_cannot_be_rebuilt(gist):
    snap = storage.backup_snapshot()
    assert snap["format"] == storage.BACKUP_FORMAT
    assert set(snap["files"]) == set(storage.BACKUP_FILES)
    assert snap["files"][storage.BUY_LOG_FILE] == GIST[storage.BUY_LOG_FILE]
    assert storage.MODEL_DATA_FILE not in snap["files"], "rebuilt nightly, and the largest file"


def test_a_failed_read_gives_no_backup(gist, monkeypatch):
    """Empty containers stand in for a failed read — a backup of them would
    look like a good backup of nothing."""
    monkeypatch.setattr(storage, "_writes_blocked", lambda names: "the Gist could not be read")
    assert storage.backup_snapshot() is None


def test_the_owner_gets_the_file_with_a_summary(gist, telegram):
    assert bot_core.send_backup("OWNER", "en") is True
    cid, name, data, caption = telegram["docs"][0]
    assert cid == "OWNER" and name.startswith("goldmonitor-backup-") and name.endswith(".json")
    assert data["files"][storage.SUBSCRIBERS_FILE]["chat_ids"] == ["a", "b", "c"]
    assert "2 ledger entries · 1 price points · 3 subscribers" in caption


def test_an_unreadable_gist_says_so_instead_of_sending(gist, telegram, monkeypatch):
    monkeypatch.setattr(storage, "backup_snapshot", lambda: None)
    assert bot_core.send_backup("OWNER", "en") is False
    assert telegram["docs"] == [] and "Backup skipped" in telegram["msgs"][0]


def test_backup_is_an_owner_command():
    assert "/backup" in bot_core.OWNER_COMMANDS and "/backup" not in bot_core.PUBLIC_COMMANDS


# ── Once a week ─────────────────────────────────────────────────

def _at(day, hour):
    return BKK.localize(_dt.datetime(2026, 11, day, hour, 5))


@pytest.fixture
def weekly(monkeypatch, gist, telegram):
    monkeypatch.setattr(gold_monitor, "_bot_state", {})
    monkeypatch.setattr(gold_monitor, "TG_CHAT_ID", "OWNER")
    monkeypatch.setattr(storage, "get_user_lang", lambda cid: "en")
    return telegram


def test_it_goes_out_weekly_in_the_evening(weekly):
    send = gold_monitor.send_weekly_backup
    assert send(_at(1, 14)) is False            # not in the evening window
    assert send(_at(1, 21)) is True             # first evening: send
    assert send(_at(1, 22)) is False            # same evening
    assert send(_at(5, 21)) is False            # four days on
    assert send(_at(8, 21)) is True             # a week on
    assert len(weekly["docs"]) == 2


def test_a_failed_send_is_retried_next_run(weekly, monkeypatch):
    monkeypatch.setattr(bot_core, "send_backup", lambda cid, lang: False)
    assert gold_monitor.send_weekly_backup(_at(1, 21)) is False
    assert "backup_sent_at" not in gold_monitor._bot_state


# ── Restoring ───────────────────────────────────────────────────

@pytest.fixture
def backup_file(tmp_path, gist):
    path = tmp_path / "backup.json"
    path.write_text(json.dumps(storage.backup_snapshot()), encoding="utf-8")
    return str(path)


@pytest.fixture
def patches(monkeypatch):
    sent = []

    class _Resp:
        def raise_for_status(self):
            pass

    monkeypatch.setattr(restore_backup.requests, "patch",
                        lambda url, **kw: sent.append(kw["json"]["files"]) or _Resp())
    return sent


def test_a_dry_run_writes_nothing(backup_file, patches, capsys):
    assert restore_backup.main([backup_file]) == 0
    assert patches == [] and "Nothing written" in capsys.readouterr().out


def test_apply_writes_back_only_the_backed_up_files(backup_file, patches, gist):
    gist[storage.BUY_LOG_FILE] = []                         # the loss being undone
    assert restore_backup.main([backup_file, "--apply"]) == 0
    written = patches[0]
    assert set(written) == set(storage.BACKUP_FILES)
    assert json.loads(written[storage.BUY_LOG_FILE]["content"]) == GIST[storage.BUY_LOG_FILE]


def test_the_telegram_offset_never_moves_backwards(backup_file, patches, gist):
    """An older offset would make the poller replay a day of updates — a
    /bought twice is a ledger entry twice."""
    gist[storage.BOT_STATE_FILE] = {"update_offset": 950}
    restore_backup.main([backup_file, "--apply"])
    state = json.loads(patches[0][storage.BOT_STATE_FILE]["content"])
    assert state["update_offset"] == 950 and state["drop_threshold"] == 0.7


def test_other_files_are_refused(tmp_path, patches, gist):
    other = tmp_path / "x.json"
    other.write_text('{"files": {}}', encoding="utf-8")
    assert restore_backup.main([str(other), "--apply"]) == 2 and patches == []
