# MiND-Shot Engine — GitHub Actions Cloud Cron

A free, fully-autonomous trading signal engine that runs on GitHub's free Actions
infrastructure. Polls Kraken every minute, runs the MiND-Shot signal logic on
**BTC + ETH** across multiple timeframes, ships rich alerts to your Telegram via a
Make.com / n8n / Pipedream webhook (or direct Telegram Bot API), and **retrains its
ML model every Sunday** on the latest historical data.

**Cost: $0 forever** (public repo gets unlimited GitHub Actions minutes).

## ✨ What it does (full feature set)

### Signal Engine
- Polls Kraken's free OHLCV API for 4 starred preset pairs (BTC/ETH × 4h/1h/1d)
- 5 trading modes: Advanced · Standard · Classic · Channel · Oscillator
- Universal SL ratchet: TP1 → BE · TP2 → TP1 · TP3 → TP2 · TP4 → exit
- Bayesian per-feature-bucket ML self-learning (learns from every closed trade)
- Multi-engine ML: Bayes · kNN · Logistic · Q-Learning · Ensemble

### Decision Support
- **Trade Verdict scoring** (0-100) combining ML + Whale + Funding + Session
- **Whale flow detection** (Binance Futures L/S ratio · OI · taker buy/sell · Whale Alert)
- **Per-pair TP/SL hit accuracy** computed from journal data
- **BTC ↔ ETH correlation** with lead/lag intelligence
- **Weekly summary** (this week vs prior week R-multiples)

### Risk Management
- Daily loss limit auto-pause (default -3R)
- Max concurrent trades cap (default 4)
- Post-SL cool-down per pair (default 240 min)
- Funding pause threshold (default 0.05%)
- Configurable risk-per-trade % (default 1%)
- Paper mode toggle (state isolated)

### ML Pipeline
- Walk-forward trained logistic regression on 2yr Kraken hourly data
- 12 engineered features (returns, RSI, ATR, EMA ratio, vol z-score, hour cyclic, distance from S/R)
- Honest out-of-sample accuracy reporting (52-62% typical)
- **Auto-retrains every Sunday** via `retrain.yml` workflow

## 📋 Prerequisites

- **GitHub account** (free)
- **Make.com / n8n / Pipedream account** for Telegram delivery (free tiers fine)
- OR a Telegram Bot token + chat ID (also free)

Zero pip dependencies. Pure Python stdlib.

## 🚀 Setup (5 minutes)

### 1. Fork or clone this repo

```bash
git clone https://github.com/<you>/mind-shot.git
cd mind-shot
```

Keep the repo **public** to get unlimited free GitHub Actions minutes.

### 2. Add your delivery secret

In your GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**:

**Option A — Make.com / n8n / Pipedream webhook (recommended)**
- Name: `WEBHOOK_URL`
- Value: `https://hook.eu1.make.com/...` (your scenario's webhook URL)

**Option B — Direct Telegram Bot API**
- Name: `TG_TOKEN`  · Value: `1234567890:AAEhBxxxxxxxxxxxxxxxxx` (from @BotFather)
- Name: `TG_CHAT_ID` · Value: `123456789`

> Set EITHER one or both. If both are present, `WEBHOOK_URL` wins.

### 3. (Optional) Set leverage display

Settings → Secrets and variables → Actions → **Variables** tab → New variable:
- Name: `LEVERAGE` · Value: `10`

### 4. Enable Actions

Repo → **Actions tab** → click "I understand my workflows, go ahead and enable them"

Two workflows are set up:
- **MiND-Shot Engine** — runs every 1 minute (cron `*/1 * * * *`)
- **Weekly ML Retrain** — runs every Sunday at 00:00 UTC (cron `0 0 * * 0`)

### 5. First run

The cron fires automatically. To trigger immediately:
- Actions tab → "MiND-Shot Engine" → Run workflow
- Or for ML training: "Weekly ML Retrain" → Run workflow

## 🛠 File structure

```
mind_shot_github/
├── .github/workflows/
│   ├── engine.yml         # 1-min cron · runs signal engine
│   └── retrain.yml        # weekly cron · retrains ML model
├── mind_shot_engine.py    # main signal engine (~1100 lines)
├── ml_trainer.py          # walk-forward ML training
├── state/
│   ├── state.json         # auto-committed: trades + ML buckets + journal + risk
│   └── trained_model.json # auto-committed: weekly walk-forward weights
├── requirements.txt       # empty (zero pip deps)
└── README.md
```

## 📡 Webhook payload format

Each entry signal POSTs JSON like this to your webhook URL:

```json
{
  "type": "entry",
  "side": "LONG",
  "asset": "BTC",
  "tf": "4h",
  "preset": "🏆 BTC 4h Optimal",
  "ml_conf": 67.3,
  "leverage": 10,
  "entry": 67234.50,
  "sl":    65812.10,
  "tp1":   68420.30,
  "tp2":   69612.80,
  "tp3":   70894.20,
  "tp4":   72510.40,
  "text":  "🟢 <b>MiND-Shot LONG</b>  ⚡ 10x\n\n..."
}
```

The `text` field is pre-formatted Telegram HTML. In Make.com:
1. Webhook trigger → Re-determine data structure
2. Trigger one workflow run (Actions → Run workflow) so Make ingests the schema
3. Telegram action → map Text field to `{{1.text}}` → Parse Mode `HTML`

For TP/SL hit events, the payload has `type: "event"` and `event: "tp1"|"tp2"|"tp3"|"tp4"|"sl"` plus pre-formatted text.

## ⚙️ Customising

Edit `mind_shot_engine.py` near the top:

```python
ACTIVE = [
    ('BTC', '4h'),   # 🏆 BTC 4h Optimal       (88.9% WR backtested)
    ('ETH', '4h'),   # 🏆 ETH 4h Optimal       (90.5% WR backtested)
    ('BTC', '1h'),   # 🏆 BTC 1h Oscillator    (77.3% WR backtested)
    ('ETH', '1d'),   # 🏆 ETH 1d Swing         (82.6% WR backtested)
]
```

Add more (asset, tf) pairs — anything not in the `PRESETS` dict uses `DEFAULT_PRESET`.

## 🧠 ML Self-Learning

Every closed trade updates:
- **Bayesian buckets** (vol regime · ADX · RSI level · hour-of-day · trading mode)
- **kNN history** (last 100 trade feature vectors)
- **Logistic weights** (online SGD)
- **Q-table** (state-action rewards)

Signals get blocked when geometric-mean confidence across current buckets drops below 40% (only after 10+ closed trades for that pair). SL losses are weighted 2× harder than TP wins, so the system actively learns to avoid losing setups.

The walk-forward trained model gives a SECOND opinion using 12 engineered features. After the first Sunday retrain, `state/trained_model.json` will contain weights + out-of-sample accuracy stats.

## ⚠️ Honest expectations

- Real ML on retail crypto data: **52-62% out-of-sample directional accuracy**
- Combined with universal SL ratchet (TP1 → BE) = positive expectancy over time
- Any tool promising "100% accuracy" is overfit and will lose money live
- Past performance ≠ future results · use responsibly

## 📜 License

MIT
