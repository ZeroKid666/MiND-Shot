# MiND-Shot Engine — Standalone Python + GitHub Actions

A free, self-hosted alternative to TradingView Pro+ webhooks. Runs the **identical**
MiND-Shot signal logic on a 5-minute GitHub Actions cron, polling free Kraken OHLCV
data, and pushes alerts to your Telegram via a Make.com webhook (or direct Bot API).

**Cost: $0 forever** (public repo gets unlimited Actions minutes).

---

## ✨ What it does

- Polls **BTC + ETH** on **15m / 30m / 1h / 4h / 1d** from Kraken's free public API
- Runs the same 5-mode signal engine as the Pine Script indicator
  (advanced / standard / classic / channel / oscillator)
- Universal **TP1→BE / TP2→TP1 / TP3→TP2** SL ratchet
- Tracks open trades + Naive Bayes ML state in `state/state.json` (persisted across runs)
- Sends alerts via your **Make.com webhook** (or direct Telegram Bot API)
- Pre-loaded with the **backtested-optimal** asset/TF presets (88–90% WR on 4h)

---

## 🚀 Setup (5 minutes)

### 1. Fork or clone this repo to your GitHub account

```bash
git clone https://github.com/<you>/mind_shot_engine.git
cd mind_shot_engine
```

Keep the repo **public** to get unlimited free GitHub Actions minutes.

### 2. Add your delivery secret

In your GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**:

**Option A — Make.com / n8n / Pipedream webhook (recommended)**
- Name: `WEBHOOK_URL`
- Value: `https://hook.eu1.make.com/...` (your scenario's webhook URL)

**Option B — Direct Telegram Bot API**
- Name: `TG_TOKEN`  · Value: `1234567890:AAEhBxxxxxxxxxxxxxxxxx` (from @BotFather)
- Name: `TG_CHAT_ID` · Value: `123456789` (your chat ID — see below)

> Set EITHER one or both. If both are present, `WEBHOOK_URL` wins.

### 3. (Optional) Set leverage display

Settings → Secrets and variables → Actions → **Variables** tab → New variable:
- Name: `LEVERAGE` · Value: `10` (or whatever you trade with — affects displayed % only)

### 4. Enable Actions

In your repo → **Actions tab** → click "I understand my workflows, go ahead and enable them"

The workflow is set to run **every 5 minutes** automatically. You can also trigger
it manually any time via the "Run workflow" button.

### 5. Verify

After ~5 min, click into the latest run on the Actions tab. You should see:

```
📡 Delivery: webhook (https://hook.eu1.make.com/...)
MiND-Shot Engine — 2026-05-05T10:00:00+00:00
Active pairs: 10
  ▸ BTC 15m (mode=advanced, profile=sharp)
  ▸ BTC 30m (mode=channel, profile=sharp)
  ...
Done.
```

When a real signal fires, you'll get a Telegram message like:

```
🟢 MiND-Shot LONG  ⚡ 10x

📊 Pair: BTC/USD
⏱ TF: 1h  ·  Preset: BTC 1h Optimal
🧠 ML: 67.3% conf
━━━━━━━━━━━━━━━━━
🎯 Entry: 67,234.50
🛡 SL:    65,812.10
✅ TP1: 68,420.30  (50%)
✅ TP2: 69,612.80  (25%)
✅ TP3: 70,894.20  (15%)
🚀 TP4: 72,510.40  (10%)
```

---

## 🛠 How to get your Telegram chat_id (only if using Option B)

1. Send any message to your bot
2. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser
3. Copy the number after `"chat":{"id":` — that's your chat_id

---

## ⚙️ Customising the active pairs / presets

Edit `mind_shot_engine.py`:

```python
ACTIVE = [
    ('BTC', '1h'),    # Pre-loaded BTC 1h Oscillator preset (77.3% WR backtested)
    ('BTC', '4h'),    # 88.9% WR
    ('ETH', '4h'),    # 90.5% WR
    ('ETH', '1d'),    # 82.6% WR
    # add more (asset, tf) tuples — uses DEFAULT_PRESET if not in PRESETS dict
]
```

The `PRESETS` dict near the top contains the optimal config for each (asset, TF).
Tweak any field there to override the backtested defaults.

---

## 📊 Inspecting ML state

Open `state/state.json` (committed back to your repo by the workflow):

```json
{
  "BTC_1h": {
    "active_trade": null,
    "last_signal_bar": 1715000000,
    "ml": {
      "vol":  {"0":[3,2], "1":[12,4], "2":[5,7]},
      "rsi":  {"0":[2,5], "1":[8,3],  "2":[10,4], "3":[1,3]},
      "ses":  {"0":[4,6], "1":[7,3],  "2":[9,2],  "3":[1,2]},
      "mode": {"0":[19,8], "2":[2,2]},
      "total_trades": 27
    }
  },
  ...
}
```

Each bucket stores `[wins, losses]`. The ML filter blocks new signals when the
geometric-mean confidence across the current bar's buckets falls below 40%
(only after 10+ closed trades for that pair).

---

## 🔧 Local dev / dry-run

```bash
python mind_shot_engine.py
```

With no env vars set, alerts go to stdout (dry-run mode). Useful for testing
indicator logic without spamming your phone.

---

## ⚠️ Disclaimers

- **Sample size matters.** ML kicks in after 10+ closed trades per pair. Earlier signals are unfiltered.
- **Past performance ≠ future results.** Backtested win rates were on 2025–2026 data; market regimes shift.
- **Kraken API rate limits.** The 5-min cron stays well under limits for 10 pairs. Don't push to 1-min cron without splitting requests.
- **GitHub Actions cron is "best effort"** — runs may be delayed by 1–10 min during high load. Acceptable for 15m+ TFs, marginal for 5m.
- **Use at your own risk.** This is not financial advice.

---

## 📁 Repo layout

```
mind_shot_engine/
├── .github/workflows/engine.yml    # cron job (every 5 min)
├── mind_shot_engine.py             # main engine
├── state/
│   └── state.json                  # ML + open-trade state (auto-committed)
├── requirements.txt                # empty (zero deps — pure stdlib)
├── .gitignore
└── README.md
```

---

## License

MIT
