"""
PPA ရွှေဈေး Monitor v2 — Enhanced Edition
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
import gta
import i18n
import news
import storage
import predictor
import regime
import goldapi
import bot_core
import signals
from gold_format import fmt, fmt_target, fmt_usd, change_arrow, gold_breakdown

# ── Config ──────────────────────────────────────────────────────
BANGKOK_TZ = pytz.timezone("Asia/Bangkok")
TG_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DROP_THRESHOLD = float(os.environ.get("DROP_THRESHOLD", "0.5"))
RISE_THRESHOLD = float(os.environ.get("RISE_THRESHOLD", "0.5"))
# Overnight / day-boundary gap: bigger than the intraday threshold to avoid
# noise from the normal open-to-open drift.
GAP_THRESHOLD = float(os.environ.get("GAP_THRESHOLD", "1.0"))

# Thresholds are user-configurable via /setthreshold and /setrisethreshold.
#
# Bound BEFORE the try: main() passes _bot_state to the webhook watchdog at the
# very end of a run, so a failure here used to raise NameError there instead —
# disabling the one check that notices a webhook silently swallowing every
# command, and disabling it precisely when storage was already misbehaving.
_bot_state: dict = {}
try:
    _bot_state = storage.load_bot_state()
    if "drop_threshold" in _bot_state:
        DROP_THRESHOLD = _bot_state["drop_threshold"]
    if "rise_threshold" in _bot_state:
        RISE_THRESHOLD = _bot_state["rise_threshold"]
    if "gap_threshold" in _bot_state:
        GAP_THRESHOLD = _bot_state["gap_threshold"]
except Exception as e:
    # Falling back to the defaults silently means the owner's /setthreshold is
    # ignored and the alert levels move, with nothing to say why.
    print(f"[monitor] could not load thresholds, using defaults "
          f"(drop {DROP_THRESHOLD}%, rise {RISE_THRESHOLD}%): {e}")


# ── Telegram Notify ─────────────────────────────────────────────

def notify(msg, category: str = "alerts", owner_msg=None):
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

    `owner_msg`, when given, is what the OWNER receives instead of `msg` —
    for content that is theirs alone. Anyone can /subscribe, so everything in
    `msg` should be treated as public.
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
        is_owner = bool(TG_CHAT_ID) and str(chat_id) == str(TG_CHAT_ID)
        source = owner_msg if (is_owner and owner_msg is not None) else msg
        if not callable(source):
            return source
        lang = i18n.normalize(all_prefs.get(str(chat_id), {}).get("lang"))
        # Cached per (audience, language): the owner's body must never be
        # handed to a subscriber who happens to share their language.
        key = ("owner" if source is owner_msg else "all", lang)
        if key not in rendered:
            rendered[key] = source(lang)
        return rendered[key]

    for i, chat_id in enumerate(recipients):
        # Telegram broadcast limit is ~30 msg/s — pace sends to stay well under.
        if i:
            time.sleep(0.1)
        resp = bot_core.send_message(body_for(chat_id), chat_id)
        if resp and not resp.get("ok") and resp.get("error_code") == 403:
            # Blocked the bot — unlike /unsubscribe, this one is not coming
            # back, so their prefs go too.
            print(f"[Telegram] Removing blocked subscriber: {chat_id}")
            storage.remove_subscriber(chat_id, drop_prefs=True)


# ── Helpers ─────────────────────────────────────────────────────

def drop_pct(open_p, cur):
    return ((open_p - cur) / open_p) * 100


def rise_pct(open_p, cur):
    return ((cur - open_p) / open_p) * 100


def build_weekly_block(history: list, lang: str | None = None) -> str:
    """Weekly recap appended to the SUNDAY evening summary.

    Quoted in USD/oz, not THB/gram: over a week the baht moves enough that a
    THB recap blends two stories, and the daily rows in the summary above
    already carry the THB side.

    Computed from the hourly price history: week change, range, and the
    best/worst day by daily close-over-open move. Returns "" if there is not
    enough data (needs ≥ 2 distinct days of spot in the last 7d window —
    entries from before usd_oz was recorded are skipped).
    """
    points = history[-168:]  # last 7 days of hourly points
    if len(points) < 24:
        return ""

    daily = {}
    for h in points:
        if not h.get("usd_oz") or "ts" not in h:
            continue
        daily.setdefault(h["ts"][:10], []).append(h["usd_oz"])
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
        arrow=change_arrow(week_change),
        change=week_change, open=fmt_usd(week_open), close=fmt_usd(week_close),
        high=fmt_usd(max(prices)), low=fmt_usd(min(prices)),
        best_day=best[5:], best=day_moves[best],
        worst_day=worst[5:], worst=day_moves[worst],
    )


# ── Is the schedule keeping up? ─────────────────────────────────
#
# The workflow asks GitHub for a run every 5 minutes, but GitHub treats
# scheduled runs as best effort. Over 34 days in Sep–Oct 2026 it delivered 4–8
# a day — a median of 4 hours apart, up to 9. Every one succeeded, so nothing
# looked wrong, yet price alerts landed hours late, the evening summary was
# skipped on 6 of 33 days and the 3am retrain ran on 9. A run is the only
# thing in a position to notice, by looking at when the previous one finished.
#
# The previous COMPLETED run, so a stretch of price-API failures counts too:
# those runs check nothing either.

RUN_GAP_WARN_MIN = 90          # this long after the previous run is late
RUN_GAP_WARN_INTERVAL_H = 12   # tell the owner at most twice a day


def warn_owner_if_runs_lag(state: dict, now: datetime) -> None:
    """Tell the owner when this run came long after the previous one.

    Reads `last_run_at` from the day state and stamps `run_gap_warned_at` in
    it; the caller saves the state, as it does at the end of every run. Never
    raises: a check on the schedule must not break the run it is checking.
    """
    try:
        last = state.get("last_run_at")
        if not (last and TG_CHAT_ID):
            return
        gap_min = (now - datetime.fromisoformat(last)).total_seconds() / 60
        if gap_min < RUN_GAP_WARN_MIN:
            return
        warned = state.get("run_gap_warned_at")
        if warned:
            try:
                age_h = (now - datetime.fromisoformat(warned)).total_seconds() / 3600
                if 0 <= age_h < RUN_GAP_WARN_INTERVAL_H:
                    return
            except (ValueError, TypeError):
                pass  # unparseable stamp: treat as never warned, not as muted
        lang = storage.get_user_lang(TG_CHAT_ID)
        bot_core.send_message(
            i18n.t("monitor.run_gap", lang,
                   gap=bot_core.format_countdown(gap_min / 60, lang)),
            TG_CHAT_ID)
        state["run_gap_warned_at"] = now.isoformat()
        print(f"  [WARN] {gap_min:.0f} min since the previous completed run")
    except Exception as e:
        print(f"[monitor] run-gap check failed: {e}")


# ── A frozen price source: switch, don't just warn ──────────────
#
# warn_owner_if_feed_stuck tells the owner when spot has sat still through
# trading hours, but the bot kept using the frozen quote — alerts and the TA
# reading stayed frozen until someone fixed the source. A second source is
# already configured for outages; it now also stands in for a source that
# answers with a stale price. The frozen source and price are remembered in
# _bot_state: once the stand-in's prices are stored, the frozen quote no
# longer matches the history, and without the memory the bot would switch
# back to it on the next run.

def failover_if_frozen(thb_gram: float, usd_oz: float, thb_rate: float,
                       now: datetime) -> tuple:
    """(thb_gram, usd_oz, state_changed), from another source if this one is frozen."""
    source = goldapi.last_spot_source
    frozen = _bot_state.get("spot_frozen") or {}
    known = frozen.get("source") == source and frozen.get("price") == usd_oz
    changed = False
    if not known:
        if frozen:
            # The stuck source moved again: back to normal.
            _bot_state.pop("spot_frozen", None)
            changed = True
        try:
            hours = goldapi.hours_frozen(storage.get_price_history(), usd_oz, now)
        except Exception as e:
            print(f"[monitor] freeze check failed: {e}")
            return thb_gram, usd_oz, changed
        if hours < goldapi.STUCK_AFTER_OPEN_HOURS:
            return thb_gram, usd_oz, changed
    alt = goldapi.fetch_spot_usd(exclude=(source,))
    if alt is None or round(alt, 2) == usd_oz:
        # Nothing better to switch to; the feed watchdog will tell the owner.
        return thb_gram, usd_oz, changed
    alt = round(alt, 2)
    if not known:
        _bot_state["spot_frozen"] = {"source": source, "price": usd_oz,
                                     "since": now.isoformat()}
        changed = True
        if TG_CHAT_ID:
            bot_core.send_message(i18n.t(
                "monitor.feed_failover", storage.get_user_lang(TG_CHAT_ID),
                frozen=source, price=fmt_usd(usd_oz),
                backup=goldapi.last_spot_source, alt=fmt_usd(alt)), TG_CHAT_ID)
    print(f"  Spot source {source!r} frozen at {usd_oz}: "
          f"using {goldapi.last_spot_source!r} = {alt}")
    return goldapi.thb_per_gram(alt, thb_rate), alt, changed


# ── Weekly backup to the owner ──────────────────────────────────
# storage.backup_snapshot, sent as a file once a week in the BKK evening.
# Half a day of slack keeps it on the same evening each week instead of
# drifting later by a run or two every time.

BACKUP_EVERY_DAYS = 7
BACKUP_HOURS = range(21, 24)


def send_weekly_backup(now: datetime) -> bool:
    """True when a backup went out and _bot_state should be saved."""
    if not TG_CHAT_ID or now.hour not in BACKUP_HOURS:
        return False
    last = _bot_state.get("backup_sent_at")
    try:
        if last and (now - datetime.fromisoformat(last)).total_seconds() < (
                BACKUP_EVERY_DAYS - 0.5) * 86400:
            return False
    except (TypeError, ValueError):
        pass  # unreadable stamp: send, rather than never again
    if not bot_core.send_backup(TG_CHAT_ID, storage.get_user_lang(TG_CHAT_ID)):
        return False
    _bot_state["backup_sent_at"] = now.isoformat()
    print("  Weekly backup sent to the owner")
    return True


# ── Heads-up before a scheduled release ─────────────────────────
#
# The calendar only reached people as a banner on an alert or a line in the
# daily messages — so a CPI print at 19:30 BKK went unmentioned unless the
# price had already moved enough to trigger an alert. Now each release gets
# one broadcast shortly before it. Announced releases are remembered in
# _bot_state (not the day state, which resets at midnight and would announce
# a 00:30 release twice).

EVENT_HEADSUP_HOURS = 2.0
_ANNOUNCED_KEEP = 20


def _event_key(event) -> str:
    return f"{event.type}@{event.when_utc.isoformat()}"


def announce_upcoming_events(now: datetime) -> bool:
    """Broadcast each release once, within EVENT_HEADSUP_HOURS of it.

    True when _bot_state changed and should be saved.
    """
    announced = list(_bot_state.get("events_announced") or [])
    due = [e for e in events.upcoming(now, within_hours=EVENT_HEADSUP_HOURS)
           if _event_key(e) not in announced]
    for event in due:
        def render(lang, event=event):
            return i18n.t(
                "events.headsup", lang, name=i18n.t(event.label_key, lang),
                emoji=event.emoji,
                est=i18n.t("events.estimated", lang) if event.estimated else "",
                when=event.when().strftime("%H:%M"),
                countdown=bot_core.format_countdown(event.hours_until(now), lang))
        notify(render, "alerts")
        announced.append(_event_key(event))
        print(f"  Event heads-up sent: {event.type} at {event.when_utc:%H:%M} UTC")
    if not due:
        return False
    _bot_state["events_announced"] = announced[-_ANNOUNCED_KEEP:]
    return True


# ── The owner's average cost ────────────────────────────────────
#
# /portfolio shows the P&L when asked. What changes the owner's position is
# the price crossing their average cost, in either direction — so say so when
# it happens. A band around the cost keeps a price sitting on it from
# reporting a cross every few minutes, and a new average (after a buy or a
# sale) re-baselines quietly: the line moved, the price did not cross it.

COST_CROSS_MARGIN = 0.25  # percent either side of the average cost


def alert_owner_on_cost_cross(thb_gram: float) -> bool:
    """Tell the owner when spot crosses their average cost. True = save state."""
    if not TG_CHAT_ID:
        return False
    try:
        book = storage.get_portfolio()
        avg = book.get("avg_cost") or 0
        if book.get("total_grams", 0) <= 0 or avg <= 0:
            return bool(_bot_state.pop("cost_side", None))
        band = avg * COST_CROSS_MARGIN / 100
        side = ("above" if thb_gram >= avg + band
                else "below" if thb_gram <= avg - band else None)
        same_basis = _bot_state.get("cost_basis") == round(avg, 2)
        if side is None or (side == _bot_state.get("cost_side") and same_basis):
            return False
        crossed = same_basis and _bot_state.get("cost_side") is not None
        _bot_state["cost_side"], _bot_state["cost_basis"] = side, round(avg, 2)
        if crossed:
            lang = storage.get_user_lang(TG_CHAT_ID)
            bot_core.send_message(
                i18n.t(f"portfolio.cost_{side}", lang, price=fmt(thb_gram), avg=fmt(avg)),
                TG_CHAT_ID)
            print(f"  Cost cross: spot {side} the average cost {avg}")
        return True
    except Exception as e:
        print(f"[monitor] cost check failed: {e}")
        return False


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

    # A source answering with a frozen quote is swapped out before the quote
    # is stored, alerted on, or fed to the TA reading.
    thb_gram, usd_oz, failover_changed = failover_if_frozen(
        thb_gram, usd_oz, thb_rate, now)

    # ── Store Price History ─────────────────────────────────────
    history = storage.append_price(thb_gram, usd_oz, thb_rate)
    print(f"  History: {len(history)} data points stored")

    # ── Day State ───────────────────────────────────────────────
    state = storage.load_day_state()
    warn_owner_if_runs_lag(state, now)
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
        gta_price = gta.fetch_latest()
        gb = gold_breakdown(thb_gram)

        def build_morning(lang):
            extras = ""
            gta_line = gta.format_line(gta_price, lang, now)
            if gta_line:
                extras += "\n" + gta_line
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
                usd_oz=fmt_usd(usd_oz), thb_rate=thb_rate,
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
    for chat_id, alert in storage.pop_triggered_alerts(thb_gram, usd_oz):
        # Level alerts go to one user each, in that user's own language.
        bot_core.send_message(
            i18n.t("monitor.level_alert", storage.get_user_lang(chat_id),
                   when=time_str,
                   arrow="⬆️" if alert["dir"] == "above" else "⬇️",
                   dir=alert["dir"],
                   target=fmt_target(alert["price"], storage.alert_unit(alert)),
                   price=fmt(thb_gram), usd_oz=fmt_usd(usd_oz)),
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

    # ── Headlines (context only) ────────────────────────────────
    # Fetched ONLY when the other two tiers say something happened: an
    # unusual regime, or a release that just landed. That keeps this off the
    # hot path for the ~288 quiet runs a day, and — more importantly — means
    # headlines always appear as an explanation for a move the bot detected by
    # other means, never as a standalone prompt to act.
    _headline_cache = {}

    def headline_block(lang):
        if not (regime.is_unusual(vol) or event_phase == "post"):
            return ""
        if "items" not in _headline_cache:
            _headline_cache["items"] = news.fetch_headlines()
        return news.format_block(_headline_cache["items"], lang)

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
        out += headline_block(lang)
        return out

    for level in DROP_LEVELS:
        threshold = DROP_THRESHOLD * level["mult"]
        if d >= threshold and not state.get(level["key"]):
            notify(lambda lang, lv=level: i18n.t(
                "monitor.drop", lang, emoji=lv["emoji"],
                title=i18n.t(f"{lv['str']}.title", lang), when=time_str,
                price=fmt(thb_gram), usd_oz=fmt_usd(usd_oz),
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
                usd_oz=fmt_usd(usd_oz), prev_close=fmt(prev_close), pct=gap,
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
                price=fmt(thb_gram), usd_oz=fmt_usd(usd_oz),
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
        # Not -d: negating a zero drop gives -0.0, which renders as "-0.00%"
        # right next to the flat arrow. The rise from the open is the same
        # number and says what it means.
        change = rise_pct(state["open_price"], thb_gram)
        arrow = change_arrow(change)

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
            # The ML outlook as a key, rendered in each recipient's language.
            # The TA reading no longer stands in for it when there are no
            # models: it describes the last day, and "Tomorrow:" in front of
            # it presented it as a forecast.
            outlook_key = pred.get("combined_outlook_key")
            ml_edge = pred.get("ml_has_edge") is True
            rates = predictor.prediction_hit_rates(model_data)
            scored = {h: sc for h, sc in rates.items() if sc.get("n")}
            hit_parts = [f"{h} {sc['hit_pct']}%" for h, sc in sorted(scored.items())]
        else:
            outlook_key, ml_edge, hit_parts = None, False, []

        # Fetch macro ONCE, then render it in each recipient language.
        macro_data = signals.fetch_macro()
        gta_price = gta.fetch_latest()

        def build_evening(lang, owner=False):
            extras = ""
            gta_line = gta.format_line(gta_price, lang, now)
            if gta_line:
                extras += "\n" + gta_line
            if evening_trend_parts:
                extras += i18n.t("monitor.trends", lang,
                                 parts=" | ".join(evening_trend_parts))
            if trend.get("streak", 0) >= 3:
                key = ("monitor.streak_up" if trend["streak_direction"] == "up"
                       else "monitor.streak_down")
                extras += i18n.t(key, lang, hours=trend["streak"])
            # The OWNER's holdings and P&L. /portfolio is owner-only, and this
            # block used to go to every subscriber — anyone who typed /subscribe
            # got the owner's grams and profit every evening.
            if owner and pnl["num_buys"] > 0:
                extras += i18n.t(
                    "monitor.portfolio", lang, grams=pnl["total_grams"],
                    buys=pnl["num_buys"],
                    emoji="🟢" if pnl["pnl_thb"] >= 0 else "🔴",
                    pnl=fmt(pnl["pnl_thb"]), pct=pnl["pnl_pct"])
            # The ML outlook and its live hit-rate: always for the owner, for
            # everyone else only while a model has an edge (predictor.ml_visible).
            if owner or ml_edge:
                if outlook_key:
                    extras += i18n.t("monitor.outlook", lang,
                                     outlook=i18n.t(outlook_key, lang))
                if hit_parts:
                    extras += i18n.t("monitor.hit_rate", lang,
                                     parts=" | ".join(hit_parts))
            # Weekly recap — Sundays only
            if now.weekday() == 6:
                extras += build_weekly_block(history, lang)
            block = signals.format_macro_block(macro_data, lang)
            if block:
                extras += f"\n━━━━━━━━━━━━━━━\n{block}"
            extras += day_event_note(lang)
            extras += regime_block(lang)
            extras += headline_block(lang)
            return i18n.t(
                "monitor.evening", lang, when=time_str, price=fmt(thb_gram),
                open=fmt(state["open_price"]), arrow=arrow, change=change,
                high=fmt(state["day_high"]), low=fmt(state["day_low"]),
                usd_oz=fmt_usd(usd_oz), extras=extras,
            )

        notify(build_evening, "evening",
               owner_msg=lambda lang: build_evening(lang, owner=True))
        state["evening_sent"] = True

    # Remember the latest price so tomorrow can detect an overnight gap, and
    # when this run happened so the next one can tell if it came late.
    state["last_price"] = thb_gram
    state["last_run_at"] = now.isoformat()
    if pending_model_data is not None:
        saved = storage.save_day_state_and_model(state, pending_model_data)
    else:
        saved = storage.save_day_state(state)
    if not saved:
        # Every "already sent" flag lives in this file. If it did not land, the
        # next run re-reads the old state and re-sends the same drop alert —
        # once every five minutes until a write succeeds. Say so loudly; the
        # write itself already logged the underlying cause.
        print("  [WARN] day state NOT saved — alert flags may replay next run")

    # ── Train ML Model (once per day, after enough data) ────────
    # On the first run at or after 03:00, not only on runs inside the 03:00
    # hour: GitHub delivered a run in that hour on 9 of 33 days, so the models
    # and the TA track record went most days without a refresh.
    if hour >= 3 and len(history) >= 100:
        model_data = storage.load_model_data()
        last_trained = model_data.get("last_trained", "")
        today = now.strftime("%Y-%m-%d")
        # Any run after 03:00 may now train, so a training that produced
        # nothing (too little labelled data, one class only) would be redone on
        # every run for the rest of the day, with the same history and the same
        # outcome. One attempt a day, stamped whatever it returns.
        attempted = str(model_data.get("train_attempted_on") or "")[:10] == today
        dirty = False

        # How the TA reading has actually played out, graded the way the
        # models are (predictor.ta_track_record). Pure stdlib, so it does not
        # wait on the ML extras; once a day, like the models. Wrapped so a
        # statistic about the signal can never cost the night's retrain.
        track = model_data.get("ta_track")
        if not (isinstance(track, dict)
                and str(track.get("computed") or "")[:10] == today):
            try:
                track = predictor.ta_track_record(history)
            except Exception as e:
                print(f"[TA] track record failed: {e}")
                track = None
            if track:
                track["computed"] = now.isoformat()
                model_data["ta_track"] = track
                dirty = True

        if (not last_trained or last_trained[:10] != today) and not attempted:
            if not predictor.ml_available():
                # numpy + scikit-learn live in requirements-ml.txt and are
                # installed by THIS workflow only. If that install ever drops
                # them, train_model would simply print and return None — the
                # models would quietly stop updating and /predict would fall
                # back to TA for good. Tell the owner, once a day while broken.
                print("[ML] numpy/scikit-learn missing — cannot train. "
                      "Does this job install requirements-ml.txt?")
                # `or ""`, not a .get() default: a key stored as null comes back
                # as None, and model_data.json already holds nulls by design
                # ("last_trained": None on a fresh file) — so None[:10] would
                # raise TypeError in the one branch that exists to warn.
                if TG_CHAT_ID and (model_data.get("ml_warned_on") or "")[:10] != today:
                    bot_core.send_message(
                        i18n.t("monitor.ml_deps_missing",
                               storage.get_user_lang(TG_CHAT_ID)), TG_CHAT_ID)
                    model_data["ml_warned_on"] = today
                    dirty = True
            else:
                print("[ML] Training prediction models...")
                new_model = predictor.train_model(history)
                model_data["train_attempted_on"] = today
                dirty = True
                if new_model:
                    # MERGE, never replace: train_model returns only the model
                    # payload, so assigning it wholesale would drop the
                    # "predictions" accuracy log that the live hit-rate is built
                    # from — erasing weeks of scored forecasts on every retrain.
                    model_data.update(new_model)
                    dirty = True
                else:
                    print("[ML] Training skipped or failed")

        # One write for everything this block changed.
        if dirty and storage.save_model_data(model_data):
            print("[ML] Model data saved to Gist")

    # ── One-off notices ─────────────────────────────────────────
    # A heads-up before each release, the owner's average-cost crossing and
    # the weekly backup. Each remembers what it did in _bot_state, so none
    # repeats — saved together with any source switch made above.
    try:
        headsup = announce_upcoming_events(now)
        cost = alert_owner_on_cost_cross(thb_gram)
        backup = send_weekly_backup(now)
        if headsup or cost or backup or failover_changed:
            storage.save_bot_state(_bot_state)
    except Exception as e:
        print(f"[monitor] notices failed: {e}")

    # ── Input watchdogs (owner only) ────────────────────────────
    # A price source answering with a frozen quote, and an event calendar about
    # to run out, both fail without an error. Same contract as the webhook
    # check below: throttled through _bot_state, never raising.
    try:
        feed = bot_core.warn_owner_if_feed_stuck(_bot_state, history, usd_oz, now)
        calendar = bot_core.warn_owner_if_calendar_stale(_bot_state, now)
        if feed or calendar:
            storage.save_bot_state(_bot_state)
    except Exception as e:
        print(f"[monitor] input checks failed: {e}")

    # ── Webhook watchdog ────────────────────────────────────────
    # Runs here, not just in the poller, because the poller workflow can be
    # disabled — and was, for three months, while a broken webhook silently
    # swallowed every command. This job is the one that always runs.
    # Throttled to one warning per WEBHOOK_WARN_INTERVAL_H and wrapped so a
    # monitoring check can never take down the monitor.
    try:
        if bot_core.warn_owner_if_webhook_broken(_bot_state):
            storage.save_bot_state(_bot_state)
    except Exception as e:
        print(f"[monitor] webhook health check failed: {e}")

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
        if TG_BOT_TOKEN and TG_CHAT_ID and not bot_core.auth_failed():
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

    # A revoked token cannot be reported BY Telegram — the alert needs the same
    # token. Everything above still ran (prices fetched, history stored), but
    # not one message escaped. Fail the process so the Actions run goes red and
    # GitHub emails the owner; a green-but-mute run is the state that hid this
    # for hours.
    if bot_core.auth_failed():
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN was rejected (401). Prices were collected but "
            "NO alerts could be sent. Update the token in the GitHub repo "
            "secrets (Settings -> Secrets and variables -> Actions) and in "
            "Vercel, using the current token from @BotFather."
        )


if __name__ == "__main__":
    run()
