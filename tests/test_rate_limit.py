"""Public commands are rate limited per chat.

Anyone can talk to this bot and every command costs at least one Gist read.
The GitHub API allows 5,000 authenticated requests an hour, SHARED with the
monitor — so a chat spamming commands can burn the token's quota and take the
price alerts down with it. That is the failure these limits exist to prevent.
"""
import datetime as _dt

import pytz

import bot_core
import storage

BKK = pytz.timezone("Asia/Bangkok")
START = BKK.localize(_dt.datetime(2026, 9, 15, 12, 0))


class _Clock:
    """A fixed, advanceable clock for storage's datetime.now()."""

    def __init__(self, monkeypatch):
        self.at = START
        clock = self

        class _FakeDateTime(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return clock.at if tz is None else clock.at.astimezone(tz)

        monkeypatch.setattr(storage, "datetime", _FakeDateTime)

    def advance(self, seconds):
        self.at = self.at + _dt.timedelta(seconds=seconds)


class _Store:
    def __init__(self, monkeypatch):
        self.files = {}
        self.writes = 0
        monkeypatch.setattr(
            storage, "_read_file",
            lambda f, fresh=False: self.files.get(
                f, [] if f in (storage.PRICE_HISTORY_FILE, storage.BUY_LOG_FILE) else {}))

        def _write(f, d):
            self.writes += 1
            self.files[f] = d
            return True

        monkeypatch.setattr(storage, "_write_file", _write)


def _spend(n, chat="111", external=False):
    return [storage.allow_command(chat, external) for _ in range(n)]


# ── The limits themselves ───────────────────────────────────────

def test_commands_under_the_limit_are_allowed(monkeypatch):
    _Clock(monkeypatch)
    _Store(monkeypatch)

    verdicts = _spend(storage.RATE_MAX_COMMANDS)

    assert all(v["allowed"] for v in verdicts)


def test_the_general_limit_bites(monkeypatch):
    _Clock(monkeypatch)
    _Store(monkeypatch)
    _spend(storage.RATE_MAX_COMMANDS)

    verdict = storage.allow_command("111")

    assert verdict["allowed"] is False
    assert 0 < verdict["retry_after"] <= storage.RATE_WINDOW_SEC


def test_external_commands_get_a_tighter_allowance(monkeypatch):
    _Clock(monkeypatch)
    _Store(monkeypatch)

    external = _spend(storage.RATE_MAX_EXTERNAL, external=True)
    assert all(v["allowed"] for v in external)

    assert storage.allow_command("111", external=True)["allowed"] is False
    # ...but a cheap command is still fine: the general budget is not spent.
    assert storage.allow_command("111", external=False)["allowed"] is True


def test_limits_are_per_chat(monkeypatch):
    _Clock(monkeypatch)
    _Store(monkeypatch)
    _spend(storage.RATE_MAX_COMMANDS, chat="111")

    assert storage.allow_command("111")["allowed"] is False
    assert storage.allow_command("222")["allowed"] is True


def test_the_window_rolls(monkeypatch):
    clock = _Clock(monkeypatch)
    _Store(monkeypatch)
    _spend(storage.RATE_MAX_COMMANDS)
    assert storage.allow_command("111")["allowed"] is False

    clock.advance(storage.RATE_WINDOW_SEC + 1)

    assert storage.allow_command("111")["allowed"] is True


# ── A flood must get cheaper, not louder ────────────────────────

def test_only_the_first_refusal_notifies(monkeypatch):
    _Clock(monkeypatch)
    _Store(monkeypatch)
    _spend(storage.RATE_MAX_COMMANDS)

    refusals = _spend(5)

    assert [v["notify"] for v in refusals] == [True, False, False, False, False]


def test_a_refused_command_writes_nothing(monkeypatch):
    """The refusal path must not be usable to generate load itself."""
    _Clock(monkeypatch)
    store = _Store(monkeypatch)
    _spend(storage.RATE_MAX_COMMANDS)
    storage.allow_command("111")          # the one refusal that records notify
    writes_so_far = store.writes

    _spend(20)

    assert store.writes == writes_so_far


def test_inactive_chats_are_compacted_away(monkeypatch):
    clock = _Clock(monkeypatch)
    store = _Store(monkeypatch)
    _spend(3, chat="111")
    _spend(3, chat="222")
    assert set(store.files[storage.RATE_LIMIT_FILE]) == {"111", "222"}

    clock.advance(storage.RATE_WINDOW_SEC + 1)
    storage.allow_command("333")

    assert set(store.files[storage.RATE_LIMIT_FILE]) == {"333"}


# ── Wiring into dispatch ────────────────────────────────────────

def _dispatch_setup(monkeypatch, owner=""):
    _Clock(monkeypatch)
    _Store(monkeypatch)
    monkeypatch.setattr(bot_core, "TG_CHAT_ID", owner)
    monkeypatch.setattr(storage, "get_user_lang", lambda cid: "en")
    sent = []
    monkeypatch.setattr(bot_core, "send_message", lambda text, cid="", **k: sent.append(text))
    ran = []
    monkeypatch.setattr(bot_core, "cmd_price", lambda cid, lang: ran.append(cid))
    return sent, ran


def _price(chat="111"):
    return bot_core.dispatch_update(
        {"message": {"text": "/price", "chat": {"id": chat}}})


def test_dispatch_refuses_before_running_the_handler(monkeypatch):
    sent, ran = _dispatch_setup(monkeypatch)

    for _ in range(storage.RATE_MAX_EXTERNAL):
        assert _price() is True
    assert len(ran) == storage.RATE_MAX_EXTERNAL

    assert _price() is False
    assert len(ran) == storage.RATE_MAX_EXTERNAL, "handler ran while throttled"
    assert "Slow down" in sent[-1]


def test_the_owner_is_never_throttled(monkeypatch):
    """A throttled owner would mean the bot could refuse its own operator."""
    _, ran = _dispatch_setup(monkeypatch, owner="999")

    for _ in range(storage.RATE_MAX_COMMANDS * 2):
        assert _price("999") is True

    assert len(ran) == storage.RATE_MAX_COMMANDS * 2


def test_unknown_commands_count_too(monkeypatch):
    """They still cost a Gist read and a Telegram send."""
    sent, _ = _dispatch_setup(monkeypatch)

    for _ in range(storage.RATE_MAX_COMMANDS):
        bot_core.dispatch_update(
            {"message": {"text": "/nope", "chat": {"id": "111"}}})

    sent.clear()
    bot_core.dispatch_update({"message": {"text": "/nope", "chat": {"id": "111"}}})
    assert "Slow down" in sent[-1]
