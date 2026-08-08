"""
YLG ရွှေဈေး Monitor v2 — Enhanced Edition
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Features:
  • Multi-timeframe buy signals (intraday + weekly + monthly)
  • Technical analysis (RSI, SMA, MACD, Bollinger)
  • ML price prediction (4h / 12h / 24h)
  • Portfolio tracking with P&L
  • Rich evening summary with trends
  • GitHub Gist persistent storage
  • Retry logic + multi-source price fallback (see goldapi.py)

GitHub Actions: runs on a cron through the day.
Shared logic (price fetch, formatting, Telegram send) lives in goldapi.py,
gold_format.py and bot_core.py so it is not duplicated here.
"""

import os
import time
import traceback
from datetime import datetime
import pytz

import events
import i18n
import storage
import predictor
import regime
import goldapi
import bot_core
import signals
from gold_format import fmt, gold_breakdown

# ── Config ──────────────────────────────────────────────────────
BANGKOK_TZ = pytz.timezone("Asia/Bangkok")
TG_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DROP_THRESHOLD = float(os.environ.get("DROP_THRESHOLD", "0.5"))
RISE_THRESHOLD = float(os.environ.get("RISE_THRESHOLD", "0.5"))
# Overnight / day-boundary gap: bigger than the intraday threshold to avoid
# noise from the normal open-to-open drift.
GAP_THRESHOLD = float(os.environ.get("GAP_THRESHOLD", "1.0"))

# Try to load thresholds from bot state (user-configurable via /setthreshold, /setrisethreshold)
try:
    _bot_state = storage.load_bot_state()
    if "drop_threshold" in _bot_state:
        DROP_THRESHOLD = _bot_state["drop_threshold"]
    if "rise_threshold" in _bot_state:
        RISE_THRESHOLD = _bot_state["rise_threshold"]
    if "gap_threshold" in _bot_state:
        GAP_THRESHOLD = _bot_state["gap_threshold"]
except Exception:
    pass


# ── Telegram Notify ─────────────────────────────────────────────

def notify(msg, category: str = "alerts"):
    """Send message to owner + all subscribers, honoring per-user preferences.

    `msg` is either a plain string (same text for everyone) or a callable
    `lang -> str`, which is how every localised broadcast is passed. The
    callable is invoked at most ONCE PER LANGUAGE actually present among the
    recipients, not once per recipient, so a 500-subscriber broadcast still
    only builds three message bodies.

    `category` is one of "morning" / "evening" / "alerts" — users can mute
    categories (/mute) or set quiet hours (/quiet); both are checked here.
    Uses the shared bot_core.send_message; auto-removes subscribers who have
    blocked the bot (Telegram error_code 403).
    """
    if not TG_BOT_TOKEN:
        print("[WARN] Telegram bot token not set")
        print(msg(i18n.DEFAULT_LANG) if callable(msg) else msg)
        return

    # Subscribers and prefs live in the same Gist file — one read for both.
    subscribers, all_prefs = storage.get_subscribers_and_prefs()

    recipients = []
    if TG_CHAT_ID:
        recipients.append(TG_CHAT_ID)
    for sub_id in subscribers:
        if sub_id != TG_CHAT_ID:  # avoid duplicate if owner subscribed
            recipients.append(sub_id)

    hour = datetime.now(BANGKOK_TZ).hour
    allowed = [c for c in recipients
               if storage.prefs_allow(all_prefs.get(str(c), {}), category, hour)]
    if len(allowed) < len(recipients):
        print(f"[notify] {len(recipients) - len(allowed)} recipient(s) "
              f"skipped by prefs ({category})")
    recipients = allowed

    rendered = {}

    def body_for(chat_id) -> str:
        if not callable(msg):
            return msg
        lang = i18n.normalize(all_prefs.get(str(chat_id), {}).get("lang"))
        if lang not in rendered:
            rendered[lang] = msg(lang)
        return rendered[lang]

    for i, chat_id in enumerate(recipients):
        # Telegram broadcast limit is ~30 msg/s — pace sends to stay well under.
        if i:
            time.sleep(0.1)
        resp = bot_core.send_message(body_for(chat_id), chat_id)
        if resp and not resp.get("ok") and resp.get("error_code") == 403:
            print(f"[Telegram] Removing blocked subscriber: {chat_id}")
            storage.remove_subscriber(chat_id)


# ── Helpers ─────────────────────────────────────────────────────

def drop_pct(open_p, cur):
    return ((open_p - cur) / open_p) * 100


def rise_pct(open_p, cur):
    return ((cur - open_p) / open_p) * 100


def build_weekly_block(history: list, lang: str | None = None) -> str:
    """Weekly recap appended to the SUNDAY evening summary.

    Computed from the hourly price history: week change, range, and the
    best/worst day by daily close-over-open move. Returns "" if there is not
    enough data (needs ≥ 2 distinct days in the last 7d window).
    """
    points = history[-168:]  # last 7 days of hourly points
    if len(points) < 24:
        return ""

    daily = {}
    for h in points:
        if "thb_gram" not in h or "ts" not in h:
            continue
        daily.setdefault(h["ts"][:10], []).append(h["thb_gram"])
    if len(daily) < 2:
        return ""

    prices = [p for day in daily.values() for p in day]
    week_open, week_close = prices[0], prices[-1]
    week_change = ((week_close - week_open) / week_open) * 100 if week_open else 0

    day_moves = {}
    for date, day_prices in daily.items():
        if day_prices[0]:
            day_moves[date] = ((day_prices[-1] - day_prices[0]) / day_prices[0]) * 100
    best = max(day_moves, key=day_moves.get)
    worst = min(day_moves, key=day_moves.get)

    return i18n.t(
        "monitor.weekly", lang,
        arrow="📈" if week_change >= 0 else "📉",
        change=week_change, open=fmt(week_open), close=fmt(week_close),
        high=fmt(max(prices)), low=fmt(min(prices)),
        best_day=best[5:], best=day_moves[best],
        worst_day=worst[5:], worst=day_moves[worst],
    )


# ── Main Monitor ────────────────────────────────────────────────

def main():
    now = datetime.now(BANGKOK_TZ)
    hour = now.hour
    time_str = now.strftime("%d %b %Y %H:%M")

    print(f"[{time_str}] Gold Monitor v2 checking...")

    # Scheduled high-impact release nearby? Resolved once per run and reused by
    # every message below. Purely about TIMING — it says something is happening,
    # never which way the price will go.
    event, event_phase = events.active_window(now)
    if event:
        print(f"  Event window: {event.type} ({event_phase})")

    # Daily messages look further ahead than the alert banner: an alert is about
    # right now, whereas the morning/evening summary is the moment to say "CPI
    # lands tomorrow".
    next_events = events.upcoming(now, within_hours=events.LOOKAHEAD_HOURS, limit=2)

    def day_event_note(lang):
        if not next_events:
            return ""
        lines = [i18n.t("events.header", lang)]
        lines += [bot_core.format_event_line(e, now, lang) for e in next_events]
        return "\n━━━━━━━━━━━━━━━\n" + "\n".join(lines)

    def event_banner(lang):
        """Warning appended to alerts while a release is imminent or fresh."""
        if not event:
            return ""
        name = i18n.t(event.label_key, lang)
        if event_phase == "pre":
            return i18n.t("events.banner_pre", lang, name=name,
                          countdown=bot_core.format_countdown(
                              event.hours_until(now), lang))
        return i18n.t("events.banner_post", lang, name=name)

    # ── Fetch Price ─────────────────────────────────────────────
    thb_gram, usd_oz, thb_rate = goldapi.get_gold_price()
    if thb_gram is None:
        notify(lambda lang: i18n.t("monitor.api_error", lang))
        return

    print(f"  Gold: {fmt(thb_gram)}/g (${usd_oz}/oz) [THB rate: {thb_rate}]")

    # ── Store Price History ─────────────────────────────────────
    history = storage.append_price(thb_gram, usd_oz, thb_rate)
    print(f"  History: {len(history)} data points stored")

    # ── Day State ───────────────────────────────────────────────
    state = storage.load_day_state()
    # Set by the evening block; flushed with the day state in one Gist PATCH.
    pending_model_data = None

    # First run of the day — anchor the day's open/high/low.
    #
    # With the 24/7 */5 cron this lands at ~00:00 BKK, so "open" means the
    # day-BOUNDARY price, not the morning price: every drop/rise alert and the
    # evening "ယနေ့ change" are measured from midnight. That is deliberate —
    # it leaves no blind window between midnight and the morning message, and
    # the move across the boundary itself is covered by the gap-down alert
    # below (vs yesterday's close). Persisted with the rest of the state at the
    # end of the run; if this run dies first, the next one simply re-anchors a
    # few minutes later.
    if state["open_price"] is None:
        state.update({
            "open_price": thb_gram,
            "day_low": thb_gram,
            "day_high": thb_gram,
        })

    # ── Morning Message ─────────────────────────────────────────
    # Send once per day during the morning window (6am–2pm BKK), gated by its
    # own `morning_sent` flag — NOT by the "first run of the day" check above.
    #
    # Why: the cron's last UTC hours fall after midnight BKK (e.g. 17:00 UTC =
    # 00:00 BKK the next day). Those overnight runs used to consume the
    # first-run slot — setting open_price at hour 0, outside the 6–14 window so
    # no message — and the real 7am run then saw open_price already set and
    # skipped the morning message entirely. Decoupling the two flags is what
    # fixes that; open_price still anchors at the day boundary (see above).
    if 6 <= hour <= 14 and not state.get("morning_sent"):
        # Trend / TA fragments are language-independent numbers; only their
        # labels differ, so compute the values once and format per language.
        trend_parts = []
        if len(history) >= 24:
            trend_now = predictor.get_trend_summary(history)
            if "change_24h" in trend_now:
                trend_parts.append(f"24h: {trend_now['change_24h']:+.3f}%")
            if "change_7d" in trend_now:
                trend_parts.append(f"7d: {trend_now['change_7d']:+.3f}%")

        morning_signal = ""
        if len(history) >= 14:
            ta_now = predictor.analyze(history)
            morning_signal = ta_now.get("overall_signal") or ""

        # Fetch macro ONCE, then render it in each recipient language.
        macro_data = signals.fetch_macro()
        gb = gold_breakdown(thb_gram)

        def build_morning(lang):
            extras = ""
            if trend_parts:
                extras += i18n.t("monitor.trend", lang, parts=" | ".join(trend_parts))
            if morning_signal:
                extras += i18n.t("monitor.ta_signal", lang, signal=morning_signal)
            block = signals.format_macro_block(macro_data, lang)
            if block:
                extras += f"\n━━━━━━━━━━━━━━━\n{block}"
            extras += day_event_note(lang)
            return i18n.t(
                "monitor.morning", lang, when=time_str,
                baht_9999=fmt(gb["baht_9999"]), gram_9999=fmt(gb["gram_9999"]),
                baht_9650=fmt(gb["baht_9650"]), gram_9650=fmt(gb["gram_9650"]),
                usd_oz=usd_oz, thb_rate=thb_rate,
                drop=DROP_THRESHOLD, rise=RISE_THRESHOLD, extras=extras,
            )

        notify(build_morning, "morning")
        state["morning_sent"] = True
        storage.save_day_state(state)

    # ── Update Day Stats ────────────────────────────────────────
    # .get(...) or thb_gram: tolerate older day_state schemas missing keys.
    state["day_low"] = min(state.get("day_low") or thb_gram, thb_gram)
    state["day_high"] = max(state.get("day_high") or thb_gram, thb_gram)
    d = drop_pct(state["open_price"], thb_gram)
    print(f"  Drop from open: {d:+.2f}%")

    # ── Per-user Price-level Alerts (one-shot, set via /alert) ──
    for chat_id, alert in storage.pop_triggered_alerts(thb_gram):
        # Level alerts go to one user each, in that user's own language.
        bot_core.send_message(
            i18n.t("monitor.level_alert", storage.get_user_lang(chat_id),
                   when=time_str,
                   arrow="⬆️" if alert["dir"] == "above" else "⬇️",
                   dir=alert["dir"], target=fmt(alert["price"]),
                   price=fmt(thb_gram)),
            chat_id,
        )
        print(f"  Level alert fired: {chat_id} {alert['dir']} {alert['price']}")

    # ── Multi-timeframe Analysis ────────────────────────────────
    ta = predictor.analyze(history) if len(history) >= 14 else {}
    trend = predictor.get_trend_summary(history) if len(history) >= 2 else {}

    # Regime: is this move unusually large, and is it moving against gold's
    # usual drivers? Both describe what already happened — neither forecasts.
    # Macro is fetched lazily: only worth a round-trip once volatility says
    # something is actually going on.
    vol = regime.vol_regime(history)
    divergence_key = None
    if regime.is_unusual(vol):
        try:
            divergence_key = regime.divergence(trend.get("change_24h"),
                                               signals.fetch_macro())
        except Exception as e:  # macro is optional context, never fatal
            print(f"[regime] macro fetch failed: {e}")
    if vol.get("available"):
        print(f"  Regime: {vol['level']} (vol {vol['ratio']}x, "
              f"last move {vol['sigma']}σ)")

    def regime_block(lang):
        return regime.format_block(vol, divergence_key, lang)

    # ── Drop Alerts (5 levels, equal spacing) ─────────────────────
    # Titles and advice are i18n keys, resolved per recipient language.
    DROP_LEVELS = [
        {"mult": 1, "key": "notified_drop_1", "emoji": "🟡", "str": "drop.1"},
        {"mult": 2, "key": "notified_drop_2", "emoji": "🟠", "str": "drop.2"},
        {"mult": 3, "key": "notified_drop_3", "emoji": "🔴", "str": "drop.3"},
        {"mult": 4, "key": "notified_drop_4", "emoji": "🔴🔴", "str": "drop.4"},
        {"mult": 5, "key": "notified_drop_5", "emoji": "🚨", "str": "drop.5"},
    ]

    def ta_block(lang):
        """TA suffix shared by the drop / rise / gap alerts.

        Inside an event window the indicators are still shown — hiding them
        loses information — but they carry an explicit caution, because RSI
        "oversold" 20 minutes before CPI is close to meaningless.
        """
        out = ""
        if ta.get("overall_signal"):
            out += i18n.t("monitor.ta_signal", lang, signal=ta["overall_signal"])
        if ta.get("rsi"):
            out += "\n" + i18n.t("price.rsi", lang, value=ta["rsi"])
        out += event_banner(lang)
        if out and event:
            out += i18n.t("events.ta_caution", lang)
        out += regime_block(lang)
        return out

    for level in DROP_LEVELS:
        threshold = DROP_THRESHOLD * level["mult"]
        if d >= threshold and not state.get(level["key"]):
            notify(lambda lang, lv=level: i18n.t(
                "monitor.drop", lang, emoji=lv["emoji"],
                title=i18n.t(f"{lv['str']}.title", lang), when=time_str,
                price=fmt(thb_gram), usd_oz=usd_oz,
                open=fmt(state["open_price"]), pct=d, level=lv["mult"],
                low=fmt(state["day_low"]), ta=ta_block(lang),
                advice=i18n.t(f"{lv['str']}.advice", lang),
            ))
            state[level["key"]] = True

    # Reset drop notifications if price recovers
    if d < DROP_THRESHOLD * 0.3:
        for level in DROP_LEVELS:
            state[level["key"]] = False

    # ── Overnight / Gap-Down Alert (vs yesterday's close) ─────────
    # The open-based alerts above only see moves from TODAY's open, so a decline
    # that happens overnight or across the midnight boundary is invisible (the
    # open is re-anchored each morning, often after the move). We carry
    # yesterday's last price as `prev_close` and fire a one-shot alert if today
    # gapped down beyond GAP_THRESHOLD.
    prev_close = state.get("prev_close")
    if prev_close and not state.get("notified_gap"):
        gap = drop_pct(prev_close, thb_gram)  # > 0 means down vs yesterday
        if gap >= GAP_THRESHOLD:
            notify(lambda lang: i18n.t(
                "monitor.gap", lang, when=time_str, price=fmt(thb_gram),
                usd_oz=usd_oz, prev_close=fmt(prev_close), pct=gap,
                low=fmt(state["day_low"]), ta=ta_block(lang),
            ))
            state["notified_gap"] = True

    # ── Rise Alerts (5 levels, equal spacing) ──────────────────
    RISE_LEVELS = [
        {"mult": 1, "key": "notified_rise_1", "emoji": "🟢", "str": "rise.1"},
        {"mult": 2, "key": "notified_rise_2", "emoji": "🟢🟢", "str": "rise.2"},
        {"mult": 3, "key": "notified_rise_3", "emoji": "🟣", "str": "rise.3"},
        {"mult": 4, "key": "notified_rise_4", "emoji": "🟣🟣", "str": "rise.4"},
        {"mult": 5, "key": "notified_rise_5", "emoji": "🚀", "str": "rise.5"},
    ]

    r = rise_pct(state["open_price"], thb_gram)
    for level in RISE_LEVELS:
        threshold = RISE_THRESHOLD * level["mult"]
        if r >= threshold and not state.get(level["key"]):
            notify(lambda lang, lv=level: i18n.t(
                "monitor.rise", lang, emoji=lv["emoji"],
                title=i18n.t(f"{lv['str']}.title", lang), when=time_str,
                price=fmt(thb_gram), usd_oz=usd_oz,
                open=fmt(state["open_price"]), pct=r, level=lv["mult"],
                high=fmt(state["day_high"]), ta=ta_block(lang),
                advice=i18n.t(f"{lv['str']}.advice", lang),
            ))
            state[level["key"]] = True

    # Reset rise notifications if price drops back
    if r < RISE_THRESHOLD * 0.3:
        for level in RISE_LEVELS:
            state[level["key"]] = False

    # ── Evening Summary (8pm BKK; window to 11:55pm absorbs Actions delays) ──
    if 20 <= hour <= 23 and not state.get("evening_sent"):
        change = -d
        arrow = "📈" if change > 0 else "📉"

        pnl = storage.get_portfolio_pnl(thb_gram)

        evening_trend_parts = []
        if trend:
            for key, label in [("change_4h", "4h"), ("change_24h", "24h"),
                               ("change_7d", "7d")]:
                if key in trend:
                    evening_trend_parts.append(f"{label}: {trend[key]:+.3f}%")

        # Prediction outlook + accuracy tracking (record tonight's prediction,
        # score matured ones so the bot reports its real hit-rate over time)
        if len(history) >= 15:
            model_data = storage.load_model_data()
            changed = predictor.resolve_predictions(model_data, history)
            pred = predictor.predict(history, model_data)
            if pred.get("predictions"):
                predictor.record_predictions(model_data, pred, thb_gram)
                changed = True
            if changed:
                # Flushed together with the day state at the end of the run.
                pending_model_data = model_data
            evening_outlook = pred.get("combined_outlook") or pred.get("ta_outlook", "")
            rates = predictor.prediction_hit_rates(model_data)
            scored = {h: sc for h, sc in rates.items() if sc.get("n")}
            hit_parts = [f"{h} {sc['hit_pct']}%" for h, sc in sorted(scored.items())]
        else:
            evening_outlook, hit_parts = "", []

        # Fetch macro ONCE, then render it in each recipient language.
        macro_data = signals.fetch_macro()

        def build_evening(lang):
            extras = ""
            if evening_trend_parts:
                extras += i18n.t("monitor.trends", lang,
                                 parts=" | ".join(evening_trend_parts))
            if trend.get("streak", 0) >= 3:
                key = ("monitor.streak_up" if trend["streak_direction"] == "up"
                       else "monitor.streak_down")
                extras += i18n.t(key, lang, hours=trend["streak"])
            if pnl["num_buys"] > 0:
                extras += i18n.t(
                    "monitor.portfolio", lang, grams=pnl["total_grams"],
                    buys=pnl["num_buys"],
                    emoji="🟢" if pnl["pnl_thb"] >= 0 else "🔴",
                    pnl=fmt(pnl["pnl_thb"]), pct=pnl["pnl_pct"])
            if evening_outlook:
                extras += i18n.t("monitor.outlook", lang, outlook=evening_outlook)
            if hit_parts:
                extras += i18n.t("monitor.hit_rate", lang, parts=" | ".join(hit_parts))
            # Weekly recap — Sundays only
            if now.weekday() == 6:
                extras += build_weekly_block(history, lang)
            block = signals.format_macro_block(macro_data, lang)
            if block:
                extras += f"\n━━━━━━━━━━━━━━━\n{block}"
            extras += day_event_note(lang)
            extras += regime_block(lang)
            return i18n.t(
                "monitor.evening", lang, when=time_str, price=fmt(thb_gram),
                open=fmt(state["open_price"]), arrow=arrow, change=change,
                high=fmt(state["day_high"]), low=fmt(state["day_low"]),
                usd_oz=usd_oz, extras=extras,
            )

        notify(build_evening, "evening")
        state["evening_sent"] = True

    # Remember the latest price so tomorrow can detect an overnight gap.
    state["last_price"] = thb_gram
    if pending_model_data is not None:
        storage.save_day_state_and_model(state, pending_model_data)
    else:
        storage.save_day_state(state)

    # ── Train ML Model (once per day, after enough data) ────────
    if hour == 3 and len(history) >= 100:
        model_data = storage.load_model_data()
        last_trained = model_data.get("last_trained", "")
        today = now.strftime("%Y-%m-%d")
        if not last_trained or last_trained[:10] != today:
            print("[ML] Training prediction models...")
            new_model = predictor.train_model(history)
            if new_model:
                # MERGE, never replace: train_model returns only the model
                # payload, so assigning it wholesale would drop the
                # "predictions" accuracy log that the live hit-rate is built
                # from — erasing weeks of scored forecasts on every retrain.
                model_data.update(new_model)
                storage.save_model_data(model_data)
                print("[ML] Models saved to Gist")
            else:
                print("[ML] Training skipped or failed")

    print("  Done.")


def run():
    """Entry point with failure alerting.

    If the monitor itself crashes (Gist outage, schema surprise, bug), tell the
    owner instead of failing silently — otherwise alerts just stop and nobody
    notices until it's too late.
    """
    try:
        main()
    except Exception as e:
        print(f"[monitor] CRASH: {e}")
        traceback.print_exc()
        if TG_BOT_TOKEN and TG_CHAT_ID:
            err = str(e)[:300]
            try:
                owner_lang = storage.get_user_lang(TG_CHAT_ID)
            except Exception:
                owner_lang = i18n.DEFAULT_LANG  # storage itself may be the fault
            bot_core.send_message(
                i18n.t("monitor.crash", owner_lang,
                       error=f"{type(e).__name__}: {err}"),
                TG_CHAT_ID,
            )
        raise  # keep the Actions run red


if __name__ == "__main__":
    run()
