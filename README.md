<a id="english"></a>

# 🥇 YLG Gold Price Monitor v2 (Telegram)

**🇬🇧 English** · [🇲🇲 မြန်မာ](#myanmar)

Automatic **Telegram** alerts when the gold price moves + **AI price prediction** + **portfolio tracking**.
GitHub Actions + Python — **$0 to run**.

---

## ✨ v2 New Features

- 🔮 **Price Prediction** — 4h/12h/24h outlook from RSI, MACD, Bollinger + an ML model
- 📊 **Portfolio Tracking** — buy/sell log with P&L
- 🤖 **Interactive Bot** — Telegram commands (/price, /predict, /bought, /portfolio)
- 🌐 **Public Bot** — anyone can check the price and subscribe
- 🗣 **3 Languages** — English / မြန်မာ / ไทย, per user via `/lang`
- 📈 **Multi-timeframe Signals** — compare 1h, 4h, 24h and 7d trends
- 🌙 **Rich Evening Summary** — trends, portfolio P&L, prediction outlook
- 💾 **Persistent Storage** — all data kept in a private GitHub Gist

---

## 📲 Telegram Commands

### 🌐 Public Commands (anyone can use)

| Command | Description |
|---|---|
| `/price` | 💰 Current gold price + quick TA |
| `/predict` | 🔮 4h/12h/24h outlook + live hit-rate |
| `/chart [N]` | 📊 N-day price chart image (default 7, max 30) |
| `/alert above\|below <THB>` | 🎯 One-shot alert when a price level is hit (max 5) |
| `/alerts` | 📋 List your price alerts |
| `/delalert <#>` | 🗑 Delete a price alert |
| `/history [N]` | 📈 N-day price history (default 7) |
| `/macro` | 🌍 DXY / US10Y / VIX + fear score |
| `/events` | 📅 Upcoming FOMC / CPI / NFP releases |
| `/subscribe` | 🔔 Receive morning/evening price alerts |
| `/unsubscribe` | 🔕 Stop alerts |
| `/settings` | ⚙️ View notification settings |
| `/mute morning\|evening\|alerts` | 🔕 Turn one category off |
| `/unmute morning\|evening\|alerts` | 🔔 Turn it back on |
| `/quiet 22-7` | 🤫 Quiet hours (BKK) — `/quiet off` to disable |
| `/lang en\|my\|th` | 🌐 Change language (English / မြန်မာ / ไทย) |
| `/help` | ❓ All commands + tap-able buttons |

### 🔒 Owner-Only Commands (bot owner only)

| Command | Description |
|---|---|
| `/bought <THB>` | 📝 Log a purchase (e.g. `/bought 5000`) |
| `/sold <THB>` | 📝 Log a sale |
| `/edit <#> <THB>` | ✏️ Edit an entry |
| `/delete <#>` | 🗑 Delete an entry |
| `/portfolio` | 📊 Portfolio P&L |
| `/setthreshold N` | ⚙️ Change the drop alert % |
| `/setrisethreshold N` | 📈 Change the rise alert % |

Commands reply **instantly via webhook** (primary); the Actions poller is a fallback that checks every **15 minutes**. `/help` and `/start` show **inline buttons** — tap instead of typing.

---

## 📲 Auto Alerts

| When | Message |
|---|---|
| Morning 6am–2pm (once) | 🌅 Open price + trend + TA signal |
| Evening 8–9pm | 🌙 Summary + trends + portfolio + prediction |
| Sunday evening | 📅 Weekly recap (week change, high/low, best/worst day) |

> 🔄 Price checks run every **5 minutes, 24/7** — gold trades around the clock
> on weekdays, so overnight runs are what make the gap-down alert possible.
> Pip caching + a concurrency guard keep cost down and stop overlapping runs
> racing on the Gist. (The repo is public, so Actions minutes are unlimited; if
> it goes private, widen the cron to `*/15`–`*/30`.)
> 📌 The day's **open** is therefore anchored at ~00:00 BKK, and the drop/rise
> alerts measure from there. The move across the day boundary itself is covered
> separately by the gap-down alert vs yesterday's close.
> ⚙️ Subscribers can `/mute` categories or set `/quiet 22-7` hours — alerts
> respect each user's preferences.
> 🌐 Each user also picks their own language with `/lang` — the same broadcast
> is rendered once per language actually in use, not once per subscriber.

**Drop Alerts (5 levels, threshold = 0.5% default):**

| Level | Trigger | Alert |
|---|---|---|
| 1 | ≥ 1× (0.5%) | 🟡 Gold price falling |
| 2 | ≥ 2× (1.0%) | 🟠 Gold price still falling |
| 3 | ≥ 3× (1.5%) | 🔴 Gold price down sharply |
| 4 | ≥ 4× (2.0%) | 🔴🔴 Gold price down severely |
| 5 | ≥ 5× (2.5%) | 🚨 Gold price crashing |

**Rise Alerts (5 levels, threshold = 0.5% default):**

| Level | Trigger | Alert |
|---|---|---|
| 1 | ≥ 1× (0.5%) | 🟢 Gold price is rising |
| 2 | ≥ 2× (1.0%) | 🟢🟢 Gold price keeps rising |
| 3 | ≥ 3× (1.5%) | 🟣 Gold price up sharply |
| 4 | ≥ 4× (2.0%) | 🟣🟣 Gold price up steeply |
| 5 | ≥ 5× (2.5%) | 🚀 Gold price surging |

> 📢 Alerts go to the owner and to every user who ran `/subscribe`
> 🔄 An alert only repeats after the price recovers past the reset band | auto-reset every new day

---

## ⚙️ Setup

### Step 1 — Create a Telegram Bot

1. Telegram: **@BotFather** → `/newbot` → copy the token
2. Open a chat with your bot and send it a message
3. Get your Chat ID from `https://api.telegram.org/bot<TOKEN>/getUpdates`

### Step 2 — Get a GitHub Personal Access Token

1. https://github.com/settings/tokens → **Generate new token (classic)**
2. Scope: check **gist** only
3. Copy the token

### Step 3 — Create the Gist

Run locally:

```bash
GIST_GITHUB_TOKEN=ghp_your_token python setup_gist.py
```

Copy the `GIST_ID` it prints.

### Step 4 — Add GitHub Repo Secrets

Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Chat ID from Step 1 |
| `GIST_GITHUB_TOKEN` | GitHub token from Step 2 |
| `GIST_ID` | Gist ID from Step 3 |

> 🔐 **`WEBHOOK_SECRET` (required if you use the Vercel webhook):**
> the webhook handler **fails closed** — without this it rejects every update
> with 403. Set the same value in the Vercel project environment and in the
> shell you run `setup_webhook.py` from. Generate one with:
>
> ```bash
> python -c "import secrets; print(secrets.token_urlsafe(32))"
> ```
>
> Without it, anyone who learns the webhook URL could forge the owner's chat ID
> and run owner-only commands against your portfolio.

### Step 5 — Push & Test

```bash
git add -A
git commit -m "Gold Monitor v2 — predictions + portfolio"
git push
```

GitHub → **Actions** → **Gold Price Monitor** → **Run workflow**

---

## 🔮 Prediction: How It Works

**Technical Analysis (always available):**
RSI, SMA (5/20), EMA, MACD, Bollinger Bands, Momentum — combined into a buy/hold/wait score.

**ML Model (after 100+ data points ≈ 4 days):**
GradientBoosting classifier trained on historical features. Predicts price direction for 4h, 12h, and 24h horizons. Auto-retrains daily at 3am.

Accuracy is measured **out-of-sample** (train on the first 80%, score the most recent unseen 20%) and compared against a majority-class baseline. A horizon is only treated as a real signal when it beats that baseline (`✅edge`); otherwise it is labelled `⚠️no-edge` and the combined outlook tells you to ignore ML and rely on the TA signal. Gold is close to a random walk at the hourly scale, so do not be surprised when models show no edge — that is the honest result, not a bug.

Both signals are combined for a final outlook in alerts and the `/predict` command.

**Live accuracy tracking:** every evening the bot records its ML predictions, then
scores them once they mature (4h/12h/24h later) against the actual price. The real
hit-rate appears in `/predict` and the evening summary — so you can see whether the
models work in the real world, not just in backtests.

**Reliability:** price history is stored hourly (alert checks still run every 5
minutes); if the monitor itself crashes, the owner gets a 🛑 Telegram alert instead
of silent failure; Telegram rate limits (429) are respected with retry; owner
commands fail closed if `TELEGRAM_CHAT_ID` is unset.

---

## 🌐 Language (English / မြန်မာ / ไทย)

Every alert and command reply is localised per user.

```
/lang          # show the current language + options
/lang en       # English
/lang my       # မြန်မာ  (default)
/lang th       # ไทย
```

The choice is stored per chat alongside the other notification preferences and
shows up in `/settings`. **Myanmar stays the default**, so existing users see
no change unless they opt in. Aliases are accepted (`english`, `mm`, `ไทย`, …).

Broadcasts are rendered **once per language present among the recipients** —
a 500-subscriber alert still builds at most three message bodies.

Indicator and ticker names (RSI, MACD, DXY, VIX, USD/oz) are deliberately left
untranslated; they read as symbols in all three locales.

**Adding a language:** add its code to `LANGUAGES` and `_ALIASES` in
`i18n.py`, then fill in the new entry for every key in `STRINGS`. The test
suite fails on any missing translation or mismatched `{placeholder}` set, so
an incomplete language cannot ship silently.

---

## 📅 Event Calendar (why TA alone is not enough)

Technical indicators describe what the price *has done*. They say nothing about
a Fed decision landing in twenty minutes — and that is where gold's largest
moves come from. `events.py` adds the timing of scheduled US releases:

| | |
|---|---|
| 🏛 FOMC | Rate decision, 14:00 ET |
| 📈 CPI | US inflation, 08:30 ET |
| 👷 NFP | Non-Farm Payrolls, 08:30 ET first Friday (generated, marked *estimated*) |
| 🧾 PCE | US PCE inflation, 08:30 ET |

What it does with them:

- **Before** a release — alerts carry `⚠️ FOMC rate decision in 0h 30m — expect volatility`
- **After** one — `📰 FOMC rate decision just released — this move is likely event-driven`
- **Inside either window** — the TA signal is still shown but explicitly flagged
  as unreliable, because "RSI oversold" 20 minutes before CPI means very little
- **Daily messages** — the morning and evening summaries list anything due in
  the next 24h
- **`/events`** — the next few releases with a countdown, in your language

It also feeds the ML model two new features, `hours_to_event` and
`in_event_window`. Every other feature is derived from the price series itself,
which is a large part of why the models honestly report no edge on a
near-random walk; event timing is the first genuinely **exogenous** input.

> ⚠️ **This calendar is hand-maintained and must be kept current.** Dates are
> the one part of the feature that cannot be derived or tested into
> correctness. Top up `CALENDAR` in `events.py` once a year from
> [federalreserve.gov](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)
> and [bls.gov](https://www.bls.gov/schedule/news_release/cpi.htm).
> `/events` warns the owner when fewer than 45 days remain.

**It does not predict direction.** It says *something scheduled is happening* —
a fact about the calendar, not a forecast about the price.

---

## 📅 Event Calendar (TA တစ်ခုတည်း မလုံလောက်ရခြင်း)

Technical indicators describe what the price *has done*. They say nothing about
a Fed decision landing in twenty minutes — and that is where gold's largest
moves come from. `events.py` adds the timing of scheduled US releases:

| | |
|---|---|
| 🏛 FOMC | Rate decision, 14:00 ET |
| 📈 CPI | US inflation, 08:30 ET |
| 👷 NFP | Non-Farm Payrolls, 08:30 ET first Friday (generated, marked *estimated*) |
| 🧾 PCE | US PCE inflation, 08:30 ET |

What it does with them:

- **Before** a release — alerts carry `⚠️ FOMC rate decision in 0h 30m — expect volatility`
- **After** one — `📰 FOMC rate decision just released — this move is likely event-driven`
- **Inside either window** — the TA signal is still shown but explicitly flagged
  as unreliable, because "RSI oversold" 20 minutes before CPI means very little
- **Daily messages** — the morning and evening summaries list anything due in
  the next 24h
- **`/events`** — the next few releases with a countdown, in your language

It also feeds the ML model two new features, `hours_to_event` and
`in_event_window`. Every other feature is derived from the price series itself,
which is a large part of why the models honestly report no edge on a
near-random walk; event timing is the first genuinely **exogenous** input.

> ⚠️ **This calendar is hand-maintained and must be kept current.** Dates are
> the one part of the feature that cannot be derived or tested into
> correctness. Top up `CALENDAR` in `events.py` once a year from
> [federalreserve.gov](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)
> and [bls.gov](https://www.bls.gov/schedule/news_release/cpi.htm).
> `/events` warns the owner when fewer than 45 days remain.

**It does not predict direction.** It says *something scheduled is happening* —
a fact about the calendar, not a forecast about the price.

---

## 📁 Files

```
goldmonitor/
├── gold_monitor.py          # Main monitor (alerts, summaries) — cron entrypoint
├── events.py                # Scheduled FOMC/CPI/NFP calendar + event windows
├── i18n.py                  # Translation catalogue (en / my / th) + t()
├── predictor.py             # TA indicators + ML prediction (honest OOS eval)
├── storage.py               # GitHub Gist persistent storage
├── goldapi.py               # Price + FX fetch, multi-source fallback (shared)
├── gold_format.py           # Price formatting helpers (shared)
├── bot_core.py              # Telegram I/O + all /command handlers + dispatch (shared)
├── bot_commands.py          # Polling entrypoint (thin) — self-disables if webhook set
├── api/
│   └── webhook.py           # Vercel webhook entrypoint (thin, instant replies)
├── tests/                   # pytest suite (math, portfolio, dispatch, fallbacks)
├── setup_gist.py            # One-time Gist setup script
├── setup_webhook.py         # Webhook setup script
├── vercel.json              # Vercel deployment config
├── requirements.txt         # Runtime dependencies
├── requirements-dev.txt     # + pytest for tests
├── .github/workflows/
│   ├── gold_monitor.yml     # Price check (cron)
│   └── bot_commands.yml     # Command polling (fallback to webhook)
└── README.md
```

> ⚡ **Webhook vs polling:** the Vercel webhook gives instant replies. Telegram
> rejects `getUpdates` (HTTP 409) while a webhook is set, so the polling job now
> auto-disables when a webhook is configured — the two no longer conflict. Use
> the webhook as primary; polling is the keyless fallback.

> 🧪 **Tests:** `pip install -r requirements-dev.txt && pytest`

---
---

<a id="myanmar"></a>

# 🥇 YLG ရွှေဈေး Monitor v2 (Telegram)

[🇬🇧 English](#english) · **🇲🇲 မြန်မာ**

ရွှေဈေး ကျဆင်းတဲ့အချိန် **Telegram** ဖြင့် အလိုအလျောက် သတိပေး + **AI ဈေးခန့်မှန်းချက်** + **Portfolio tracking**
GitHub Actions + Python — **ကုန်ကျငွေ $0**

---

## ✨ v2 New Features

- 🔮 **Price Prediction** — RSI, MACD, Bollinger + ML model ဖြင့် 4h/12h/24h ခန့်မှန်း
- 📊 **Portfolio Tracking** — ဝယ်ယူမှု မှတ်တမ်း + P&L tracking
- 🤖 **Interactive Bot** — Telegram commands (/price, /predict, /bought, /portfolio)
- 🌐 **Public Bot** — ဘယ်သူမဆို ဈေးကြည့်နိုင်၊ subscribe လုပ်နိုင်
- 🗣 **3 Languages** — English / မြန်မာ / ไทย, per-user via `/lang`
- 📈 **Multi-timeframe Signals** — 1h, 4h, 24h, 7d trends ကို ယှဉ်ကြည့်
- 🌙 **Rich Evening Summary** — trends, portfolio P&L, prediction outlook
- 💾 **Persistent Storage** — GitHub Gist ဖြင့် data ကို store

---

## 📲 Telegram Commands

### 🌐 Public Commands (ဘယ်သူမဆို သုံးနိုင်)

| Command | Description |
|---|---|
| `/price` | 💰 လက်ရှိ ရွှေဈေး + quick TA |
| `/predict` | 🔮 4h/12h/24h ခန့်မှန်းချက် + live hit-rate |
| `/chart [N]` | 📊 N-day ဈေး chart ပုံ (default 7, max 30) |
| `/alert above\|below <THB>` | 🎯 ဈေးအဆင့်ရောက်ရင် one-shot alert (max 5) |
| `/alerts` | 📋 သင့် price alerts စာရင်း |
| `/delalert <#>` | 🗑 Price alert ဖျက်ပါ |
| `/history [N]` | 📈 N-day ဈေးသမိုင်း (default 7) |
| `/macro` | 🌍 DXY / US10Y / VIX + fear score |
| `/events` | 📅 လာမည့် FOMC / CPI / NFP ကြေညာချက်များ |
| `/subscribe` | 🔔 မနက်/ညနေ ဈေးနှုန်း alerts ရယူပါ |
| `/unsubscribe` | 🔕 Alerts ရပ်ပါ |
| `/settings` | ⚙️ Notification settings ကြည့်ပါ |
| `/mute morning\|evening\|alerts` | 🔕 Category တစ်ခု ပိတ်ပါ |
| `/unmute morning\|evening\|alerts` | 🔔 ပြန်ဖွင့်ပါ |
| `/quiet 22-7` | 🤫 Quiet hours (BKK) — `/quiet off` ဖြင့် ပိတ်ပါ |
| `/lang en\|my\|th` | 🌐 ဘာသာစကား ပြောင်းပါ (English / မြန်မာ / ไทย) |
| `/help` | ❓ Commands အားလုံး + tap-able buttons |

### 🔒 Owner-Only Commands (bot owner သီးသန့်)

| Command | Description |
|---|---|
| `/bought <THB>` | 📝 ဝယ်ယူမှု မှတ်ပါ (e.g. `/bought 5000`) |
| `/sold <THB>` | 📝 ရောင်းချမှု မှတ်ပါ |
| `/edit <#> <THB>` | ✏️ Entry ပြင်ဆင်ပါ |
| `/delete <#>` | 🗑 Entry ဖျက်ပါ |
| `/portfolio` | 📊 Portfolio P&L |
| `/setthreshold N` | ⚙️ Drop alert % ပြောင်းပါ |
| `/setrisethreshold N` | 📈 Rise alert % ပြောင်းပါ |

Commands reply **instantly via webhook** (primary); the Actions poller is a fallback that checks every **15 minutes**. `/help` and `/start` show **inline buttons** — tap instead of typing.

---

## 📲 Auto Alerts

| အချိန် | Message |
|---|---|
| မနက် 6am–2pm (once) | 🌅 Open ဈေး + trend + TA signal |
| ညနေ 8–9pm | 🌙 Summary + trends + portfolio + prediction |
| တနင်္ဂနွေ ညနေ | 📅 Weekly recap (week change, high/low, best/worst day) |

> 🔄 Price checks run every **5 minutes, 24/7** — gold trades around the clock
> on weekdays, so overnight runs are what make the gap-down alert possible.
> Pip caching + a concurrency guard keep cost down and stop overlapping runs
> racing on the Gist. (The repo is public, so Actions minutes are unlimited; if
> it goes private, widen the cron to `*/15`–`*/30`.)
> 📌 The day's **open** is therefore anchored at ~00:00 BKK, and the drop/rise
> alerts measure from there. The move across the day boundary itself is covered
> separately by the gap-down alert vs yesterday's close.
> ⚙️ Subscribers can `/mute` categories or set `/quiet 22-7` hours — alerts
> respect each user's preferences.
> 🌐 Each user also picks their own language with `/lang` — the same broadcast
> is rendered once per language actually in use, not once per subscriber.

**Drop Alerts (5 levels, threshold = 0.5% default):**

| Level | Trigger | Alert |
|---|---|---|
| 1 | ≥ 1× (0.5%) | 🟡 ရွှေဈေး ကျဆင်း |
| 2 | ≥ 2× (1.0%) | 🟠 ဆက်ကျဆင်း |
| 3 | ≥ 3× (1.5%) | 🔴 ကြီးစွာ ကျဆင်း |
| 4 | ≥ 4× (2.0%) | 🔴🔴 ပြင်းထန်စွာ ကျ |
| 5 | ≥ 5× (2.5%) | 🚨 အကြီးအကျယ် ကျဆင်း |

**Rise Alerts (5 levels, threshold = 0.5% default):**

| Level | Trigger | Alert |
|---|---|---|
| 1 | ≥ 1× (0.5%) | 🟢 ရွှေဈေး တက်နေတယ် |
| 2 | ≥ 2× (1.0%) | 🟢🟢 ဆက်တက်နေတယ် |
| 3 | ≥ 3× (1.5%) | 🟣 ကြီးစွာ တက် |
| 4 | ≥ 4× (2.0%) | 🟣🟣 ပြင်းထန်စွာ တက် |
| 5 | ≥ 5× (2.5%) | 🚀 အကြီးအကျယ် တက် |

> 📢 Alerts များကို owner နှင့် `/subscribe` လုပ်ထားသော users အားလုံးကို ပို့ပါသည်
> 🔄 ဈေးပြန်တက်/ကျပြီး reset ဖြစ်မှ alerts ထပ်ပို့ | နေ့သစ်တိုင်း auto reset

---

## ⚙️ Setup

### Step 1 — Telegram Bot ဆောက်ပါ

1. Telegram: **@BotFather** → `/newbot` → Token ယူပါ
2. Bot နှင့် chat ဖွင့်ပြီး message ပို့ပါ
3. `https://api.telegram.org/bot<TOKEN>/getUpdates` မှ Chat ID ယူပါ

### Step 2 — GitHub Personal Access Token ယူပါ

1. https://github.com/settings/tokens → **Generate new token (classic)**
2. Scope: **gist** ကိုသာ check ပါ
3. Token ကို copy ပါ

### Step 3 — Gist ဆောက်ပါ

Local machine မှာ run ပါ:

```bash
GIST_GITHUB_TOKEN=ghp_your_token python setup_gist.py
```

Print ထုတ်လာသည့် `GIST_ID` ကို copy ပါ

### Step 4 — GitHub Repo Secrets ထည့်ပါ

Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather မှ bot token |
| `TELEGRAM_CHAT_ID` | Step 1 မှ chat ID |
| `GIST_GITHUB_TOKEN` | Step 2 မှ GitHub token |
| `GIST_ID` | Step 3 မှ Gist ID |

> 🔐 **`WEBHOOK_SECRET` (Vercel webhook သုံးမည်ဆိုလျှင် မဖြစ်မနေ လိုအပ်သည်):**
> the webhook handler **fails closed** — without this it rejects every update
> with 403. Set the same value in the Vercel project environment and in the
> shell you run `setup_webhook.py` from. Generate one with:
>
> ```bash
> python -c "import secrets; print(secrets.token_urlsafe(32))"
> ```
>
> Without it, anyone who learns the webhook URL could forge the owner's chat ID
> and run owner-only commands against your portfolio.

### Step 5 — Push & Test

```bash
git add -A
git commit -m "Gold Monitor v2 — predictions + portfolio"
git push
```

GitHub → **Actions** → **Gold Price Monitor** → **Run workflow**

---

## 🔮 Prediction: How It Works

**Technical Analysis (always available):**
RSI, SMA (5/20), EMA, MACD, Bollinger Bands, Momentum — combined into a buy/hold/wait score.

**ML Model (after 100+ data points ≈ 4 days):**
GradientBoosting classifier trained on historical features. Predicts price direction for 4h, 12h, and 24h horizons. Auto-retrains daily at 3am.

Accuracy is measured **out-of-sample** (train on the first 80%, score the most recent unseen 20%) and compared against a majority-class baseline. A horizon is only treated as a real signal when it beats that baseline (`✅edge`); otherwise it is labelled `⚠️no-edge` and the combined outlook tells you to ignore ML and rely on the TA signal. Gold is close to a random walk at the hourly scale, so do not be surprised when models show no edge — that is the honest result, not a bug.

Both signals are combined for a final outlook in alerts and the `/predict` command.

**Live accuracy tracking:** every evening the bot records its ML predictions, then
scores them once they mature (4h/12h/24h later) against the actual price. The real
hit-rate appears in `/predict` and the evening summary — so you can see whether the
models work in the real world, not just in backtests.

**Reliability:** price history is stored hourly (alert checks still run every 5
minutes); if the monitor itself crashes, the owner gets a 🛑 Telegram alert instead
of silent failure; Telegram rate limits (429) are respected with retry; owner
commands fail closed if `TELEGRAM_CHAT_ID` is unset.

---

## 🌐 Language (English / မြန်မာ / ไทย)

Every alert and command reply is localised per user.

```
/lang          # show the current language + options
/lang en       # English
/lang my       # မြန်မာ  (default)
/lang th       # ไทย
```

The choice is stored per chat alongside the other notification preferences and
shows up in `/settings`. **Myanmar stays the default**, so existing users see
no change unless they opt in. Aliases are accepted (`english`, `mm`, `ไทย`, …).

Broadcasts are rendered **once per language present among the recipients** —
a 500-subscriber alert still builds at most three message bodies.

Indicator and ticker names (RSI, MACD, DXY, VIX, USD/oz) are deliberately left
untranslated; they read as symbols in all three locales.

**Adding a language:** add its code to `LANGUAGES` and `_ALIASES` in
`i18n.py`, then fill in the new entry for every key in `STRINGS`. The test
suite fails on any missing translation or mismatched `{placeholder}` set, so
an incomplete language cannot ship silently.

---

## 📁 Files

```
goldmonitor/
├── gold_monitor.py          # Main monitor (alerts, summaries) — cron entrypoint
├── events.py                # Scheduled FOMC/CPI/NFP calendar + event windows
├── i18n.py                  # Translation catalogue (en / my / th) + t()
├── predictor.py             # TA indicators + ML prediction (honest OOS eval)
├── storage.py               # GitHub Gist persistent storage
├── goldapi.py               # Price + FX fetch, multi-source fallback (shared)
├── gold_format.py           # Price formatting helpers (shared)
├── bot_core.py              # Telegram I/O + all /command handlers + dispatch (shared)
├── bot_commands.py          # Polling entrypoint (thin) — self-disables if webhook set
├── api/
│   └── webhook.py           # Vercel webhook entrypoint (thin, instant replies)
├── tests/                   # pytest suite (math, portfolio, dispatch, fallbacks)
├── setup_gist.py            # One-time Gist setup script
├── setup_webhook.py         # Webhook setup script
├── vercel.json              # Vercel deployment config
├── requirements.txt         # Runtime dependencies
├── requirements-dev.txt     # + pytest for tests
├── .github/workflows/
│   ├── gold_monitor.yml     # Price check (cron)
│   └── bot_commands.yml     # Command polling (fallback to webhook)
└── README.md
```

> ⚡ **Webhook vs polling:** the Vercel webhook gives instant replies. Telegram
> rejects `getUpdates` (HTTP 409) while a webhook is set, so the polling job now
> auto-disables when a webhook is configured — the two no longer conflict. Use
> the webhook as primary; polling is the keyless fallback.

> 🧪 **Tests:** `pip install -r requirements-dev.txt && pytest`
