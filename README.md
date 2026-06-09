# 🥇 YLG Gold Price Monitor v2 (Telegram)

ရွှေဈေး ကျဆင်းတဲ့အချိန် **Telegram** ဖြင့် အလိုအလျောက် သတိပေး + **AI ဈေးခန့်မှန်းချက်** + **Portfolio tracking**
GitHub Actions + Python — **ကုန်ကျငွေ $0**

---

## ✨ v2 New Features

- 🔮 **Price Prediction** — RSI, MACD, Bollinger + ML model ဖြင့် 4h/12h/24h ခန့်မှန်း
- 📊 **Portfolio Tracking** — ဝယ်ယူမှု မှတ်တမ်း + P&L tracking
- 🤖 **Interactive Bot** — Telegram commands (/price, /predict, /bought, /portfolio)
- 🌐 **Public Bot** — ဘယ်သူမဆို ဈေးကြည့်နိုင်၊ subscribe လုပ်နိုင်
- 📈 **Multi-timeframe Signals** — 1h, 4h, 24h, 7d trends ကို ယှဉ်ကြည့်
- 🌙 **Rich Evening Summary** — trends, portfolio P&L, prediction outlook
- 💾 **Persistent Storage** — GitHub Gist ဖြင့် data ကို store

---

## 📲 Telegram Commands

### 🌐 Public Commands (ဘယ်သူမဆို သုံးနိုင်)

| Command | Description |
|---|---|
| `/price` | 💰 လက်ရှိ ရွှေဈေး + quick TA |
| `/predict` | 🔮 4h/12h/24h ခန့်မှန်းချက် |
| `/history [N]` | 📈 N-day ဈေးသမိုင်း (default 7) |
| `/subscribe` | 🔔 မနက်/ညနေ ဈေးနှုန်း alerts ရယူပါ |
| `/unsubscribe` | 🔕 Alerts ရပ်ပါ |
| `/help` | ❓ Commands အားလုံး |

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

Commands are checked every **5 minutes** via GitHub Actions + **instant via webhook**.

---

## 📲 Auto Alerts

| အချိန် | Message |
|---|---|
| မနက် (first run) | 🌅 Open ဈေး + trend + TA signal |
| ညနေ 8–9pm | 🌙 Summary + trends + portfolio + prediction |

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

---

## 📁 Files

```
goldmonitor/
├── gold_monitor.py          # Main monitor (alerts, summaries) — cron entrypoint
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
