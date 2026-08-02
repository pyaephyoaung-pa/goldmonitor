import bot_core


def _capture(monkeypatch):
    sent = []
    monkeypatch.setattr(bot_core, "send_message", lambda text, chat_id="": sent.append((chat_id, text)))
    return sent


def _update(text, chat_id="999"):
    return {"message": {"text": text, "chat": {"id": chat_id}}}


def test_parse_command_plain():
    assert bot_core._parse_command("/price") == ("/price", "")
    assert bot_core._parse_command("/history 5") == ("/history", "5")


def test_parse_command_strips_botname():
    assert bot_core._parse_command("/price@MyBot") == ("/price", "")


def test_parse_command_glued_prefix():
    # Bracketed template form is recovered: /bought<5000> -> ("/bought", "5000")
    assert bot_core._parse_command("/bought<5000>") == ("/bought", "5000")
    # Letters glued to digits cannot be split unambiguously, so it is left as-is
    # (matches original behaviour -- would be flagged as an unknown command).
    assert bot_core._parse_command("/bought5000") == ("/bought5000", "")


def test_unknown_command(monkeypatch):
    sent = _capture(monkeypatch)
    handled = bot_core.dispatch_update(_update("/nope"))
    assert handled is False
    assert any("Unknown command" in t for _, t in sent)


def test_owner_command_blocked_for_non_owner(monkeypatch):
    sent = _capture(monkeypatch)
    monkeypatch.setattr(bot_core, "TG_CHAT_ID", "111")  # owner is 111
    handled = bot_core.dispatch_update(_update("/portfolio", chat_id="222"))
    assert handled is False
    assert any("🔒" in t for _, t in sent)


def test_owner_command_allowed_for_owner(monkeypatch):
    sent = _capture(monkeypatch)
    called = {}
    monkeypatch.setattr(bot_core, "TG_CHAT_ID", "111")
    monkeypatch.setattr(bot_core, "cmd_portfolio", lambda cid, lang: called.setdefault("cid", cid))
    handled = bot_core.dispatch_update(_update("/portfolio", chat_id="111"))
    assert handled is True
    assert called.get("cid") == "111"


def test_public_command_routes(monkeypatch):
    _capture(monkeypatch)
    called = {}
    monkeypatch.setattr(bot_core, "cmd_price", lambda cid, lang: called.setdefault("cid", cid))
    handled = bot_core.dispatch_update(_update("/price", chat_id="222"))
    assert handled is True
    assert called.get("cid") == "222"


def test_macro_command_routes(monkeypatch):
    _capture(monkeypatch)
    called = {}
    monkeypatch.setattr(bot_core, "cmd_macro", lambda cid, lang: called.setdefault("cid", cid))
    handled = bot_core.dispatch_update(_update("/macro", chat_id="222"))
    assert handled is True
    assert called.get("cid") == "222"


def test_non_command_ignored(monkeypatch):
    _capture(monkeypatch)
    assert bot_core.dispatch_update(_update("hello there")) is False
