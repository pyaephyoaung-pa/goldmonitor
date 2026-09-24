"""A Gist read that FAILS must never turn into a write that destroys data.

Nearly every write in storage.py is read-modify-write, and a failed read used
to look exactly like an empty file. One GET timing out, followed by a PATCH
that works, did this — measured, not hypothetical:

    append_price     price history   720 points -> 1
    log_buy          portfolio       the old buys replaced by the new one
    add_subscriber   subscribers     3 -> 1, and every user's prefs wiped

The data was intact on GitHub the whole time. These tests drive the real
requests-level code paths: the GET fails, the PATCH would succeed, and nothing
may reach GitHub.
"""
import json
from datetime import datetime, timedelta

import pytest
import pytz

import bot_core
import storage


class _GitHub:
    """GET and PATCH at the requests layer, so the real _get_gist runs."""

    def __init__(self, monkeypatch, files, get_fails=True):
        self.files = {k: json.dumps(v) for k, v in files.items()}
        self.get_fails = get_fails
        self.gets = 0
        self.patched = {}
        monkeypatch.setattr(storage, "GITHUB_TOKEN", "t")
        monkeypatch.setattr(storage, "GIST_ID", "g")
        monkeypatch.setattr(storage.requests, "get", self._get)
        monkeypatch.setattr(storage.requests, "patch", self._patch)

    def _get(self, url, headers=None, timeout=None):
        self.gets += 1
        if self.get_fails:
            raise TimeoutError("GET timed out")
        outer = self

        class _R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"files": {k: {"content": v} for k, v in outer.files.items()}}

        return _R()

    def _patch(self, url, headers=None, timeout=None, json=None):
        for name, f in json["files"].items():
            self.patched[name] = f["content"]

        class _R:
            def raise_for_status(self):
                pass

        return _R()


# 720 hourly points ending two hours ago — a full history, all in the past, so
# a freshly appended point is the newest one.
_NOW = datetime.now(pytz.timezone("Asia/Bangkok"))
HISTORY = [{"ts": (_NOW - timedelta(hours=722 - i)).isoformat(), "thb_gram": 4000.0}
           for i in range(720)]
LEDGER = [{"type": "buy", "ts": "2026-09-01T10:00:00+07:00",
           "amount_thb": 50000, "price_per_gram": 4000.0, "grams": 12.5}]
SUBS = {"chat_ids": ["a", "b", "c"], "prefs": {"a": {"lang": "th"}}}


# ── The data-loss cases ─────────────────────────────────────────

@pytest.mark.parametrize("label, action", [
    ("price history", lambda: storage.append_price(4100.0, 2400.0, 34.0)),
    ("portfolio",     lambda: storage.log_buy(1000, 4100.0)),
    ("subscribers",   lambda: storage.add_subscriber("d")),
    ("prefs",         lambda: storage.set_user_pref("d", "lang", "en")),
    ("level alerts",  lambda: storage.add_level_alert("d", "above", 3000)),
])
def test_a_failed_read_writes_nothing(monkeypatch, label, action):
    gh = _GitHub(monkeypatch, {storage.PRICE_HISTORY_FILE: HISTORY,
                               storage.BUY_LOG_FILE: LEDGER,
                               storage.SUBSCRIBERS_FILE: SUBS})
    action()
    assert gh.patched == {}, f"{label}: a failed read went on to overwrite {list(gh.patched)}"


def test_the_callers_see_the_write_was_refused(monkeypatch):
    """So the poller skips its batch and the monitor says day state was not
    saved — both already act on a False from these."""
    _GitHub(monkeypatch, {storage.BOT_STATE_FILE: {"update_offset": 7}})
    storage.load_bot_state()
    assert storage.save_bot_state({"update_offset": 8}) is False
    assert storage.save_day_state_and_model({}, {}) is False


def test_a_healthy_run_still_writes(monkeypatch):
    gh = _GitHub(monkeypatch, {storage.PRICE_HISTORY_FILE: HISTORY}, get_fails=False)
    storage.append_price(4100.0, 2400.0, 34.0)
    written = json.loads(gh.patched[storage.PRICE_HISTORY_FILE])
    assert len(written) == 720 and written[-1]["thb_gram"] == 4100.0


# ── Fewer requests while failing ────────────────────────────────

def test_a_failing_run_makes_one_request_not_one_per_read(monkeypatch):
    gh = _GitHub(monkeypatch, {})
    for name in (storage.BOT_STATE_FILE, storage.DAY_STATE_FILE,
                 storage.LEVEL_ALERTS_FILE, storage.SUBSCRIBERS_FILE,
                 storage.PRICE_HISTORY_FILE):
        storage._read_file(name)
    assert gh.gets == 1


def test_a_failed_fresh_reread_uses_the_copy_already_read(monkeypatch):
    """append_price re-reads with fresh=True to catch concurrent appends. If
    that re-read fails after a good read, the good copy is real — seconds old,
    not wrong — so the append proceeds on it."""
    gh = _GitHub(monkeypatch, {storage.PRICE_HISTORY_FILE: HISTORY}, get_fails=False)
    storage.get_price_history()                 # a good read first
    gh.get_fails = True                         # then the fresh re-read fails

    storage.append_price(4100.0, 2400.0, 34.0)

    written = json.loads(gh.patched[storage.PRICE_HISTORY_FILE])
    assert len(written) == 720 and written[-1]["thb_gram"] == 4100.0


# ── One file unreadable, not the whole Gist ─────────────────────

def test_a_truncated_file_that_cannot_be_fetched_is_protected(monkeypatch):
    """GitHub inlines files only up to 1 MB. If the raw_url refetch fails, the
    file exists and we cannot see it — so it must not be overwritten. Files
    that were read fine stay writable."""
    monkeypatch.setattr(storage, "GITHUB_TOKEN", "t")
    monkeypatch.setattr(storage, "GIST_ID", "g")
    monkeypatch.setattr(storage, "_get_gist", lambda: {
        storage.MODEL_DATA_FILE: {"content": "{", "truncated": True, "raw_url": "https://x"},
        storage.DAY_STATE_FILE: {"content": json.dumps({"date": "2026-09-24"})},
    })

    def _raw(*a, **k):
        raise TimeoutError("raw_url fetch timed out")

    monkeypatch.setattr(storage.requests, "get", _raw)
    patched = []

    class _OK:
        def raise_for_status(self):
            pass

    monkeypatch.setattr(storage.requests, "patch",
                        lambda *a, **k: patched.append(list(k["json"]["files"])) or _OK())

    storage.load_model_data()
    assert storage.save_model_data({"predictions": []}) is False
    assert storage.save_day_state({"date": "2026-09-24"}) is True
    assert patched == [[storage.DAY_STATE_FILE]]


def test_a_corrupt_file_does_not_wedge_every_write(monkeypatch):
    """A file that downloads but will not PARSE is corrupt on GitHub, not
    missing. Blocking on it would block every write on every run, forever."""
    monkeypatch.setattr(storage, "GITHUB_TOKEN", "t")
    monkeypatch.setattr(storage, "GIST_ID", "g")
    monkeypatch.setattr(storage, "_get_gist",
                        lambda: {storage.BOT_STATE_FILE: {"content": "{not json"}})

    class _OK:
        def raise_for_status(self):
            pass

    monkeypatch.setattr(storage.requests, "patch", lambda *a, **k: _OK())

    storage.load_bot_state()
    assert storage.save_bot_state({"update_offset": 1}) is True


# ── The rate limiter stops reading the Gist for a refused chat ──

class _CountingGist:
    def __init__(self, monkeypatch, files):
        self.files, self.fetches = files, 0
        monkeypatch.setattr(storage, "GITHUB_TOKEN", "t")
        monkeypatch.setattr(storage, "GIST_ID", "g")
        monkeypatch.setattr(storage, "_get_gist", self._get)
        monkeypatch.setattr(storage, "_write_file", lambda f, d: True)

    def _get(self):
        self.fetches += 1
        return {k: {"content": json.dumps(v)} for k, v in self.files.items()}


def _flood(monkeypatch, chat="111", owner="999", n=5):
    monkeypatch.setattr(bot_core, "TG_CHAT_ID", owner)
    monkeypatch.setattr(bot_core, "send_message", lambda *a, **k: None)
    monkeypatch.setattr(bot_core, "cmd_price", lambda cid, lang: None)
    for _ in range(n):
        bot_core.dispatch_update({"message": {"text": "/price", "chat": {"id": chat}}})


def _over_the_limit(chat="111"):
    now = storage._now_ts()
    return {storage.SUBSCRIBERS_FILE: {"chat_ids": [], "prefs": {}},
            storage.RATE_LIMIT_FILE: {chat: {"hits": [now] * 40, "external": [],
                                             "notified_at": now}}}


def test_a_refused_flood_stops_reading_the_gist(monkeypatch):
    """The limiter's state is in the Gist, and reading the Gist is the cost it
    bounds. Five refused commands used to cost five full downloads."""
    gist = _CountingGist(monkeypatch, _over_the_limit())
    _flood(monkeypatch, n=5)
    assert gist.fetches == 1


def test_the_chat_is_let_back_in_when_its_window_frees(monkeypatch):
    gist = _CountingGist(monkeypatch, _over_the_limit())
    _flood(monkeypatch, n=1)
    until = bot_core._refused_until["111"]

    monkeypatch.setattr(storage, "_now_ts", lambda: until + 1)
    gist.files[storage.RATE_LIMIT_FILE] = {}      # the window really has freed
    _flood(monkeypatch, n=1)

    assert gist.fetches == 2 and "111" not in bot_core._refused_until


def test_the_owner_is_never_dropped(monkeypatch):
    ran = []
    _CountingGist(monkeypatch, _over_the_limit("999"))
    bot_core._refused_until["999"] = storage._now_ts() + 600
    monkeypatch.setattr(bot_core, "TG_CHAT_ID", "999")
    monkeypatch.setattr(bot_core, "send_message", lambda *a, **k: None)
    monkeypatch.setattr(bot_core, "cmd_price", lambda cid, lang: ran.append(cid))

    bot_core.dispatch_update({"message": {"text": "/price", "chat": {"id": "999"}}})

    assert ran == ["999"]


def test_the_refusal_memory_stays_bounded(monkeypatch):
    for i in range(bot_core._REFUSED_MEMORY_MAX + 50):
        bot_core._remember_refusal(str(i), 600)
    assert len(bot_core._refused_until) <= bot_core._REFUSED_MEMORY_MAX


def test_an_outage_throttles_nobody(monkeypatch):
    """If the limiter's own state cannot be read, it fails OPEN — failing
    closed would lock every user out during every GitHub blip."""
    monkeypatch.setattr(storage, "GITHUB_TOKEN", "t")
    monkeypatch.setattr(storage, "GIST_ID", "g")
    monkeypatch.setattr(storage, "_get_gist", lambda: None)
    ran = []
    monkeypatch.setattr(bot_core, "TG_CHAT_ID", "999")
    monkeypatch.setattr(bot_core, "send_message", lambda *a, **k: None)
    monkeypatch.setattr(bot_core, "cmd_price", lambda cid, lang: ran.append(cid))

    for _ in range(40):
        bot_core.dispatch_update({"message": {"text": "/price", "chat": {"id": "111"}}})

    assert len(ran) == 40 and not bot_core._refused_until
