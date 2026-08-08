"""
Unified Telegram bot core for Gold Monitor.

This module is the single source of truth for:
  * sending / receiving Telegram messages
  * every /command handler
  * command dispatch (owner checks, prefix matching)

Both entrypoints — bot_commands.py (polling) and api/webhook.py (instant
webhook) — are now thin wrappers around dispatch_update() here. Previously each
held its own ~400-line copy of these handlers, which drifted out of sync.
"""

from __future__ import annotations

import os
import re
import time
import html as html_module
from datetime import datetime

import pytz
import requests

import events
import i18n
import news
import storage
import predictor
import regime
import goldapi
import signals
from gold_format import fmt, gold_breakdown

BANGKOK_TZ = pytz.timezone("Asia/Bangkok")
TG_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


# ── Telegram I/O ────────────────────────────────────────────────

def send_message(text: str, chat_id: str = "", reply_markup: dict | None = None) -> dict | None:
    """Send a Telegram message (HTML), with a plain-text retry on parse errors.

    `reply_markup` optionally attaches an inline keyboard.
    Returns the Telegram API response dict (or None on hard failure) so callers
    can react to error codes (e.g. 403 = bot blocked).
    """
    cid = chat_id or TG_CHAT_ID
    if not TG_BOT_TOKEN or not cid:
        print(f"[bot] No credentials. Message:\n{text}")
        return None
    payload = {"chat_id": cid, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=10,
        )
        resp = r.json()
        if resp.get("ok"):
            return resp
        print(f"[bot] Telegram error: {resp.get('description')} (code={resp.get('error_code')})")
        # 429 Too Many Requests — respect Telegram's retry_after and retry once.
        if resp.get("error_code") == 429:
            wait = min(resp.get("parameters", {}).get("retry_after", 1), 30)
            print(f"[bot] Rate limited — retrying after {wait}s")
            time.sleep(wait)
            # Resend the ORIGINAL payload — rebuilding it here used to drop
            # reply_markup, so a rate-limited /help arrived with no buttons.
            r = requests.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                json=payload,
                timeout=10,
            )
            return r.json()
        # Retry without HTML parse_mode in case of a formatting error
        if resp.get("error_code") == 400:
            r2 = requests.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": text},
                timeout=10,
            )
            resp2 = r2.json()
            print(f"[bot] Retry without HTML: {'OK' if resp2.get('ok') else 'failed'}")
            return resp2
        return resp
    except Exception as e:
        print(f"[bot] Send error: {e}")
        return None


def answer_callback_query(callback_id: str):
    """Ack a button press so Telegram stops showing the loading spinner."""
    if not TG_BOT_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback_id},
            timeout=10,
        )
    except Exception as e:
        print(f"[bot] answerCallbackQuery error: {e}")


def send_photo(photo_url: str, caption: str, chat_id: str = "") -> dict | None:
    """Send a photo by URL via Telegram sendPhoto."""
    cid = chat_id or TG_CHAT_ID
    if not TG_BOT_TOKEN or not cid:
        print(f"[bot] No credentials. Photo: {photo_url}")
        return None
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto",
            json={"chat_id": cid, "photo": photo_url,
                  "caption": caption, "parse_mode": "HTML"},
            timeout=15,
        )
        resp = r.json()
        if not resp.get("ok"):
            print(f"[bot] sendPhoto error: {resp.get('description')}")
        return resp
    except Exception as e:
        print(f"[bot] sendPhoto error: {e}")
        return None


def get_updates(offset: int = 0) -> list:
    """Fetch new Telegram messages (long-poll)."""
    if not TG_BOT_TOKEN:
        return []
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 5, "limit": 20},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("result", [])
    except Exception as e:
        print(f"[bot] getUpdates error: {e}")
        return []


def webhook_is_configured() -> bool:
    """True if a Telegram webhook URL is set.

    Telegram refuses getUpdates (HTTP 409) while a webhook is active, so the
    poller uses this to self-disable and avoid wasted, conflicting runs.
    """
    if not TG_BOT_TOKEN:
        return False
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getWebhookInfo",
            timeout=10,
        )
        r.raise_for_status()
        return bool(r.json().get("result", {}).get("url"))
    except Exception as e:
        print(f"[bot] getWebhookInfo error: {e}")
        return False


# ── Command Handlers ────────────────────────────────────────────
#
# Every handler takes the caller's language as its last argument. dispatch_update
# resolves it ONCE per update and threads it through, so a command costs no extra
# Gist read no matter how many strings it renders.

def cmd_price(chat_id: str, lang: str):
    thb_gram, usd_oz, thb_rate = goldapi.get_gold_price()
    if thb_gram is None:
        send_message(i18n.t("err.price_fetch", lang), chat_id)
        return

    history = storage.get_price_history()
    trend = predictor.get_trend_summary(history) if history else {}
    gb = gold_breakdown(thb_gram)

    lines = [
        i18n.t("price.header", lang),
        "━━━━━━━━━━━━━━━",
        i18n.t("price.pure", lang),
        i18n.t("price.baht_weight", lang, value=fmt(gb["baht_9999"])),
        i18n.t("price.per_gram", lang, value=fmt(gb["gram_9999"])),
        i18n.t("price.jewelry", lang),
        i18n.t("price.baht_weight", lang, value=fmt(gb["baht_9650"])),
        i18n.t("price.per_gram", lang, value=fmt(gb["gram_9650"])),
        "━━━━━━━━━━━━━━━",
        i18n.t("price.spot", lang, value=usd_oz),
        i18n.t("price.rate", lang, value=thb_rate),
    ]

    if trend.get("change_1h") is not None:
        lines.append(i18n.t("price.changes_header", lang))
        for key, label in [("change_1h", "1h"), ("change_4h", "4h"),
                           ("change_24h", "24h"), ("change_7d", "7d")]:
            if key in trend:
                arrow = "📈" if trend[key] > 0 else "📉" if trend[key] < 0 else "➡️"
                lines.append(f"  {arrow} {label}: {trend[key]:+.3f}%")

    if len(history) >= 14:
        ta = predictor.analyze(history)
        if ta.get("overall_signal"):
            lines.append(i18n.t("price.signal", lang, signal=ta["overall_signal"]))
        if ta.get("rsi"):
            lines.append(i18n.t("price.rsi", lang, value=ta["rsi"]))

    send_message("\n".join(lines), chat_id)


def cmd_predict(chat_id: str, lang: str):
    history = storage.get_price_history()
    if len(history) < 15:
        send_message(i18n.t("predict.need_data", lang, n=len(history)), chat_id)
        return

    model_data = storage.load_model_data()
    # Score any matured predictions first so the hit-rate shown is current.
    if predictor.resolve_predictions(model_data, history):
        storage.save_model_data(model_data)
    prediction = predictor.predict(history, model_data, lang)
    prediction["hit_rates"] = predictor.prediction_hit_rates(model_data)
    msg = predictor.format_prediction_message(prediction, lang)
    send_message(msg, chat_id)


# ── /chart — price chart via QuickChart (no matplotlib dependency) ──

QUICKCHART_CREATE_URL = "https://quickchart.io/chart/create"
CHART_MAX_POINTS = 96  # downsample target so the config stays small


def _downsample(items: list, max_points: int) -> list:
    """Evenly thin a list to at most max_points, always keeping the last item."""
    if len(items) <= max_points:
        return items
    step = len(items) / max_points
    sampled = [items[int(i * step)] for i in range(max_points)]
    if sampled[-1] is not items[-1]:
        sampled[-1] = items[-1]
    return sampled


def chart_points(history: list, days: int) -> list:
    """The priced points backing both the chart and its caption.

    Single source of truth on purpose: the caption used to slice the raw
    history and filter afterwards, while the config filtered and then sliced,
    so any entry missing "thb_gram" made the two disagree about the window —
    and could leave the caption with an empty list to index.
    """
    return [h for h in history if "thb_gram" in h][-days * 24:]


def build_chart_config(history: list, days: int) -> dict | None:
    """Build a Chart.js config for the last `days` of price history."""
    points = chart_points(history, days)
    if len(points) < 2:
        return None
    points = _downsample(points, CHART_MAX_POINTS)
    labels = [p["ts"][5:16].replace("T", " ") for p in points]  # "MM-DD HH:MM"
    prices = [p["thb_gram"] for p in points]
    return {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [{
                "label": "THB/gram (99.99%)",
                "data": prices,
                "borderColor": "#d4a017",
                "backgroundColor": "rgba(212,160,23,0.15)",
                "fill": True,
                "pointRadius": 0,
                "borderWidth": 2,
                "tension": 0.2,
            }],
        },
        "options": {
            "title": {"display": True, "text": f"Gold Price — last {days}d"},
            "legend": {"display": False},
            "scales": {
                "xAxes": [{"ticks": {"maxTicksLimit": 8, "fontSize": 9}}],
                "yAxes": [{"ticks": {"maxTicksLimit": 8}}],
            },
        },
    }


def _quickchart_short_url(config: dict) -> str | None:
    """Create a short chart URL via QuickChart's create endpoint."""
    try:
        r = requests.post(
            QUICKCHART_CREATE_URL,
            json={"chart": config, "width": 800, "height": 420,
                  "backgroundColor": "white"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("success") and data.get("url"):
            return data["url"]
    except Exception as e:
        print(f"[bot] quickchart error: {e}")
    return None


def cmd_chart(chat_id: str, args: str, lang: str):
    try:
        days = int(args.strip()) if args.strip() else 7
    except ValueError:
        days = 7
    days = max(1, min(days, 30))

    history = storage.get_price_history()
    config = build_chart_config(history, days)
    if config is None:
        send_message(i18n.t("chart.no_data", lang), chat_id)
        return

    url = _quickchart_short_url(config)
    if url is None:
        send_message(i18n.t("chart.unavailable", lang), chat_id)
        return

    prices = [p["thb_gram"] for p in chart_points(history, days)]
    change = ((prices[-1] - prices[0]) / prices[0]) * 100 if prices[0] else 0
    caption = i18n.t(
        "chart.caption", lang,
        days=days, now=fmt(prices[-1]), arrow="📈" if change >= 0 else "📉",
        change=change, high=fmt(max(prices)), low=fmt(min(prices)),
    )
    resp = send_photo(url, caption, chat_id)
    if not resp or not resp.get("ok"):
        # Fallback: at least give the user the link.
        send_message(f"{caption}\n🔗 {url}", chat_id)


def cmd_macro(chat_id: str, lang: str):
    """Macro context (DXY / US10Y / VIX) plus the current market regime.

    The regime half needs no network at all — it is computed from the price
    history we already store — so it is still shown when the macro fetch fails.
    """
    macro = signals.fetch_macro()
    block = signals.format_macro_block(macro, lang) if macro else ""

    history = storage.get_price_history()
    vol = regime.vol_regime(history)
    div_key = regime.divergence(
        predictor.get_trend_summary(history).get("change_24h") if len(history) >= 2 else None,
        macro,
    )

    lines = []
    if block:
        lines += [block, "━━━━━━━━━━━━━━━"]

    lines.append(i18n.t("regime.header", lang))
    if not vol.get("available"):
        lines.append(i18n.t("regime.unavailable", lang,
                            have=vol.get("have", 0), need=vol.get("need", 0)))
    elif vol["level"] == "extreme":
        lines.append(i18n.t("regime.vol_extreme", lang,
                            ratio=regime.display_ratio(vol["ratio"])))
    elif vol["level"] == "elevated":
        lines.append(i18n.t("regime.vol_elevated", lang,
                            ratio=regime.display_ratio(vol["ratio"])))
    elif vol["level"] == "calm":
        lines.append(i18n.t("regime.calm", lang,
                            ratio=regime.display_ratio(vol["ratio"])))
    else:
        lines.append(i18n.t("regime.normal", lang,
                            ratio=regime.display_ratio(vol["ratio"])))

    if vol.get("shock"):
        lines.append(i18n.t("regime.shock", lang,
                            sigma=regime.display_sigma(vol["sigma"]),
                            move=vol["last_move"]))
    if div_key:
        lines.append(i18n.t(div_key, lang))

    if not block and not vol.get("available"):
        send_message(i18n.t("macro.unavailable", lang), chat_id)
        return

    lines += ["━━━━━━━━━━━━━━━", i18n.t("macro.footer", lang)]
    send_message("\n".join(lines), chat_id)


# ── /events — scheduled high-impact releases ────────────────────

def format_countdown(hours: float, lang: str) -> str:
    """"3d 4h" / "4h 20m" — coarse on purpose, these are not to-the-second."""
    total_min = max(0, int(hours * 60))
    if total_min >= 24 * 60:
        return i18n.t("events.countdown_d", lang,
                      d=total_min // (24 * 60), h=(total_min % (24 * 60)) // 60)
    return i18n.t("events.countdown_h", lang, h=total_min // 60, m=total_min % 60)


def format_event_line(event, now, lang: str) -> str:
    return i18n.t(
        "events.line", lang,
        emoji=event.emoji,
        name=i18n.t(event.label_key, lang),
        est=i18n.t("events.estimated", lang) if event.estimated else "",
        when=event.when(BANGKOK_TZ).strftime("%a %d %b, %H:%M"),
        countdown=format_countdown(event.hours_until(now), lang),
    )


def cmd_events(chat_id: str, lang: str):
    now = datetime.now(pytz.UTC)
    upcoming = events.upcoming(now, limit=6)
    if not upcoming:
        send_message(i18n.t("events.none", lang), chat_id)
        return

    lines = [i18n.t("events.header", lang), "━━━━━━━━━━━━━━━"]
    lines += [format_event_line(e, now, lang) for e in upcoming]
    lines += ["━━━━━━━━━━━━━━━", i18n.t("events.footer", lang)]

    # Only the owner can act on a stale calendar, so only the owner is told.
    status = events.calendar_status(now)
    if status["stale"] and TG_CHAT_ID and chat_id == TG_CHAT_ID:
        lines.append("")
        lines.append(i18n.t("events.stale", lang, days=status["days_left"]))

    send_message("\n".join(lines), chat_id)


def cmd_news(chat_id: str, lang: str):
    """Recent gold-related headlines. Context only — nothing is interpreted."""
    headlines = news.fetch_headlines()
    if not headlines:
        # An empty list means either "source down" or "genuinely nothing", and
        # the fetch layer logs which. Tell the user the recoverable one.
        send_message(i18n.t("news.unavailable", lang), chat_id)
        return
    send_message(news.format_block(headlines, lang).lstrip("\n"), chat_id)


def cmd_bought(chat_id: str, args: str, lang: str):
    try:
        amount = float(args.strip())
    except (ValueError, AttributeError):
        send_message(i18n.t("bought.usage", lang), chat_id)
        return

    if amount <= 0:
        send_message(i18n.t("err.amount_positive", lang), chat_id)
        return

    thb_gram, _, _ = goldapi.get_gold_price()
    if thb_gram is None:
        send_message(i18n.t("err.price_fetch_retry", lang), chat_id)
        return

    entry = storage.log_buy(amount, thb_gram)
    send_message(
        i18n.t("bought.ok", lang, amount=fmt(amount), price=fmt(thb_gram),
               grams=entry["grams"],
               when=datetime.now(BANGKOK_TZ).strftime("%d %b %Y %H:%M")),
        chat_id,
    )


def cmd_sold(chat_id: str, args: str, lang: str):
    try:
        amount = float(args.strip())
    except (ValueError, AttributeError):
        send_message(i18n.t("sold.usage", lang), chat_id)
        return

    if amount <= 0:
        send_message(i18n.t("err.amount_positive", lang), chat_id)
        return

    thb_gram, _, _ = goldapi.get_gold_price()
    if thb_gram is None:
        send_message(i18n.t("err.price_fetch_retry", lang), chat_id)
        return

    entry = storage.log_sell(amount, thb_gram)
    if entry is None:
        send_message(i18n.t("sold.not_enough", lang), chat_id)
        return

    send_message(
        i18n.t("sold.ok", lang, amount=fmt(amount), price=fmt(thb_gram),
               grams=entry["grams"],
               when=datetime.now(BANGKOK_TZ).strftime("%d %b %Y %H:%M")),
        chat_id,
    )


def cmd_edit(chat_id: str, args: str, lang: str):
    parts = args.strip().split()
    if len(parts) != 2:
        send_message(i18n.t("edit.usage", lang), chat_id)
        return

    try:
        index = int(parts[0])
        new_amount = float(parts[1])
    except ValueError:
        send_message(i18n.t("edit.numbers", lang), chat_id)
        return

    if new_amount <= 0:
        send_message(i18n.t("err.amount_positive", lang), chat_id)
        return

    entry = storage.edit_entry(index, new_amount)
    if entry is None:
        send_message(i18n.t("edit.not_found", lang, index=index), chat_id)
        return

    type_label = i18n.t("entry.buy" if entry["type"] == "buy" else "entry.sell", lang)
    send_message(
        i18n.t("edit.ok", lang, index=index, type=type_label,
               amount=fmt(new_amount), price=fmt(entry["price_per_gram"]),
               grams=entry["grams"]),
        chat_id,
    )


def cmd_delete(chat_id: str, args: str, lang: str):
    try:
        index = int(args.strip())
    except (ValueError, AttributeError):
        send_message(i18n.t("delete.usage", lang), chat_id)
        return

    entry = storage.delete_entry(index)
    if entry is None:
        send_message(i18n.t("delete.not_found", lang, index=index), chat_id)
        return

    type_label = i18n.t("entry.buy" if entry["type"] == "buy" else "entry.sell", lang)
    send_message(
        i18n.t("delete.ok", lang, index=index, type=type_label,
               amount=fmt(entry["amount_thb"]), price=fmt(entry["price_per_gram"])),
        chat_id,
    )


def cmd_portfolio(chat_id: str, lang: str):
    thb_gram, _, _ = goldapi.get_gold_price()
    if thb_gram is None:
        send_message(i18n.t("err.price_fetch_short", lang), chat_id)
        return

    pnl = storage.get_portfolio_pnl(thb_gram)
    if pnl["num_buys"] == 0 and pnl["num_sells"] == 0:
        send_message(i18n.t("portfolio.empty", lang), chat_id)
        return

    profit_emoji = "🟢" if pnl["pnl_thb"] >= 0 else "🔴"
    lines = [
        i18n.t("portfolio.header", lang),
        "━━━━━━━━━━━━━━━",
        i18n.t("portfolio.counts", lang, buys=pnl["num_buys"], sells=pnl["num_sells"]),
        i18n.t("portfolio.invested", lang, value=fmt(pnl["total_invested"])),
        i18n.t("portfolio.holdings", lang, grams=pnl["total_grams"]),
        i18n.t("portfolio.avg_cost", lang, value=fmt(pnl["avg_cost"])),
        i18n.t("portfolio.current_price", lang, value=fmt(pnl["current_price"])),
        "━━━━━━━━━━━━━━━",
        i18n.t("portfolio.current_value", lang, value=fmt(pnl["current_value"])),
    ]

    if pnl["realized_pnl"] != 0:
        lines.append(i18n.t(
            "portfolio.realized", lang,
            emoji="🟢" if pnl["realized_pnl"] >= 0 else "🔴",
            value=fmt(pnl["realized_pnl"])))
    if pnl.get("unrealized_pnl") is not None and pnl["total_grams"] > 0:
        lines.append(i18n.t(
            "portfolio.unrealized", lang,
            emoji="🟢" if pnl["unrealized_pnl"] >= 0 else "🔴",
            value=fmt(pnl["unrealized_pnl"])))

    lines.append(i18n.t("portfolio.total", lang, emoji=profit_emoji,
                        value=fmt(pnl["pnl_thb"]), pct=pnl["pnl_pct"]))

    if pnl["entries"]:
        total_entries = pnl["num_buys"] + pnl["num_sells"]
        start_idx = max(1, total_entries - len(pnl["entries"]) + 1)
        lines.append(i18n.t("portfolio.recent", lang))
        for i, e in enumerate(pnl["entries"]):
            idx = start_idx + i
            ts = e["ts"][:10]
            is_buy = e.get("type", "buy") == "buy"
            icon = "🟢" if is_buy else "🔴"
            label = i18n.t("entry.buy" if is_buy else "entry.sell", lang)
            lines.append(f"  {icon} #{idx} {label} {ts}: "
                         f"{fmt(e['amount_thb'])} @ {fmt(e['price_per_gram'])}/g")

    send_message("\n".join(lines), chat_id)


def cmd_history(chat_id: str, args: str, lang: str):
    try:
        days = int(args.strip()) if args.strip() else 7
    except ValueError:
        days = 7
    # Clamp BOTH ends: `dates[-0:]` is the whole list and `dates[-(-3):]` skips
    # from the front, so 0 and negatives used to dump far more than requested.
    days = max(1, min(days, 30))

    history = storage.get_price_history()
    if len(history) < 2:
        send_message(i18n.t("err.not_enough_data", lang), chat_id)
        return

    daily = {}
    for h in history:
        date = h["ts"][:10]
        if date not in daily:
            daily[date] = {"prices": [], "usd": []}
        daily[date]["prices"].append(h["thb_gram"])
        daily[date]["usd"].append(h.get("usd_oz", 0))

    dates = sorted(daily.keys())[-days:]
    lines = [i18n.t("history.header", lang, days=len(dates)), "━━━━━━━━━━━━━━━"]

    for date in dates:
        p = daily[date]["prices"]
        high, low, close, opn = max(p), min(p), p[-1], p[0]
        change = ((close - opn) / opn) * 100
        arrow = "📈" if change > 0 else "📉" if change < 0 else "➡️"
        lines.append(
            f"{arrow} {date}: {fmt(close)} "
            f"(H:{fmt(high)} L:{fmt(low)} {change:+.2f}%)"
        )

    send_message("\n".join(lines), chat_id)


def cmd_setthreshold(chat_id: str, args: str, lang: str):
    try:
        val = float(args.strip())
    except (ValueError, AttributeError):
        send_message(i18n.t("threshold.usage_drop", lang), chat_id)
        return

    if val <= 0 or val > 10:
        send_message(i18n.t("threshold.range", lang), chat_id)
        return

    bot_state = storage.load_bot_state()
    bot_state["drop_threshold"] = val
    storage.save_bot_state(bot_state)
    # The monitor fires 5 equally spaced levels at 1x–5x this value, so quote
    # the real ladder rather than a "1.5x strong alert" tier that never fires.
    send_message(
        i18n.t("threshold.drop_ok", lang, val=val, l1=val, l2=val * 2,
               l3=val * 3, l4=val * 4, l5=val * 5),
        chat_id,
    )


def cmd_setrisethreshold(chat_id: str, args: str, lang: str):
    try:
        val = float(args.strip())
    except (ValueError, AttributeError):
        send_message(i18n.t("threshold.usage_rise", lang), chat_id)
        return

    if val <= 0 or val > 10:
        send_message(i18n.t("threshold.range", lang), chat_id)
        return

    bot_state = storage.load_bot_state()
    bot_state["rise_threshold"] = val
    storage.save_bot_state(bot_state)
    send_message(
        i18n.t("threshold.rise_ok", lang, val=val, l1=val, l2=val * 2,
               l3=val * 3, l4=val * 4, l5=val * 5),
        chat_id,
    )


# ── Price-level alerts ──────────────────────────────────────────

def cmd_alert(chat_id: str, args: str, lang: str):
    """/alert above 4500  |  /alert below 4200 — one-shot price-level alert."""
    parts = args.strip().lower().split()
    if len(parts) != 2 or parts[0] not in ("above", "below"):
        send_message(i18n.t("alert.usage", lang), chat_id)
        return
    try:
        price = float(parts[1].replace(",", ""))
    except ValueError:
        send_message(i18n.t("alert.usage", lang), chat_id)
        return
    if price <= 0:
        send_message(i18n.t("alert.price_positive", lang), chat_id)
        return

    # Sanity check against the current price so "above" alerts below market
    # (which would fire instantly) are rejected with a helpful message.
    thb_gram, _, _ = goldapi.get_gold_price()
    if thb_gram is not None:
        if parts[0] == "above" and price <= thb_gram:
            send_message(i18n.t("alert.must_be_above", lang, price=fmt(thb_gram)), chat_id)
            return
        if parts[0] == "below" and price >= thb_gram:
            send_message(i18n.t("alert.must_be_below", lang, price=fmt(thb_gram)), chat_id)
            return

    if not storage.add_level_alert(chat_id, parts[0], price):
        send_message(i18n.t("alert.limit", lang, max=storage.MAX_ALERTS_PER_USER), chat_id)
        return

    key = "alert.ok_above" if parts[0] == "above" else "alert.ok_below"
    send_message(i18n.t(key, lang, price=fmt(price)), chat_id)


def cmd_alerts(chat_id: str, lang: str):
    alerts = storage.get_user_alerts(chat_id)
    if not alerts:
        send_message(i18n.t("alerts.empty", lang), chat_id)
        return
    lines = [i18n.t("alerts.header", lang), "━━━━━━━━━━━━━━━"]
    for i, a in enumerate(alerts, 1):
        arrow = "⬆️" if a["dir"] == "above" else "⬇️"
        lines.append(f"  #{i} {arrow} {a['dir']} {fmt(a['price'])}/g")
    lines.append("━━━━━━━━━━━━━━━")
    lines.append(i18n.t("alerts.delete_hint", lang))
    send_message("\n".join(lines), chat_id)


def cmd_delalert(chat_id: str, args: str, lang: str):
    try:
        index = int(args.strip())
    except (ValueError, AttributeError):
        send_message(i18n.t("delalert.usage", lang), chat_id)
        return
    removed = storage.remove_level_alert(chat_id, index)
    if removed is None:
        send_message(i18n.t("delalert.not_found", lang, index=index), chat_id)
        return
    send_message(i18n.t("delalert.ok", lang, dir=removed["dir"],
                        price=fmt(removed["price"])), chat_id)


def cmd_subscribe(chat_id: str, lang: str):
    if TG_CHAT_ID and chat_id == TG_CHAT_ID:
        send_message(i18n.t("subscribe.owner", lang), chat_id)
        return
    added = storage.add_subscriber(chat_id)
    send_message(i18n.t("subscribe.ok" if added else "subscribe.already", lang), chat_id)


def cmd_unsubscribe(chat_id: str, lang: str):
    if TG_CHAT_ID and chat_id == TG_CHAT_ID:
        send_message(i18n.t("unsubscribe.owner", lang), chat_id)
        return
    removed = storage.remove_subscriber(chat_id)
    send_message(
        i18n.t("unsubscribe.ok" if removed else "unsubscribe.not_subscribed", lang),
        chat_id,
    )


# ── Notification preferences ────────────────────────────────────

_PREF_LABEL_KEYS = {"morning": "settings.morning", "evening": "settings.evening",
                    "alerts": "settings.alerts"}


def cmd_settings(chat_id: str, lang: str):
    prefs = storage.get_user_prefs(chat_id)
    lines = [i18n.t("settings.header", lang), "━━━━━━━━━━━━━━━"]
    for key, label_key in _PREF_LABEL_KEYS.items():
        state = i18n.t("settings.on" if prefs.get(key, True) else "settings.off", lang)
        lines.append(f"  {i18n.t(label_key, lang)}: {state}")
    quiet = prefs.get("quiet")
    lines.append(i18n.t("settings.quiet", lang,
                        value=quiet if quiet else i18n.t("settings.off", lang)))
    lines.append(i18n.t("settings.language", lang,
                        value=i18n.LANGUAGES[i18n.normalize(lang)]))
    lines += ["━━━━━━━━━━━━━━━", i18n.t("settings.hints", lang)]
    send_message("\n".join(lines), chat_id)


def _cmd_mute_unmute(chat_id: str, args: str, lang: str, value: bool):
    key = args.strip().lower()
    if key not in storage.PREF_CATEGORIES:
        send_message(
            i18n.t("mute.usage", lang, cmd="unmute" if value else "mute"), chat_id)
        return
    storage.set_user_pref(chat_id, key, value)
    send_message(
        i18n.t("mute.result", lang,
               icon="🔔" if value else "🔕",
               label=i18n.t(_PREF_LABEL_KEYS[key], lang),
               state=i18n.t("mute.on" if value else "mute.off", lang)),
        chat_id,
    )


def cmd_mute(chat_id: str, args: str, lang: str):
    _cmd_mute_unmute(chat_id, args, lang, False)


def cmd_unmute(chat_id: str, args: str, lang: str):
    _cmd_mute_unmute(chat_id, args, lang, True)


def cmd_quiet(chat_id: str, args: str, lang: str):
    spec = args.strip().lower()
    if spec in ("off", "0"):
        storage.set_user_pref(chat_id, "quiet", None)
        send_message(i18n.t("quiet.off", lang), chat_id)
        return
    if storage.parse_quiet_hours(spec) is None:
        send_message(i18n.t("quiet.usage", lang), chat_id)
        return
    storage.set_user_pref(chat_id, "quiet", spec)
    send_message(i18n.t("quiet.ok", lang, spec=spec), chat_id)


# ── Interface language ──────────────────────────────────────────

def cmd_lang(chat_id: str, args: str, lang: str):
    """/lang — show the current language; /lang en|my|th — change it.

    The confirmation is deliberately rendered in the NEW language so the user
    can see straight away whether they picked the one they wanted.
    """
    choice = args.strip().lower()
    usage = i18n.t("lang.usage", lang, current=i18n.LANGUAGES[i18n.normalize(lang)])
    if not choice:
        send_message(usage, chat_id)
        return
    if not i18n.is_supported(choice):
        # Say so explicitly — otherwise a rejected value is indistinguishable
        # from the user simply asking to see the options.
        send_message(
            i18n.t("lang.invalid", lang, choice=html_module.escape(choice))
            + "\n" + usage,
            chat_id,
        )
        return

    new_lang = i18n.normalize(choice)
    storage.set_user_pref(chat_id, "lang", new_lang)
    send_message(i18n.t("lang.ok", new_lang, lang=i18n.LANGUAGES[new_lang]), chat_id)


# Inline keyboard shown with /help and /start — tap instead of typing.
def main_keyboard(lang: str | None = None) -> dict:
    """Localised inline keyboard. callback_data stays the raw command."""
    return {
        "inline_keyboard": [
            [{"text": i18n.t("btn.price", lang), "callback_data": "/price"},
             {"text": i18n.t("btn.predict", lang), "callback_data": "/predict"}],
            [{"text": i18n.t("btn.chart", lang), "callback_data": "/chart"},
             {"text": i18n.t("btn.macro", lang), "callback_data": "/macro"}],
            [{"text": i18n.t("btn.subscribe", lang), "callback_data": "/subscribe"},
             {"text": i18n.t("btn.settings", lang), "callback_data": "/settings"}],
        ]
    }


def cmd_help(chat_id: str, lang: str):
    send_message(i18n.t("help.text", lang), chat_id, reply_markup=main_keyboard(lang))


# ── Dispatch ────────────────────────────────────────────────────

# Public commands — anyone can use
PUBLIC_COMMANDS = {
    "/price": lambda cid, _, lang: cmd_price(cid, lang),
    "/predict": lambda cid, _, lang: cmd_predict(cid, lang),
    "/macro": lambda cid, _, lang: cmd_macro(cid, lang),
    "/events": lambda cid, _, lang: cmd_events(cid, lang),
    "/news": lambda cid, _, lang: cmd_news(cid, lang),
    "/chart": cmd_chart,
    "/history": cmd_history,
    "/alert": cmd_alert,
    "/alerts": lambda cid, _, lang: cmd_alerts(cid, lang),
    "/delalert": cmd_delalert,
    "/settings": lambda cid, _, lang: cmd_settings(cid, lang),
    "/mute": cmd_mute,
    "/unmute": cmd_unmute,
    "/quiet": cmd_quiet,
    "/lang": cmd_lang,
    "/language": cmd_lang,
    "/subscribe": lambda cid, _, lang: cmd_subscribe(cid, lang),
    "/unsubscribe": lambda cid, _, lang: cmd_unsubscribe(cid, lang),
    "/help": lambda cid, _, lang: cmd_help(cid, lang),
    "/start": lambda cid, _, lang: cmd_help(cid, lang),
}

# Owner-only commands — require matching TELEGRAM_CHAT_ID
OWNER_COMMANDS = {
    "/bought": cmd_bought,
    "/sold": cmd_sold,
    "/edit": cmd_edit,
    "/delete": cmd_delete,
    "/portfolio": lambda cid, _, lang: cmd_portfolio(cid, lang),
    "/setthreshold": cmd_setthreshold,
    "/setrisethreshold": cmd_setrisethreshold,
}

COMMANDS = {**PUBLIC_COMMANDS, **OWNER_COMMANDS}


def _parse_command(text: str) -> tuple:
    """Parse '/cmd@bot args' -> (cmd, args), with prefix-glue recovery.

    Recovers the bracketed template form users paste from /help — '/bought<5000>'
    becomes ('/bought', '5000'). Digits glued directly to the word ('/bought5000')
    cannot be split unambiguously and are left alone, so they surface as an
    unknown command rather than a silently misread amount.
    """
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().split("@")[0]
    args = parts[1] if len(parts) > 1 else ""

    if cmd not in COMMANDS:
        m = re.match(r"^(/\w+)", cmd)
        if m:
            base_cmd = m.group(1)
            if base_cmd in COMMANDS:
                extra = re.sub(r"[<>]", "", cmd[len(base_cmd):]).strip()
                if extra and not args:
                    args = extra
                cmd = base_cmd
    return cmd, args


def dispatch_update(update: dict) -> bool:
    """Process a single Telegram update. Returns True if a command was handled.

    Shared by both the poller and the webhook so command behaviour and access
    control can never drift between the two entrypoints again.
    """
    # Inline keyboard button press — ack the spinner, then re-dispatch the
    # button's callback_data exactly as if the user had typed the command.
    cq = update.get("callback_query")
    if cq:
        if cq.get("id"):
            answer_callback_query(str(cq["id"]))
        data = (cq.get("data") or "").strip()
        chat_id = str(cq.get("message", {}).get("chat", {}).get("id", ""))
        if not data or not chat_id or not data.startswith("/"):
            return False
        return dispatch_update({"message": {"text": data, "chat": {"id": chat_id}}})

    msg = update.get("message", {})
    text = (msg.get("text") or "").strip()
    chat_id = str(msg.get("chat", {}).get("id", ""))

    if not text or not chat_id or not text.startswith("/"):
        return False

    cmd, args = _parse_command(text)
    # Fail closed: if TELEGRAM_CHAT_ID is not configured, NOBODY is owner.
    # (Previously everyone was owner in that case — an unsafe default for a
    # public bot where a missing env var would expose portfolio commands.)
    is_owner = bool(TG_CHAT_ID) and (chat_id == TG_CHAT_ID)

    # Resolved once and threaded into the handler, so rendering a message with
    # dozens of strings costs no extra Gist round-trips.
    lang = storage.get_user_lang(chat_id)

    handler = COMMANDS.get(cmd)
    if not handler:
        safe_cmd = html_module.escape(cmd)
        send_message(i18n.t("err.unknown_command", lang, cmd=safe_cmd), chat_id)
        return False

    if cmd in OWNER_COMMANDS and not is_owner:
        print(f"[bot] Owner-only command '{cmd}' from unauthorized chat: {chat_id}")
        send_message(i18n.t("err.owner_only", lang), chat_id)
        return False

    print(f"[bot] Command: {cmd} args='{args}' chat={chat_id} lang={lang}")
    try:
        handler(chat_id, args, lang)
    except Exception as e:
        print(f"[bot] Command error: {e}")
        send_message(i18n.t("err.generic", lang, error=html_module.escape(str(e))), chat_id)
    return True
