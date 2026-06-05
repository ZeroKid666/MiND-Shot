<div align="center">

<h1>📡 MiND-Shot</h1>

<p><strong>A free, fully-autonomous crypto trading signal engine that runs entirely on GitHub Actions — no server, no cost, no dependencies.</strong></p>

[![Stars](https://img.shields.io/github/stars/aashir-athar/MiND-Shot?style=for-the-badge&logo=github&color=FFD33D)](https://github.com/aashir-athar/MiND-Shot/stargazers)
[![License](https://img.shields.io/github/license/aashir-athar/MiND-Shot?style=for-the-badge&color=blue)](./LICENSE)
[![Last commit](https://img.shields.io/github/last-commit/aashir-athar/MiND-Shot?style=for-the-badge)](https://github.com/aashir-athar/MiND-Shot/commits)
[![Top language](https://img.shields.io/github/languages/top/aashir-athar/MiND-Shot?style=for-the-badge&logo=python&logoColor=white)](https://github.com/aashir-athar/MiND-Shot)
[![Workflow status](https://img.shields.io/github/actions/workflow/status/aashir-athar/MiND-Shot/engine.yml?style=for-the-badge&label=engine)](https://github.com/aashir-athar/MiND-Shot/actions)

<a href="#-getting-started"><strong>Getting Started</strong></a> ·
<a href="#-how-it-works"><strong>How It Works</strong></a> ·
<a href="https://github.com/aashir-athar/MiND-Shot/issues"><strong>Report Bug</strong></a> ·
<a href="https://github.com/aashir-athar/MiND-Shot/issues"><strong>Request Feature</strong></a>

</div>

---

**MiND-Shot** is an open-source, autonomous **crypto trading signal engine** that runs as a **GitHub Actions cron job** — meaning $0 hosting, no VPS, and no third-party pip dependencies (pure Python stdlib). It polls Kraken's free OHLCV API every minute, runs self-learning trading logic on **BTC and ETH** across multiple timeframes, and ships rich entry/exit alerts straight to your Telegram via a webhook (Make.com / n8n / Pipedream) or the direct Telegram Bot API. A built-in **machine-learning pipeline retrains every Sunday** on fresh historical data, so the engine adapts as the market moves.

> 🚧 **Active development.** MiND-Shot is an evolving research/automation project. It is a decision-support tool, **not financial advice** — see [Honest expectations](#-honest-expectations).

## ✨ Features

| | Feature | Description |
|---|---|---|
| 💸 | **$0 forever** | Runs on a public repo's free GitHub Actions minutes — no server, no VPS, no bill |
| 🐍 | **Zero dependencies** | Pure Python standard library — nothing to `pip install` |
| 📊 | **5 trading modes** | Advanced · Standard · Classic · Channel · Oscillator presets per pair |
| 🧠 | **Self-learning ML** | Bayesian buckets · kNN · online logistic regression · Q-learning ensemble |
| 🎯 | **Trade Verdict score** | 0–100 score blending ML confidence, whale flow, funding, and session |
| 🐋 | **Whale-flow signals** | Binance Futures long/short ratio, open interest, and taker buy/sell context |
| 🪜 | **SL ratchet** | Universal stop-loss laddering: TP1 → BE · TP2 → TP1 · TP3 → TP2 · TP4 → exit |
| 🛡️ | **Risk controls** | Daily loss limit, max concurrent trades, post-SL cool-down, funding pause |
| 🔁 | **Weekly retrain** | Walk-forward logistic model auto-retrains every Sunday via `retrain.yml` |
| 📲 | **Telegram alerts** | Pre-formatted HTML alerts via webhook or direct Bot API |

## 🛠️ Tech Stack

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&logo=githubactions&logoColor=white)
![Kraken](https://img.shields.io/badge/Kraken_API-5741D9?style=for-the-badge&logo=kraken&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)
![Make](https://img.shields.io/badge/Make.com-6D00CC?style=for-the-badge&logo=make&logoColor=white)
![n8n](https://img.shields.io/badge/n8n-EA4B71?style=for-the-badge&logo=n8n&logoColor=white)

| Layer | Choice |
|---|---|
| **Language** | Python 3 (standard library only) |
| **Runtime** | GitHub Actions scheduled workflows (cron) |
| **Market data** | Kraken public OHLCV API · Binance Futures (whale-flow context) |
| **ML** | Custom Bayesian / kNN / logistic / Q-learning ensemble + walk-forward trainer |
| **Delivery** | Telegram Bot API or Make.com / n8n / Pipedream webhook |
| **State** | Git-committed JSON (`state/state.json`, `state/trained_model.json`) |

## 🚀 Getting Started

Setup takes about 5 minutes. Keep your repo **public** to receive unlimited free GitHub Actions minutes.

### Prerequisites
- A **GitHub account** (free)
- A delivery channel — **one of**:
  - A Make.com / n8n / Pipedream account (free tiers are fine), **or**
  - A Telegram Bot token + chat ID (from [@BotFather](https://t.me/BotFather))

No Python install or `pip install` required — everything runs in the GitHub Actions runner.

### 1. Fork or clone

```bash
git clone https://github.com/aashir-athar/MiND-Shot.git
cd MiND-Shot
```

### 2. Add your delivery secret

In your repo go to **Settings → Secrets and variables → Actions → New repository secret**:

```text
# Option A — webhook (recommended)
WEBHOOK_URL = https://hook.eu1.make.com/...      # your Make/n8n/Pipedream URL

# Option B — direct Telegram Bot API
TG_TOKEN    = 1234567890:AAEh...                 # from @BotFather
TG_CHAT_ID  = 123456789
```

Set either one or both. If both are present, `WEBHOOK_URL` wins. Optionally add a `LEVERAGE` repository **variable** (e.g. `10`) for display.

### 3. Enable Actions and run

Open the **Actions** tab and enable workflows. Two are included:

- **MiND-Shot Engine** — runs every minute (`*/1 * * * *`)
- **Weekly ML Retrain** — runs every Sunday at 00:00 UTC (`0 0 * * 0`)

The cron fires automatically. To trigger immediately, open a workflow and click **Run workflow**.

## 📖 Usage

### Customising the active pairs

Edit the `ACTIVE` list near the top of [`mind_shot_engine.py`](./mind_shot_engine.py):

```python
ACTIVE = [
    ('BTC', '4h'),
    ('ETH', '4h'),
    ('BTC', '1h'),
    ('ETH', '1d'),
]
```

Add any `(asset, timeframe)` pair — anything not in the `PRESETS` dict falls back to `DEFAULT_PRESET`.

### Webhook payload

Each entry signal POSTs JSON to your webhook. The `text` field is pre-formatted Telegram HTML ready to forward:

```json
{
  "type": "entry",
  "side": "LONG",
  "asset": "BTC",
  "tf": "4h",
  "ml_conf": 67.3,
  "leverage": 10,
  "entry": 67234.50,
  "sl": 65812.10,
  "tp1": 68420.30,
  "tp2": 69612.80,
  "tp3": 70894.20,
  "tp4": 72510.40,
  "text": "🟢 <b>MiND-Shot LONG</b>  ⚡ 10x\n\n..."
}
```

TP/SL hit events use `type: "event"` with `event: "tp1" | "tp2" | "tp3" | "tp4" | "sl"`.

<details>
<summary><strong>Project structure</strong></summary>

```text
.github/workflows/
├── engine.yml          # 1-min cron · runs the signal engine
└── retrain.yml         # weekly cron · retrains the ML model
mind_shot_engine.py     # main signal engine
ml_trainer.py           # walk-forward ML training
state/
├── state.json          # auto-committed: trades · ML buckets · journal · risk
└── trained_model.json  # auto-committed: weekly walk-forward weights
requirements.txt        # intentionally empty (zero pip deps)
```

</details>

## 🧠 How It Works

Every closed trade updates the engine's self-learning state — **Bayesian buckets** (volatility regime, ADX, RSI level, hour-of-day, mode), a **kNN** history of recent feature vectors, **online logistic** weights, and a **Q-table** of state–action rewards. Signals are blocked when geometric-mean confidence across the current buckets drops below threshold (after enough closed trades for that pair), and stop-loss losses are weighted more heavily than wins so the system actively learns to avoid losing setups.

In parallel, `ml_trainer.py` runs a **walk-forward logistic regression** on ~2 years of Kraken hourly data using 12 engineered features (returns, RSI, ATR, EMA ratio, volume z-score, cyclic hour, distance from support/resistance) and reports **honest out-of-sample accuracy**. This gives every signal a second, independent opinion.

## ⚠️ Honest Expectations

- Real ML on retail crypto data delivers roughly **52–62% out-of-sample directional accuracy** — not magic.
- Combined with the universal SL ratchet (TP1 → break-even), the goal is **positive expectancy over time**, not perfect predictions.
- Any tool promising "100% accuracy" is overfit and will lose money live.
- **This is not financial advice.** Past performance does not guarantee future results. Use responsibly and at your own risk.

## 🗺️ Roadmap

- [x] GitHub Actions cron engine (1-minute polling)
- [x] Self-learning ML ensemble (Bayes · kNN · logistic · Q-learning)
- [x] Weekly walk-forward retraining workflow
- [x] Telegram / webhook alert delivery
- [ ] Additional exchanges and trading pairs
- [ ] Backtest reporting dashboard
- [ ] Configurable strategy presets via repo variables

## 🤝 Contributing

Contributions are welcome. For major changes, please open an issue first to discuss what you would like to change.

1. Fork the repo
2. Create a branch (`git checkout -b feat/your-idea`)
3. Commit your changes and push
4. Open a Pull Request

## 📄 License

Distributed under the **MIT License**. See [LICENSE](./LICENSE) for details.

## 👤 Author

**Aashir Athar**

[![GitHub](https://img.shields.io/badge/GitHub-aashir--athar-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/aashir-athar)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-aashirathar-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/aashirathar/)
[![X](https://img.shields.io/badge/X_(Twitter)-aashirathar-000000?style=for-the-badge&logo=x&logoColor=white)](https://x.com/aashirathar)

<div align="center">

<sub>Built by <a href="https://github.com/aashir-athar">aashir-athar</a> · If MiND-Shot helped you, consider leaving a ⭐</sub>

<br/><br/>

<sub><strong>Keywords:</strong> crypto trading signal engine · algorithmic trading bot · GitHub Actions cron · Bitcoin & Ethereum signals · Kraken API · Telegram trading alerts · machine learning crypto · Python trading automation · serverless trading bot</sub>

</div>
