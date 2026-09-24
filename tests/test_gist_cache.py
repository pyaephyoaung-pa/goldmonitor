"""storage caches the Gist for the length of one logical run.

_get_gist downloads EVERY file — history, buy log, exported models — so a
single monitor run did that 3-6 times, every five minutes. The cache is only
safe because of three rules, and each of them is pinned here.
"""
import json

import bot_core
import storage


class _FakeGist:
    """Counts full-Gist downloads and lets a test change what they return."""

    def __init__(self, monkeypatch, files=None, down=False):
        self.files = files if files is not None else {}
        self.down = down                 # the request FAILS, as in an outage
        self.fetches = 0
        monkeypatch.setattr(storage, "_get_gist", self._get)
        monkeypatch.setattr(storage, "GITHUB_TOKEN", "t")
        monkeypatch.setattr(storage, "GIST_ID", "g")

    def _get(self):
        self.fetches += 1
        if self.down:
            return None
        return {name: {"content": json.dumps(value)}
                for name, value in self.files.items()}

    def set(self, name, value):
        self.files[name] = value


def _ok_patch(monkeypatch, ok=True):
    """Stand in for the requests.patch inside _write_file/_write_files."""
    class _Resp:
        def raise_for_status(self):
            if not ok:
                raise RuntimeError("gist write failed")

    monkeypatch.setattr(storage.requests, "patch", lambda *a, **k: _Resp())


# ── The point of the change ─────────────────────────────────────

def test_many_reads_cost_one_download(monkeypatch):
    gist = _FakeGist(monkeypatch, {
        storage.BOT_STATE_FILE: {"update_offset": 3},
        storage.PRICE_HISTORY_FILE: [{"ts": "2026-01-01T00:00:00+07:00",
                                      "thb_gram": 4000.0}],
        storage.SUBSCRIBERS_FILE: {"chat_ids": ["1"], "prefs": {}},
    })

    assert storage.load_bot_state()["update_offset"] == 3
    assert len(storage.get_price_history()) == 1
    assert storage.get_subscribers() == ["1"]
    assert storage.get_user_lang("1") == "my"

    assert gist.fetches == 1


def test_reset_cache_forces_a_refetch(monkeypatch):
    gist = _FakeGist(monkeypatch, {storage.BOT_STATE_FILE: {"n": 1}})

    storage.load_bot_state()
    storage.reset_cache()
    storage.load_bot_state()

    assert gist.fetches == 2


# ── Rule 1: never cache a failed or empty fetch ─────────────────

def test_a_failed_fetch_is_remembered_for_the_run(monkeypatch):
    """Retrying on every read never protected anything — the FIRST failed read
    already hands callers an empty container — it only multiplied requests
    during an outage. The overwrite risk is closed by the write guard instead."""
    gist = _FakeGist(monkeypatch, down=True)

    for _ in range(5):
        assert storage.load_bot_state() == {"update_offset": 0, "drop_threshold": 0.5}

    assert gist.fetches == 1


def test_the_next_run_tries_again(monkeypatch):
    gist = _FakeGist(monkeypatch, down=True)
    storage.load_bot_state()

    gist.down = False
    gist.set(storage.BOT_STATE_FILE, {"update_offset": 9})
    storage.reset_cache()                       # a new logical run

    assert storage.load_bot_state()["update_offset"] == 9
    assert gist.fetches == 2


def test_an_empty_but_reachable_gist_is_not_cached(monkeypatch):
    """Not an outage — the request worked and returned nothing, which a real
    Gist never does. It is not remembered, so a later read looks again."""
    gist = _FakeGist(monkeypatch, {})

    storage.load_bot_state()
    gist.set(storage.BOT_STATE_FILE, {"update_offset": 9})
    assert storage.load_bot_state()["update_offset"] == 9

    assert gist.fetches == 2


# ── Rule 2: writes update the cache, but only when they land ────

def test_read_after_write_sees_the_write(monkeypatch):
    gist = _FakeGist(monkeypatch, {storage.BOT_STATE_FILE: {"update_offset": 1}})
    _ok_patch(monkeypatch)

    storage.load_bot_state()
    assert storage.save_bot_state({"update_offset": 42}) is True
    assert storage.load_bot_state()["update_offset"] == 42

    assert gist.fetches == 1  # served from the updated cache, no refetch


def test_failed_write_does_not_update_the_cache(monkeypatch):
    _FakeGist(monkeypatch, {storage.BOT_STATE_FILE: {"update_offset": 1}})
    _ok_patch(monkeypatch, ok=False)

    storage.load_bot_state()
    assert storage.save_bot_state({"update_offset": 42}) is False
    # The write never landed, so the cache must still show the stored value —
    # otherwise the run acts on state that is not in the Gist.
    assert storage.load_bot_state()["update_offset"] == 1


def test_batch_write_updates_every_file(monkeypatch):
    gist = _FakeGist(monkeypatch, {storage.DAY_STATE_FILE: {"date": "old"},
                                   storage.MODEL_DATA_FILE: {"predictions": []}})
    _ok_patch(monkeypatch)

    storage._read_file(storage.DAY_STATE_FILE)   # warm the cache
    assert storage.save_day_state_and_model({"date": "new"},
                                            {"predictions": [1]}) is True

    assert storage._read_file(storage.DAY_STATE_FILE) == {"date": "new"}
    assert storage._read_file(storage.MODEL_DATA_FILE) == {"predictions": [1]}
    assert gist.fetches == 1


# ── Rule 3: append_price still re-reads for real ────────────────

def test_append_price_rereads_past_the_cache(monkeypatch):
    """The pre-write re-read exists to pick up a CONCURRENT run's appends.
    Serving it from our own cache would silently remove that guard."""
    concurrent = {"ts": "2026-01-01T05:00:00+07:00", "thb_gram": 4111.0}
    gist = _FakeGist(monkeypatch, {storage.PRICE_HISTORY_FILE: []})
    _ok_patch(monkeypatch)

    storage.get_price_history()          # warms the cache with an empty history
    gist.set(storage.PRICE_HISTORY_FILE, [concurrent])  # another run appends

    result = storage.append_price(4200.0, 2400.0, 34.0)

    assert gist.fetches == 2
    assert concurrent in result, "a concurrent append was lost"
    assert any(h["thb_gram"] == 4200.0 for h in result)


# ── A warm container is not a fresh process ─────────────────────

def test_dispatch_resets_the_cache_per_update(monkeypatch):
    resets = []
    monkeypatch.setattr(storage, "reset_cache", lambda: resets.append(1))
    monkeypatch.setattr(storage, "get_user_lang", lambda cid: "en")
    monkeypatch.setattr(bot_core, "send_message", lambda *a, **k: None)
    monkeypatch.setattr(bot_core, "cmd_price", lambda cid, lang: None)

    for _ in range(2):
        bot_core.dispatch_update({"message": {"text": "/price", "chat": {"id": "1"}}})

    assert len(resets) == 2


# ── The redundant second read of subscribers.json is gone ───────

def test_subscriber_writes_read_the_file_once(monkeypatch):
    gist = _FakeGist(monkeypatch, {storage.SUBSCRIBERS_FILE:
                                   {"chat_ids": ["1"], "prefs": {"1": {"lang": "th"}}}})
    _ok_patch(monkeypatch)

    assert storage.add_subscriber("2") is True
    assert storage.get_subscribers() == ["1", "2"]
    # Adding a subscriber must not wipe anyone's prefs.
    assert storage.get_user_prefs("1")["lang"] == "th"

    assert gist.fetches == 1


# ── The truncated-file refetch happens once, not per read ───────

def test_truncated_file_is_refetched_once(monkeypatch):
    """model_data.json is the file most likely to cross the API's 1 MB inline
    limit, and it is read more than once per run."""
    payload = {"predictions": [{"horizon": "24h"}]}
    full = json.dumps(payload)

    monkeypatch.setattr(storage, "_get_gist", lambda: {
        storage.MODEL_DATA_FILE: {"content": full[:5], "truncated": True,
                                  "raw_url": "https://gist.example/raw"},
    })

    raw_fetches = []

    class _Resp:
        text = full

        def raise_for_status(self):
            pass

    monkeypatch.setattr(storage.requests, "get",
                        lambda *a, **k: (raw_fetches.append(1), _Resp())[1])

    assert storage.load_model_data() == payload
    assert storage.load_model_data() == payload

    assert len(raw_fetches) == 1
