<div align="center">

<h1>📡 MiND-Shot</h1>

<p><strong>A free, fully-autonomous crypto signal engine driven by five backtested mean-reversion strategies — running entirely on GitHub Actions. No server, no cost, no dependencies.</strong></p>

[![Stars](https://img.shields.io/github/stars/aashir-athar/MiND-Shot?style=for-the-badge&logo=github&color=FFD33D)](https://github.com/aashir-athar/MiND-Shot/stargazers)
[![License](https://img.shields.io/github/license/aashir-athar/MiND-Shot?style=for-the-badge&color=blue)](./LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/aashir-athar/MiND-Shot/ci.yml?style=for-the-badge&label=ci)](https://github.com/aashir-athar/MiND-Shot/actions/workflows/ci.yml)
[![Engine](https://img.shields.io/github/actions/workflow/status/aashir-athar/MiND-Shot/engine.yml?style=for-the-badge&label=engine)](https://github.com/aashir-athar/MiND-Shot/actions/workflows/engine.yml)
[![Top language](https://img.shields.io/github/languages/top/aashir-athar/MiND-Shot?style=for-the-badge&logo=python&logoColor=white)](https://github.com/aashir-athar/MiND-Shot)

<a href="#-the-five-strategies"><strong>Strategies</strong></a> ·
<a href="#-getting-started"><strong>Getting Started</strong></a> ·
<a href="#-how-it-works"><strong>How It Works</strong></a> ·
<a href="https://github.com/aashir-athar/MiND-Shot/issues"><strong>Report Bug</strong></a>

</div>

---

**MiND-Shot** is an open-source **crypto signal engine** that runs as a **GitHub Actions cron job** — $0 hosting, no VPS, and no third-party pip dependencies (pure Python standard library). Its signal brain is a set of **five strategies that were each selected from a 1,620-config backtest sweep** and validated out-of-sample on real BTC/ETH data. Around them sits a full intelligence layer — a self-learning ML ensemble, whale-flow context, a Trade Verdict score, and hard risk controls — and rich entry/exit alerts shipped straight to your Telegram via a webhook (Make.com / n8n / Pipedream) or the direct Bot API.

> 🚧 **Active research/automation project.** It is a decision-support tool, **not financial advice** — see [Honest expectations](#-honest-expectations).

## ✨ Features

| | Feature | Description |
|---|---|---|
| 💸 | **$0 forever** | Runs on a public repo's free GitHub Actions minutes — no server, no VPS |
| 🐍 | **Zero dependencies** | Pure Python standard library — nothing to `pip install` |
| 🎯 | **5 backtested strategies** | Range-fading mean-reversion (VWAP · RSI-2 · Stochastic · Z-score), ADX-gated, both directions |
| 🧪 | **Self-validating** | `python -m mind_shot.backtest` reproduces the documented win rates on live data; CI runs it |
| 🧠 | **Self-learning ML** | Bayesian buckets + walk-forward logistic model as an advisory second opinion |
| 🎛 | **Trade Verdict score** | 0–100 score blending ML confidence, whale flow, funding, and session |
| 🐋 | **Whale-flow signals** | Binance Futures long/short ratio, open interest, taker buy/sell pressure |
| 🛡️ | **Risk controls** | Daily loss limit, max concurrent trades, post-SL cool-down |
| 🔁 | **Weekly retrain** | Walk-forward logistic model auto-retrains every Sunday |
| 📲 | **Telegram alerts** | Pre-formatted HTML alerts via webhook or direct Bot API |

## 🎯 The Five Strategies

All five share one edge — **fade an extreme back toward the mean, but only while the market is ranging (`ADX(14) < 25`)** — and each trades **both long and short** on the **4-hour** chart. Backtested at **$100 wallet · 10× · 15%-of-wallet · cross margin · 0.10% round-trip**:

| Strategy | Coin | Win rate | Entry | Exit | Stop |
|---|---|---:|---|---|---|
| **VWAP-Reversion** | ETH | 78.4% | price ±2σ from VWAP(20) | TP 0.75×ATR | 1.5×ATR |
| **RSI-2 Reversion** | ETH | 72.3% | RSI(2) < 10 / > 90 | TP 0.75×ATR | 1.5×ATR |
| **VWAP-Reversion (revert)** | ETH | 70.0% | price ±2σ from VWAP(20) | back to VWAP | 2.0×ATR |
| **Stochastic Reversion** | ETH | 75.9% | %K(14) < 20 / > 80 | TP 0.75×ATR | 2.0×ATR |
| **Z-Score Reversion** | BTC | 65.1% | ±1.5σ from SMA(20) | back to mean | 3.0×ATR |

These numbers are **in-sample backtests, not promises.** Win rate alone is not edge — see [Honest expectations](#-honest-expectations). The full research lives in the project notes; the strategy definitions are in [`mind_shot/strategies.py`](./mind_shot/strategies.py).

## 🛠️ Tech Stack

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&logo=githubactions&logoColor=white)
![Kraken](https://img.shields.io/badge/Kraken_API-5741D9?style=for-the-badge&logo=kraken&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)

| Layer | Choice |
|---|---|
| **Language** | Python 3.10+ (standard library only) |
| **Runtime** | GitHub Actions scheduled workflows (cron) |
| **Market data** | Kraken public OHLC for the live feed (reachable from GitHub Actions; Binance geo-blocks the US runner IPs). The backtest validates against committed Binance 4h fixtures. |
| **Context** | Binance whale-flow · CoinGecko dominance · alternative.me Fear & Greed |
| **ML** | Bayesian buckets + walk-forward logistic ensemble |
| **Delivery** | Telegram Bot API or Make.com / n8n / Pipedream webhook |
| **State** | Git-committed JSON (`state/state.json`, `state/trained_model.json`) |

## 🚀 Getting Started

Setup takes about 5 minutes. Keep your repo **public** for unlimited free Actions minutes.

### 1. Fork or clone
```bash
git clone https://github.com/aashir-athar/MiND-Shot.git
cd MiND-Shot
```

### 2. Add your delivery secret
**Settings → Secrets and variables → Actions → New repository secret**:
```text
# Option A — webhook (recommended)
WEBHOOK_URL = https://hook.eu1.make.com/...

# Option B — direct Telegram Bot API
TG_TOKEN    = 1234567890:AAEh...     # from @BotFather
TG_CHAT_ID  = 123456789
```
If both are set, `WEBHOOK_URL` wins. Optional repo **variables**: `LEVERAGE` (default `10`), `ACCOUNT_USD` (`100`), `ALLOC_PCT` (`15`).

### 3. Enable Actions
Open the **Actions** tab and enable workflows. Three are included:
- **MiND-Shot Engine** — polls every few minutes and ships signals
- **Weekly ML Retrain** — retrains the logistic model every Sunday
- **CI** — runs the test suite + strategy validation on every push

## 📖 Usage

### Configuration (environment variables)
| Var | Default | Purpose |
|---|---|---|
| `WEBHOOK_URL` / `TG_TOKEN` + `TG_CHAT_ID` | — | delivery channel |
| `LEVERAGE` | `10` | leverage shown in alerts / PnL math |
| `ACCOUNT_USD` | `100` | account size for sizing display |
| `ALLOC_PCT` | `15` | % of wallet per trade |
| `ML_GATING_ENABLED` | `1` | let the Bayesian model veto low-confidence signals |
| `ML_MIN_TRADES` / `ML_MIN_CONF` | `12` / `0.40` | when/how strongly ML may veto |

The active strategy set is fixed to the five validated strategies (in `mind_shot/strategies.py`); there are no ad-hoc modes to misconfigure.

### Webhook payload
Each entry POSTs JSON; the `text` field is pre-formatted Telegram HTML ready to forward:
```json
{
  "type": "entry",
  "side": "LONG",
  "asset": "ETH",
  "tf": "4h",
  "strategy": "vwap_bracket_eth",
  "strategy_name": "VWAP-Reversion (bracket)",
  "ml_conf": 58.3,
  "leverage": 10,
  "entry": 1800.58,
  "sl": 1753.20,
  "tp": 1824.10,
  "target": null,
  "text": "🟢 ... MiND-Shot LONG ..."
}
```
TP / SL / exit events use `type: "event"` with `event: "tp" | "sl" | "exit"`.

## 🧠 How It Works

1. **Data** — every poll fetches recent **Kraken 4h** candles for ETH and BTC (Kraken is reachable from GitHub Actions runners; Binance returns HTTP 451 to their US IPs). The strategies are price-based, so the signals match the backtest.
2. **Signals** — each strategy checks, on the most recently *closed* bar, whether its oscillator is at an extreme **and** `ADX(14) < 25`. If so it proposes a long or short; the engine acts on the next bar's open.
3. **Second opinion** — a self-learning **Bayesian ensemble** scores the setup from past outcomes (stop-losses weighted more heavily than wins) and can veto weak signals once a strategy has enough history. A weekly **walk-forward logistic model** adds an independent directional tilt to the Trade Verdict.
4. **Management** — bracket strategies exit on a fixed take-profit / stop; revert strategies ride back to VWAP or the mean with a hard ATR stop. Stops are checked intrabar, stop-first.
5. **Delivery & learning** — entries and TP/SL/exit events ship to Telegram; every closed trade updates the ML, the streak heatmap, the journal, and the daily-R stats, all committed back to `state/`.

## 🧪 Validation

The strategies are **self-validating** — the same indicator/strategy code the live engine uses is replayed **offline** over committed fixtures of the original backtest window (`tests/fixtures/*_4h.csv`):
```bash
python -m mind_shot.backtest
```
It prints each strategy's win rate, trade count, and $100→ result, and fails if any strategy drifts materially from its documented numbers. It needs no network, so CI runs it deterministically on every push.

## 🧰 Development
```bash
python -m unittest discover -s tests -v      # unit tests (no network)
python -m mind_shot.backtest                 # strategy validation (live data)
OUTPUT_JSON=1 python mind_shot_engine.py      # one local dry-run (no secrets = no alerts sent)
```

<details>
<summary><strong>Project structure</strong></summary>

```text
mind_shot/
├── indicators.py     # pure-stdlib SMA/STD/z-score/RSI/ATR/ADX/Stochastic/VWAP
├── strategies.py     # the 5 backtested strategies (the registry)
├── market.py         # Kraken 4h klines (live feed)
├── trading.py        # trade lifecycle (bracket + revert exits)
├── ml.py             # Bayesian ensemble + trained-model application
├── context.py        # Fear & Greed / dominance / funding
├── whale.py          # whale-flow signals
├── intelligence.py   # Trade Verdict + analytics
├── notifier.py       # delivery + alert formatting
├── state.py          # atomic JSON state
├── config.py         # env-driven configuration
├── engine.py         # poll orchestration
└── backtest.py       # in-repo validation backtest
mind_shot_engine.py   # entrypoint (used by the engine workflow / Electron host)
ml_trainer.py         # weekly walk-forward trainer
tests/                # unit tests + backtest fixtures (committed 4h playbook data)
.github/workflows/    # engine.yml · retrain.yml · ci.yml
```
</details>

## ⚠️ Honest Expectations

- **Win rate is not edge.** A high win rate with a wide stop can still lose money; these strategies are profitable only because their win rate clears the break-even implied by their reward:risk.
- The backtested numbers are **in-sample on one bear/chop regime**, selected from many configs. Expect **lower live win rates (~60–68%)** and **thin expectancy**, and **paper-trade before risking real capital**.
- The entire edge is *"ranges revert."* A real trend breaking out of the range produces a cluster of losses — the `ADX < 25` filter reduces but does not remove this.
- The ML adds roughly **52–62% out-of-sample directional accuracy** — a second opinion, not magic. Any tool promising "100% accuracy" is overfit and will lose money live.
- **This is not financial advice.** Past performance does not guarantee future results. Use responsibly and at your own risk.

## 🗺️ Roadmap
- [x] Five backtested, out-of-sample-validated strategies as the signal core
- [x] In-repo backtest + unit tests + CI
- [x] Self-learning ML ensemble + weekly walk-forward retrain
- [x] Telegram / webhook alert delivery
- [ ] Configurable strategy set via repo variables
- [ ] Backtest reporting dashboard

## 🤝 Contributing
Contributions are welcome. For major changes, please open an issue first. Fork → branch (`git checkout -b feat/your-idea`) → commit → open a PR. CI must pass.

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
<sub><strong>Keywords:</strong> crypto trading signal engine · mean-reversion strategies · algorithmic trading bot · GitHub Actions cron · Bitcoin &amp; Ethereum signals · Binance API · Telegram trading alerts · Python trading automation · serverless trading bot</sub>
</div>
</div>
