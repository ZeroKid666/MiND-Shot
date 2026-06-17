"""
The self-learning second opinion.

Two independent models, both preserved from v1 and kept as advisory overlays on the
five strategies (they never invent a signal — they only score or, optionally, veto one):

  • Bayesian buckets — per-strategy win/loss tallies across volatility, RSI, session,
    and strategy dimensions; a geometric-mean confidence that can gate a signal once
    a strategy has enough closed trades. Stop-losses are weighted more heavily than
    wins so the engine learns to avoid losing contexts.
  • Trained logistic model — the walk-forward regression from ``ml_trainer.py``,
    applied with the exact 12 features it was trained on, as a directional tilt.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from . import config, indicators as ind
from .models import C, H, L, V, Candle
from .strategies import STRATEGIES

_STRAT_INDEX = {s.id: i for i, s in enumerate(STRATEGIES)}


# ── bucketing ────────────────────────────────────────────────────────────────
def vol_bucket(v: float) -> int:
    return 0 if v < 0.7 else (2 if v > 1.3 else 1)


def rsi_bucket(r: float) -> int:
    return 0 if r < 30 else 1 if r < 50 else 2 if r < 70 else 3


def session_bucket(hour: int) -> int:
    return 0 if hour < 7 else 1 if hour < 13 else 2 if hour < 21 else 3


def strategy_bucket(strategy_id: str) -> int:
    return _STRAT_INDEX.get(strategy_id, 0)


def laplace(wins: float, losses: float) -> float:
    return (wins + 1) / (wins + losses + 2)


# ── Bayesian model ───────────────────────────────────────────────────────────
def build_snapshot(series: Dict[str, List[Optional[float]]], i: int, strategy_id: str, time_s: int) -> Dict[str, int]:
    atr = series["atr"]
    vol_regime = (atr[i] / atr[i - 50]) if (i >= 50 and atr[i - 50]) else 1.0
    rsi_v = series["rsi14"][i] if series["rsi14"][i] is not None else 50.0
    hour = datetime.fromtimestamp(time_s, tz=timezone.utc).hour
    return {
        "vol_b": vol_bucket(vol_regime),
        "rsi_b": rsi_bucket(rsi_v),
        "ses_b": session_bucket(hour),
        "strat_b": strategy_bucket(strategy_id),
    }


def predict(ml: Dict[str, Any], snap: Dict[str, int]) -> float:
    """Geometric-mean confidence across the four Bayesian dimensions."""
    def lookup(dim: str, key: int) -> float:
        v = ml.get(dim, {}).get(str(key), [0, 0])
        return laplace(v[0], v[1])

    return (
        lookup("vol", snap["vol_b"])
        * lookup("rsi", snap["rsi_b"])
        * lookup("ses", snap["ses_b"])
        * lookup("strat", snap["strat_b"])
    ) ** 0.25


def update(ml: Dict[str, Any], snap: Dict[str, int], won: bool, gross_profit: float = 0.0, gross_loss: float = 0.0) -> None:
    delta = 1 if won else config.ML_PENALTY_SL
    idx = 0 if won else 1
    for dim, key in (("vol", "vol_b"), ("rsi", "rsi_b"), ("ses", "ses_b"), ("strat", "strat_b")):
        bucket = str(snap[key])
        ml.setdefault(dim, {}).setdefault(bucket, [0, 0])
        ml[dim][bucket][idx] += delta
    ml["total_trades"] = ml.get("total_trades", 0) + 1
    ml["wins"] = ml.get("wins", 0) + (1 if won else 0)
    ml["gross_profit"] = ml.get("gross_profit", 0.0) + gross_profit
    ml["gross_loss"] = ml.get("gross_loss", 0.0) + gross_loss


# ── Trained logistic model (matches ml_trainer.py features exactly) ──────────
def apply_trained_model(model: Optional[Dict[str, Any]], candles: Sequence[Candle], i: int, asset: str) -> Optional[float]:
    """Probability of an up-move over the trainer's horizon, or ``None``.

    Recomputes the same 12 features ``ml_trainer.build_features`` used, then applies
    the asset-specific standardised logistic weights.
    """
    if not model or i < 50:
        return None
    m = model.get(asset.lower()) or model.get("btc")
    if not m or "weights" not in m:
        return None
    closes = [c[C] for c in candles]
    highs = [c[H] for c in candles]
    lows = [c[L] for c in candles]
    vols = [c[V] for c in candles]
    if i < 12 or i >= len(closes):
        return None
    atr = ind.atr(highs, lows, closes, 14)
    rsi14 = ind.rsi(closes, 14)
    ema_f = ind.ema(closes, 12)
    ema_s = ind.ema(closes, 26)
    v_sma = ind.sma(vols, 20)
    v_std = ind.rolling_std(vols, 20, ddof=0)
    h50 = ind.sma(highs, 50)
    l50 = ind.sma(lows, 50)
    if any(arr[i] is None for arr in (atr, rsi14, ema_f, ema_s, v_sma, v_std, h50, l50)):
        return None
    if closes[i] <= 0 or v_sma[i] <= 0 or v_std[i] <= 0 or ema_s[i] == 0:
        return None
    feats = [
        (closes[i] / closes[i - 1] - 1) * 100,
        (closes[i] / closes[i - 3] - 1) * 100,
        (closes[i] / closes[i - 6] - 1) * 100,
        (closes[i] / closes[i - 12] - 1) * 100,
        (rsi14[i] - 50) / 50,
        atr[i] / closes[i] * 100,
        (ema_f[i] - ema_s[i]) / ema_s[i] * 100,
        (vols[i] - v_sma[i]) / v_std[i],
        math.sin(2 * math.pi * datetime.fromtimestamp(candles[i][0], tz=timezone.utc).hour / 24),
        math.cos(2 * math.pi * datetime.fromtimestamp(candles[i][0], tz=timezone.utc).hour / 24),
        (closes[i] - h50[i]) / closes[i] * 100,
        (closes[i] - l50[i]) / closes[i] * 100,
    ]
    means, stds, weights = m.get("means"), m.get("stds"), m.get("weights")
    bias = m.get("bias", 0.0)
    if not all(isinstance(v, list) and len(v) >= len(feats) for v in (means, stds, weights)):
        return None
    if any(stds[j] == 0 for j in range(len(feats))):
        return None
    z = bias + sum(weights[j] * (feats[j] - means[j]) / stds[j] for j in range(len(feats)))
    if z > 30:
        return 1.0
    if z < -30:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


__all__ = [
    "vol_bucket", "rsi_bucket", "session_bucket", "strategy_bucket", "laplace",
    "build_snapshot", "predict", "update", "apply_trained_model",
]
