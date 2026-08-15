"""Tests for the per-user interface language (English / Myanmar / Thai)."""

import re

import pytest

import bot_core
import gold_monitor
import i18n
import storage


class _MemStore:
    def __init__(self, monkeypatch):
        self.files = {}
        monkeypatch.setattr(
            storage, "_read_file",
            lambda f: self.files.get(
                f, [] if f in (storage.PRICE_HISTORY_FILE, storage.BUY_LOG_FILE) else {}))
        monkeypatch.setattr(storage, "_write_file",
                            lambda f, d: self.files.__setitem__(f, d))


# ── Catalogue integrity ─────────────────────────────────────────

def test_every_string_has_every_language():
    """A missing translation must fail here, not silently fall back in prod."""
    missing = [
        f"{key}:{code}"
        for key, entry in i18n.STRINGS.items()
        for code in i18n.LANGUAGES
        if not entry.get(code)
    ]
    assert not missing, f"missing translations: {missing}"


def test_placeholders_match_across_languages():
    """Same {placeholders} everywhere, or .format() breaks in one language only."""
    pattern = re.compile(r"\{(\w+)")
    mismatches = []
    for key, entry in i18n.STRINGS.items():
        expected = set(pattern.findall(entry[i18n.DEFAULT_LANG]))
        for code in i18n.LANGUAGES:
            found = set(pattern.findall(entry[code]))
            if found != expected:
                mismatches.append(f"{key}/{code}: {found} != {expected}")
    assert not mismatches, mismatches


def test_no_stray_unescaped_ampersand():
    """Telegram HTML mode requires &amp; — a bare & can 400 the send."""
    offenders = [
        f"{key}/{code}"
        for key, entry in i18n.STRINGS.items()
        for code, text in entry.items()
        if re.search(r"&(?!amp;|lt;|gt;|quot;|#)", text)
    ]
    assert not offenders, offenders


# ── normalize / is_supported ────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("en", "en"), ("EN", "en"), ("English", "en"), ("eng", "en"),
    ("my", "my"), ("mm", "my"), ("Burmese", "my"), ("မြန်မာ", "my"),
    ("th", "th"), ("Thai", "th"), ("ไทย", "th"), ("  th  ", "th"),
])
def test_normalize_accepts_aliases(raw, expected):
    assert i18n.normalize(raw) == expected


@pytest.mark.parametrize("raw", ["", "klingon", None, 42, "e", "jp"])
def test_normalize_falls_back_to_default(raw):
    assert i18n.normalize(raw) == i18n.DEFAULT_LANG


def test_is_supported_rejects_unknown():
    assert i18n.is_supported("th") is True
    assert i18n.is_supported("Thai") is True
    assert i18n.is_supported("klingon") is False
    assert i18n.is_supported(None) is False


def test_default_language_is_myanmar():
    """Existing users must keep the language they already had."""
    assert i18n.DEFAULT_LANG == "my"
    assert storage.PREF_DEFAULTS["lang"] == "my"


# ── t() ─────────────────────────────────────────────────────────

def test_t_renders_each_language_differently():
    en = i18n.t("portfolio.header", "en")
    my = i18n.t("portfolio.header", "my")
    th = i18n.t("portfolio.header", "th")
    assert en != my != th
    assert "Gold Portfolio" in en
    assert "ရွှေ" in my
    assert "พอร์ต" in th


def test_t_substitutes_params():
    assert "#7" in i18n.t("delete.not_found", "en", index=7)
    assert "#7" in i18n.t("delete.not_found", "th", index=7)


def test_t_unknown_key_returns_key():
    """Degrade to something inspectable rather than crashing a broadcast."""
    assert i18n.t("no.such.key", "en") == "no.such.key"


def test_t_missing_param_does_not_raise():
    out = i18n.t("delete.not_found", "en")  # no index=
    assert isinstance(out, str) and out


def test_t_unknown_language_uses_default():
    assert i18n.t("portfolio.header", "klingon") == i18n.t("portfolio.header", "my")


def test_t_allows_lang_as_a_placeholder_name():
    """key/lang are positional-only, so **params may reuse those names."""
    out = i18n.t("lang.ok", "th", lang="ไทย")
    assert "ไทย" in out
    assert i18n.t("lang.ok", "en", lang="English", key="ignored")


# ── /lang command ───────────────────────────────────────────────

def _capture(monkeypatch):
    sent = []
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="", **kw: sent.append(text))
    return sent


def test_lang_command_sets_preference(monkeypatch):
    _MemStore(monkeypatch)
    sent = _capture(monkeypatch)

    bot_core.cmd_lang("111", "th", "my")

    assert storage.get_user_lang("111") == "th"
    # Confirmation is rendered in the NEW language, so the user can tell at a
    # glance whether they picked the one they wanted.
    assert "ตั้งภาษา" in sent[-1]


def test_lang_command_accepts_aliases(monkeypatch):
    _MemStore(monkeypatch)
    _capture(monkeypatch)
    for raw, expected in [("English", "en"), ("MM", "my"), ("ไทย", "th")]:
        bot_core.cmd_lang("111", raw, "my")
        assert storage.get_user_lang("111") == expected


def test_lang_without_args_shows_current(monkeypatch):
    _MemStore(monkeypatch)
    sent = _capture(monkeypatch)
    storage.set_user_pref("111", "lang", "en")

    bot_core.cmd_lang("111", "", "en")

    assert "/lang en" in sent[-1]
    assert i18n.LANGUAGES["en"] in sent[-1]
    assert storage.get_user_lang("111") == "en", "showing must not change it"


def test_lang_rejects_unknown_language(monkeypatch):
    _MemStore(monkeypatch)
    sent = _capture(monkeypatch)
    storage.set_user_pref("111", "lang", "en")

    bot_core.cmd_lang("111", "klingon", "en")

    assert storage.get_user_lang("111") == "en", "unknown input must not change it"
    assert "Unknown language" in sent[-1], "rejection must be explicit"
    assert "klingon" in sent[-1]
    assert "/lang" in sent[-1], "usage should still be shown"


def test_lang_rejection_escapes_user_input(monkeypatch):
    _MemStore(monkeypatch)
    sent = _capture(monkeypatch)
    bot_core.cmd_lang("111", "<b>x</b>", "en")
    assert "<b>x</b>" not in sent[-1]
    assert "&lt;b&gt;" in sent[-1]


def test_lang_survives_other_pref_changes(monkeypatch):
    _MemStore(monkeypatch)
    _capture(monkeypatch)
    bot_core.cmd_lang("111", "th", "my")
    bot_core.cmd_quiet("111", "22-7", "th")
    bot_core.cmd_mute("111", "morning", "th")

    prefs = storage.get_user_prefs("111")
    assert prefs["lang"] == "th"
    assert prefs["quiet"] == "22-7"
    assert prefs["morning"] is False


def test_lang_survives_new_subscriber(monkeypatch):
    _MemStore(monkeypatch)
    _capture(monkeypatch)
    bot_core.cmd_lang("111", "th", "my")
    storage.add_subscriber("222")
    assert storage.get_user_lang("111") == "th"


# ── dispatch threads the language through ───────────────────────

def test_dispatch_passes_user_language(monkeypatch):
    _MemStore(monkeypatch)
    _capture(monkeypatch)
    storage.set_user_pref("555", "lang", "th")
    seen = {}
    monkeypatch.setattr(bot_core, "cmd_price",
                        lambda cid, lang: seen.update(cid=cid, lang=lang))

    bot_core.dispatch_update(
        {"message": {"text": "/price", "chat": {"id": "555"}}})

    assert seen == {"cid": "555", "lang": "th"}


def test_unknown_command_replies_in_user_language(monkeypatch):
    _MemStore(monkeypatch)
    sent = _capture(monkeypatch)
    storage.set_user_pref("555", "lang", "th")

    bot_core.dispatch_update(
        {"message": {"text": "/nope", "chat": {"id": "555"}}})

    assert "ไม่รู้จักคำสั่ง" in sent[-1]


def test_help_keyboard_is_localised():
    th = bot_core.main_keyboard("th")
    en = bot_core.main_keyboard("en")
    th_labels = [b["text"] for row in th["inline_keyboard"] for b in row]
    en_labels = [b["text"] for row in en["inline_keyboard"] for b in row]
    assert th_labels != en_labels
    # callback_data must stay the raw command in every language
    for kb in (th, en):
        assert any(b["callback_data"] == "/price"
                   for row in kb["inline_keyboard"] for b in row)


# ── Broadcasts render per recipient language ────────────────────

def test_notify_renders_each_language_once(monkeypatch):
    store = _MemStore(monkeypatch)
    store.files[storage.SUBSCRIBERS_FILE] = {
        "chat_ids": ["222", "333", "444", "555"],
        "prefs": {
            "222": {"lang": "en"},
            "333": {"lang": "th"},
            "444": {"lang": "en"},
            # 555 has no lang -> default (my)
        },
    }
    monkeypatch.setattr(gold_monitor, "TG_BOT_TOKEN", "x")
    monkeypatch.setattr(gold_monitor, "TG_CHAT_ID", "")
    monkeypatch.setattr(gold_monitor.time, "sleep", lambda s: None)

    sent = []
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="", **kw: (sent.append((chat_id, text)),
                                                        {"ok": True})[1])
    builds = []

    def build(lang):
        builds.append(lang)
        return i18n.t("portfolio.header", lang)

    gold_monitor.notify(build, "alerts")

    assert len(sent) == 4, "every subscriber should receive the message"
    # Three distinct languages present -> exactly three renders, not four.
    assert sorted(builds) == ["en", "my", "th"]

    by_chat = dict(sent)
    assert by_chat["222"] == by_chat["444"] == i18n.t("portfolio.header", "en")
    assert by_chat["333"] == i18n.t("portfolio.header", "th")
    assert by_chat["555"] == i18n.t("portfolio.header", "my")


def test_notify_still_accepts_a_plain_string(monkeypatch):
    store = _MemStore(monkeypatch)
    store.files[storage.SUBSCRIBERS_FILE] = {"chat_ids": ["222"], "prefs": {}}
    monkeypatch.setattr(gold_monitor, "TG_BOT_TOKEN", "x")
    monkeypatch.setattr(gold_monitor, "TG_CHAT_ID", "")
    sent = []
    monkeypatch.setattr(bot_core, "send_message",
                        lambda text, chat_id="", **kw: (sent.append(text),
                                                        {"ok": True})[1])

    gold_monitor.notify("plain text", "alerts")
    assert sent == ["plain text"]


def test_weekly_block_is_localised():
    from datetime import datetime, timedelta
    import pytz
    bkk = pytz.timezone("Asia/Bangkok")
    now = datetime.now(bkk)
    hist = [{"ts": (now - timedelta(hours=167 - i)).isoformat(),
             "thb_gram": 4000.0 + i * 0.5, "usd_oz": 2400.0 + i * 0.25}
            for i in range(168)]

    en = gold_monitor.build_weekly_block(hist, "en")
    th = gold_monitor.build_weekly_block(hist, "th")
    assert "Weekly Recap" in en
    assert "สรุปรายสัปดาห์" in th
