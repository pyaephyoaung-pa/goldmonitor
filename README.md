# 🥇 YLG Gold Price Monitor v2 (Telegram)

ရွှေဈေး ကျဆင်းတဲ့အချိန် **Telegram** ဖြင့် အလိုအလျောက် သတိပေး + **AI ဈေးခန့်မှန်းချက်** + **Portfolio tracking**
GitHub Actions + Python — **ကုန်ကျငွေ $0**

---

## ✨ v2 New Features

- 🔮 **Price Prediction** — RSI, MACD, Bollinger + ML model ဖြင့် 4h/12h/24h ခန့်မှန်း
- 📊 **Portfolio Tracking** — ဝယ်ယူမှု မှတ်တမ်း + P&L tracking
- 🤖 **Interactive Bot** — Telegram commands (/price, /predict, /bought, /portfolio)
- 📈 **Multi-timeframe Signals** — 1h, 4h, 24h, 7d trends ကို ယှဉ်ကြည့်
- 🌙 **Rich Evening Summary** — trends, portfolio P&L, prediction outlook
- 💾 **Persistent Storage** — GitHub Gist ဖြင့် data ကို store

---

## 📲 Telegram Commands

| Command | Description |
|---|---|
| `/price` | 💰 လက်ရှိ ရွှေဈေး + quick TA |
| `/predict` | 🔮 4h/12h/24h ခန့်မှန်းချက် |
| `/bought <THB>` | 📝 ဝယ်ယူမှု မှတ်ပါ (e.g. `/bought 5000`) |
| `/portfolio` | 📊 Portfolio P&L |
| `/history [N]` | 📈 N-day ဈေးသမိုင်း (default 7) |
| `/setthreshold N` | ⚙️ Alert % ပြောင်းပါ |
| `/help` | ❓ Commands အားလုံး |

Commands are checked every **5 minutes** via GitHub Actions.

---

## 📲 Auto Alerts

| အချိန် | Message |
|---|---|
| မနက် (first run) | 🌅 Open ဈေး + trend + TA signal |
| ဈေး drop ≥ threshold | 🟡 ဝယ်သင့်တဲ့ alert + RSI |
| ဈေး drop ≥ 1.5× threshold | 🔴 ကြီးစွာ ကျဆင်း alert |
| ညနေ 8–9pm | 🌙 Summary + trends + portfolio + prediction |

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

Both signals are combined for a final outlook in alerts and the `/predict` command.

---

## 📁 Files

```
goldmonitor/
├── gold_monitor.py          # Main hourly monitor
├── predictor.py             # TA indicators + ML prediction
├── storage.py               # GitHub Gist persistent storage
├── bot_commands.py           # Telegram command handler
├── setup_gist.py            # One-time Gist setup script
├── requirements.txt         # Python dependencies
├── .github/workflows/
│   ├── gold_monitor.yml     # Hourly price check
│   └── bot_commands.yml     # 5-min command polling
└── README.md
```
