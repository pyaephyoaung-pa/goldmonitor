"""A revoked bot token must fail LOUDLY.

Every Telegram error in bot_core is swallowed so one flaky send cannot abort a
monitor run — which makes a revoked token invisible: every call 401s, every
error is caught, the cron reports success, and no message ever leaves.

It also cannot be reported the usual way: an alert about a dead token needs
that same dead token. So the only signal left is the process failing, turning
the Actions run red. These tests pin that.
"""

import pytest

import bot_commands
import bot_core


@pytest.fixture(autouse=True)
def _clean_auth_state():
    bot_core.reset_auth_state()
    yield
    bot_core.reset_auth_state()


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {"ok": True}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError("raise_for_status must not be reached on a 401")


UNAUTHORIZED = {"ok": False, "error_code": 401, "description": "Unauthorized"}


# ── Detection ───────────────────────────────────────────────────

def test_starts_clean():
    assert bot_core.auth_failed() is False


def test_send_message_flags_401(monkeypatch):
    monkeypatch.setattr(bot_core, "TG_BOT_TOKEN", "dead")
    monkeypatch.setattr(bot_core.requests, "post",
                        lambda *a, **k: _Resp(401, UNAUTHORIZED))
    bot_core.send_message("hi", "111")
    assert bot_core.auth_failed() is True


def test_send_message_does_not_retry_on_401(monkeypatch):
    """Retrying a rejected token is pure waste."""
    monkeypatch.setattr(bot_core, "TG_BOT_TOKEN", "dead")
    calls = []

    def post(*a, **k):
        calls.append(1)
        return _Resp(401, UNAUTHORIZED)
    monkeypatch.setattr(bot_core.requests, "post", post)
    bot_core.send_message("hi", "111")
    assert len(calls) == 1


def test_get_updates_flags_401(monkeypatch):
    monkeypatch.setattr(bot_core, "TG_BOT_TOKEN", "dead")
    monkeypatch.setattr(bot_core.requests, "get",
                        lambda *a, **k: _Resp(401, UNAUTHORIZED))
    assert bot_core.get_updates() == []
    assert bot_core.auth_failed() is True


def test_webhook_status_flags_401(monkeypatch):
    monkeypatch.setattr(bot_core, "TG_BOT_TOKEN", "dead")
    monkeypatch.setattr(bot_core.requests, "get",
                        lambda *a, **k: _Resp(401, UNAUTHORIZED))
    assert bot_core.webhook_status() == {}
    assert bot_core.auth_failed() is True


def test_a_normal_error_is_not_an_auth_failure(monkeypatch):
    """429 / 400 must not be mistaken for a dead token."""
    monkeypatch.setattr(bot_core, "TG_BOT_TOKEN", "live")
    monkeypatch.setattr(bot_core.requests, "post", lambda *a, **k: _Resp(
        400, {"ok": False, "error_code": 400, "description": "Bad Request"}))
    bot_core.send_message("hi", "111")
    assert bot_core.auth_failed() is False


def test_success_is_not_an_auth_failure(monkeypatch):
    monkeypatch.setattr(bot_core, "TG_BOT_TOKEN", "live")
    monkeypatch.setattr(bot_core.requests, "post",
                        lambda *a, **k: _Resp(200, {"ok": True}))
    bot_core.send_message("hi", "111")
    assert bot_core.auth_failed() is False


# ── The watchdog must not misread a 401 as "no webhook" ─────────

def test_dead_token_does_not_read_as_healthy_polling(monkeypatch):
    """webhook_status() returns {} on a 401 — that is NOT 'no webhook set'."""
    monkeypatch.setattr(bot_core, "TG_BOT_TOKEN", "dead")
    monkeypatch.setattr(bot_core, "TG_CHAT_ID", "OWNER")
    monkeypatch.setattr(bot_core.requests, "get",
                        lambda *a, **k: _Resp(401, UNAUTHORIZED))
    sent = []
    monkeypatch.setattr(bot_core, "send_message",
                        lambda *a, **k: sent.append(1))

    assert bot_core.warn_owner_if_webhook_broken({}) is False
    assert sent == [], "a warning would need the same dead token"
    assert bot_core.auth_failed() is True


# ── The loud failure ────────────────────────────────────────────

def test_monitor_exits_nonzero_on_dead_token(monkeypatch):
    import gold_monitor
    monkeypatch.setattr(gold_monitor, "main", lambda: None)
    monkeypatch.setattr(bot_core, "auth_failed", lambda: True)

    with pytest.raises(SystemExit) as exc:
        gold_monitor.run()
    assert "401" in str(exc.value)
    assert "GitHub repo" in str(exc.value), "must say where to fix it"


def test_monitor_exits_zero_when_token_is_fine(monkeypatch):
    import gold_monitor
    monkeypatch.setattr(gold_monitor, "main", lambda: None)
    monkeypatch.setattr(bot_core, "auth_failed", lambda: False)
    gold_monitor.run()  # must not raise


def test_crash_alert_is_skipped_when_the_token_is_dead(monkeypatch):
    """No point trying to send a crash report with a rejected token."""
    import gold_monitor
    monkeypatch.setattr(gold_monitor, "TG_BOT_TOKEN", "dead")
    monkeypatch.setattr(gold_monitor, "TG_CHAT_ID", "OWNER")
    monkeypatch.setattr(bot_core, "auth_failed", lambda: True)

    def boom():
        raise RuntimeError("gist exploded")
    monkeypatch.setattr(gold_monitor, "main", boom)
    sent = []
    monkeypatch.setattr(bot_core, "send_message", lambda *a, **k: sent.append(1))

    with pytest.raises(RuntimeError):
        gold_monitor.run()
    assert sent == []


def test_crash_alert_still_sent_when_the_token_is_fine(monkeypatch):
    import gold_monitor
    monkeypatch.setattr(gold_monitor, "TG_BOT_TOKEN", "live")
    monkeypatch.setattr(gold_monitor, "TG_CHAT_ID", "OWNER")
    monkeypatch.setattr(bot_core, "auth_failed", lambda: False)
    monkeypatch.setattr(gold_monitor.storage, "get_user_lang", lambda cid: "en")

    def boom():
        raise RuntimeError("gist exploded")
    monkeypatch.setattr(gold_monitor, "main", boom)
    sent = []
    monkeypatch.setattr(bot_core, "send_message", lambda *a, **k: sent.append(1))

    with pytest.raises(RuntimeError):
        gold_monitor.run()
    assert len(sent) == 1
