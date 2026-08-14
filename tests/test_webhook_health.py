"""Tests for the webhook watchdog.

The failure this guards against is the nastiest one the bot has: a webhook that
is REGISTERED but rejecting updates. The poller self-disables because a webhook
exists, the webhook drops everything, and nothing raises — commands just stop.
It went unnoticed for three months in practice.
"""

import time
from datetime import datetime, timedelta

import pytz

import bot_commands
import bot_core
import storage

UTC = pytz.UTC


def _info(url="https://x.vercel.app/api/webhook", error="", error_age_min=None,
          pending=0):
    out = {"url": url, "pending_update_count": pending}
    if error:
        out["last_error_message"] = error
        if error_age_min is not None:
            out["last_error_date"] = int(
                (datetime.now(UTC) - timedelta(minutes=error_age_min)).timestamp())
    return out


# ── webhook_health ──────────────────────────────────────────────

def test_no_webhook_is_not_unhealthy():
    """Polling setup — absence of a webhook is a valid state, not a fault."""
    h = bot_core.webhook_health({})
    assert h["configured"] is False
    assert h["healthy"] is True


def test_working_webhook_is_healthy():
    h = bot_core.webhook_health(_info())
    assert h["configured"] is True and h["healthy"] is True and h["reason"] is None


def test_recent_error_is_unhealthy():
    h = bot_core.webhook_health(_info(error="Wrong response from the webhook: 403",
                                      error_age_min=5))
    assert h["healthy"] is False
    assert h["reason"] == "error"
    assert "403" in h["error"]


def test_stale_error_is_ignored():
    """An error from days ago that has since recovered must not warn forever."""
    h = bot_core.webhook_health(_info(error="403", error_age_min=60 * 48))
    assert h["healthy"] is True


def test_backlog_without_error_is_unhealthy():
    h = bot_core.webhook_health(_info(pending=bot_core.WEBHOOK_PENDING_ALERT))
    assert h["healthy"] is False
    assert h["reason"] == "backlog"


def test_small_backlog_is_fine():
    h = bot_core.webhook_health(_info(pending=1))
    assert h["healthy"] is True


def test_error_without_timestamp_is_not_treated_as_recent():
    h = bot_core.webhook_health(_info(error="something", error_age_min=None))
    assert h["healthy"] is True


def test_garbage_error_date_does_not_raise():
    info = _info(error="boom")
    info["last_error_date"] = "not-a-timestamp"
    assert bot_core.webhook_health(info)["healthy"] is True


# ── warn_owner_if_webhook_broken ────────────────────────────────

class _Harness:
    def __init__(self, monkeypatch, info):
        self.sent = []
        monkeypatch.setattr(bot_core, "TG_BOT_TOKEN", "token")
        monkeypatch.setattr(bot_core, "TG_CHAT_ID", "OWNER")
        monkeypatch.setattr(bot_core, "webhook_status", lambda: info)
        monkeypatch.setattr(bot_core, "send_message",
                            lambda text, chat_id="", **kw: self.sent.append((chat_id, text)))
        monkeypatch.setattr(storage, "get_user_lang", lambda cid: "en")


def test_warns_the_owner_on_a_broken_webhook(monkeypatch):
    h = _Harness(monkeypatch, _info(error="Wrong response from the webhook: 403",
                                    error_age_min=2))
    state = {}
    assert bot_core.warn_owner_if_webhook_broken(state) is True
    assert len(h.sent) == 1
    chat_id, text = h.sent[0]
    assert chat_id == "OWNER"
    assert "rejecting updates" in text
    assert "403" in text
    assert "setup_webhook.py" in text, "the message must say how to fix it"
    assert "webhook_warned_at" in state


def test_warning_goes_only_to_the_owner(monkeypatch):
    h = _Harness(monkeypatch, _info(error="403", error_age_min=2))
    bot_core.warn_owner_if_webhook_broken({})
    assert {cid for cid, _ in h.sent} == {"OWNER"}


def test_healthy_webhook_warns_nobody(monkeypatch):
    h = _Harness(monkeypatch, _info())
    assert bot_core.warn_owner_if_webhook_broken({}) is False
    assert h.sent == []


def test_throttled_within_the_interval(monkeypatch):
    h = _Harness(monkeypatch, _info(error="403", error_age_min=2))
    state = {"webhook_warned_at": datetime.now(UTC).isoformat()}
    assert bot_core.warn_owner_if_webhook_broken(state) is False
    assert h.sent == [], "must not nag every run"


def test_warns_again_after_the_interval(monkeypatch):
    h = _Harness(monkeypatch, _info(error="403", error_age_min=2))
    old = datetime.now(UTC) - timedelta(hours=bot_core.WEBHOOK_WARN_INTERVAL_H + 1)
    state = {"webhook_warned_at": old.isoformat()}
    assert bot_core.warn_owner_if_webhook_broken(state) is True
    assert len(h.sent) == 1


def test_recovery_clears_the_stamp(monkeypatch):
    """So the NEXT outage warns immediately instead of waiting out a throttle."""
    _Harness(monkeypatch, _info())
    state = {"webhook_warned_at": datetime.now(UTC).isoformat()}
    assert bot_core.warn_owner_if_webhook_broken(state) is True
    assert "webhook_warned_at" not in state


def test_unparseable_stamp_does_not_suppress(monkeypatch):
    h = _Harness(monkeypatch, _info(error="403", error_age_min=2))
    state = {"webhook_warned_at": "garbage"}
    assert bot_core.warn_owner_if_webhook_broken(state) is True
    assert len(h.sent) == 1


def test_never_raises_even_if_everything_fails(monkeypatch):
    """A monitoring check must not break the thing it monitors."""
    monkeypatch.setattr(bot_core, "TG_BOT_TOKEN", "token")
    monkeypatch.setattr(bot_core, "TG_CHAT_ID", "OWNER")

    def boom():
        raise OSError("network down")
    monkeypatch.setattr(bot_core, "webhook_status", boom)
    assert bot_core.warn_owner_if_webhook_broken({}) is False


def test_no_credentials_is_a_noop(monkeypatch):
    monkeypatch.setattr(bot_core, "TG_BOT_TOKEN", "")
    monkeypatch.setattr(bot_core, "TG_CHAT_ID", "")
    assert bot_core.warn_owner_if_webhook_broken({}) is False


def test_error_message_is_escaped(monkeypatch):
    """Telegram's error text is third-party content in an HTML message."""
    h = _Harness(monkeypatch, _info(error="<b>bad</b> & worse", error_age_min=1))
    bot_core.warn_owner_if_webhook_broken({})
    _, text = h.sent[0]
    assert "<b>bad</b>" not in text
    assert "&lt;b&gt;bad&lt;/b&gt;" in text and "&amp;" in text


def test_warning_is_localised(monkeypatch):
    h = _Harness(monkeypatch, _info(error="403", error_age_min=1))
    monkeypatch.setattr(storage, "get_user_lang", lambda cid: "th")
    bot_core.warn_owner_if_webhook_broken({})
    assert "Webhook ปฏิเสธ" in h.sent[0][1]


# ── Poller integration ──────────────────────────────────────────

def test_poller_checks_health_before_stepping_aside(monkeypatch):
    """Skipping the poll is only safe if the webhook actually works."""
    monkeypatch.setattr(bot_core, "webhook_is_configured", lambda: True)
    saved = []
    monkeypatch.setattr(storage, "load_bot_state", lambda: {"update_offset": 5})
    monkeypatch.setattr(storage, "save_bot_state", lambda s: saved.append(s))
    checked = []
    monkeypatch.setattr(bot_core, "warn_owner_if_webhook_broken",
                        lambda state: checked.append(state) or True)

    def must_not_poll(offset=0):
        raise AssertionError("poller must not call getUpdates while a webhook is set")
    monkeypatch.setattr(bot_core, "get_updates", must_not_poll)

    bot_commands.process_commands()

    assert len(checked) == 1, "health must be checked before skipping"
    assert len(saved) == 1, "throttle stamp must be persisted"


def test_poller_still_polls_when_no_webhook(monkeypatch):
    monkeypatch.setattr(bot_core, "webhook_is_configured", lambda: False)
    monkeypatch.setattr(storage, "load_bot_state", lambda: {"update_offset": 5})
    monkeypatch.setattr(storage, "save_bot_state", lambda s: None)
    monkeypatch.setattr(bot_core, "get_updates", lambda offset=0: [])
    warned = []
    monkeypatch.setattr(bot_core, "warn_owner_if_webhook_broken",
                        lambda state: warned.append(1) or False)

    bot_commands.process_commands()
    assert warned == [], "no webhook means nothing to warn about"


# ── setup_webhook.py error reporting ────────────────────────────
#
# Telegram keeps last_error_message long after the fault clears, so the setup
# script has to distinguish "failing right now" from "failed earlier, since
# fixed" — otherwise it tells you nothing at the exact moment you are trying
# to confirm a fix.

import setup_webhook


def test_setup_reports_still_failing(capsys):
    now = time.time()
    setup_webhook._report_last_error(
        {"last_error_message": "Wrong response from the webhook: 403 Forbidden",
         "last_error_date": int(now - 5)},
        registered_at=now - 30,
    )
    out = capsys.readouterr().out
    assert "STILL FAILING" in out
    assert "does not match" in out, "must name the likely cause"


def test_setup_reports_stale_error(capsys):
    now = time.time()
    setup_webhook._report_last_error(
        {"last_error_message": "403 Forbidden", "last_error_date": int(now - 7200)},
        registered_at=now - 30,
    )
    out = capsys.readouterr().out
    assert "PRE-DATES" in out
    assert "STILL FAILING" not in out


def test_setup_reports_healthy(capsys):
    setup_webhook._report_last_error({}, registered_at=time.time())
    assert "healthy" in capsys.readouterr().out


def test_setup_handles_missing_timestamp(capsys):
    setup_webhook._report_last_error(
        {"last_error_message": "boom"}, registered_at=time.time())
    out = capsys.readouterr().out
    assert "no timestamp" in out
    assert "STILL FAILING" not in out, "cannot claim that without a timestamp"


def test_ago_formatting():
    assert setup_webhook._ago(5) == "5s ago"
    assert setup_webhook._ago(300) == "5m ago"
    assert setup_webhook._ago(7200) == "2h 0m ago"
    assert setup_webhook._ago(200000) == "2d ago"
    assert setup_webhook._ago(-10) == "0s ago", "clock skew must not go negative"
