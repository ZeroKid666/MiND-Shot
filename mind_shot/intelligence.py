"""
Decision intelligence — the Trade Verdict score plus the analytics that feed the
dashboard (period R, streak heatmap, weekly trend, BTC/ETH correlation, per-strategy
hit stats, distance-to-trigger). Verdict scoring is preserved verbatim from v1.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .strategies import Strategy


# ── Trade verdict (unchanged scoring) ───────────────────────────────────────
def compute_trade_verdict(
    asset: str,
    ml_conf: Optional[float],
    whale_signal: Optional[str],
    funding: Optional[float],
    vol_regime: Optional[float],
    session_hr: Optional[int],
    trained_ml_prob: Optional[float] = None,
) -> Dict[str, Any]:
    score = 50
    reasons: List[str] = []

    if ml_conf is not None:
        if ml_conf >= 0.65:
            score += 15; reasons.append(f"🧠 Bayesian ML {ml_conf*100:.0f}% (strong)")
        elif ml_conf >= 0.55:
            score += 8; reasons.append(f"🧠 Bayesian ML {ml_conf*100:.0f}% (moderate)")
        elif ml_conf >= 0.45:
            reasons.append(f"🧠 Bayesian ML {ml_conf*100:.0f}% (neutral)")
        elif ml_conf >= 0.35:
            score -= 8; reasons.append(f"🧠 Bayesian ML {ml_conf*100:.0f}% (weak)")
        else:
            score -= 15; reasons.append(f"🧠 Bayesian ML {ml_conf*100:.0f}% (poor)")

    if trained_ml_prob is not None:
        if trained_ml_prob >= 0.62:
            score += 10; reasons.append(f"📊 Trained ML {trained_ml_prob*100:.0f}% (bullish)")
        elif trained_ml_prob <= 0.38:
            score -= 10; reasons.append(f"📊 Trained ML {trained_ml_prob*100:.0f}% (bearish)")

    if whale_signal == "strong_accum":
        score += 12; reasons.append("🐋 Whales accumulating strongly")
    elif whale_signal == "accum":
        score += 6; reasons.append("🐋 Whales accumulating")
    elif whale_signal == "strong_distrib":
        score -= 12; reasons.append("🐋 Whales distributing heavily")
    elif whale_signal == "distrib":
        score -= 6; reasons.append("🐋 Whales distributing")

    if funding is not None:
        if abs(funding) > 0.10:
            score -= 6; reasons.append(f"⚠ Funding {funding:+.3f}% (overextended)")
        elif abs(funding) > 0.05:
            score -= 3; reasons.append(f"⚠ Funding {funding:+.3f}% (elevated)")

    if vol_regime is not None:
        if vol_regime > 1.4:
            score += 3; reasons.append("⚡ Vol expansion")
        elif vol_regime < 0.6:
            score -= 3; reasons.append("🧊 Vol compression (chop risk)")

    if session_hr is not None:
        if 13 <= session_hr < 21:
            score += 3; reasons.append("🌎 NY session active")
        elif 7 <= session_hr < 13:
            score += 2; reasons.append("🇬🇧 London session active")
        elif 0 <= session_hr < 7:
            score -= 2; reasons.append("🌏 Asia session (lower volume)")

    score = max(0, min(100, score))
    if score >= 75:
        action, label = "strong", "✅ STRONG SETUP"
    elif score >= 60:
        action, label = "good", "✓ Good setup"
    elif score >= 45:
        action, label = "mixed", "~ Mixed signals — caution"
    elif score >= 30:
        action, label = "weak", "⚠ Weak setup — consider passing"
    else:
        action, label = "avoid", "✗ AVOID"
    return {"score": score, "action": action, "label": label, "reasons": reasons}


# ── period / streak analytics ────────────────────────────────────────────────
def update_period_stats(daily: Dict[str, float], ts: int, pnl_r: float) -> None:
    day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    daily[day] = daily.get(day, 0.0) + pnl_r


def aggregate_periods(daily: Dict[str, float]) -> Dict[str, float]:
    now = datetime.now(tz=timezone.utc)
    today = daily.get(now.strftime("%Y-%m-%d"), 0.0)
    week = sum(daily.get((now - timedelta(days=i)).strftime("%Y-%m-%d"), 0.0) for i in range(7))
    return {"today": round(today, 3), "week": round(week, 3), "all_time": round(sum(daily.values()), 3)}


def update_heatmap(heatmap: List[List[List[int]]], ts: int, won: bool) -> None:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    heatmap[dt.weekday()][dt.hour][0 if won else 1] += 1


def compute_weekly_summary(global_state: Dict[str, Any]) -> Dict[str, Any]:
    daily = global_state["daily_r"]
    now = datetime.now(tz=timezone.utc)
    this_week = sum(daily.get((now - timedelta(days=i)).strftime("%Y-%m-%d"), 0.0) for i in range(7))
    prior_week = sum(daily.get((now - timedelta(days=i)).strftime("%Y-%m-%d"), 0.0) for i in range(7, 14))
    delta = this_week - prior_week
    trend = "flat" if abs(delta) < 0.5 else ("improving" if delta > 0 else "declining")
    return {"this_week_r": round(this_week, 2), "prior_week_r": round(prior_week, 2),
            "delta_r": round(delta, 2), "trend": trend}


def compute_correlation(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    btc = next((r["price_24h"] for r in results if r["asset"] == "BTC" and r.get("price_24h")), [])
    eth = next((r["price_24h"] for r in results if r["asset"] == "ETH" and r.get("price_24h")), [])
    if len(btc) < 10 or len(eth) < 10:
        return out
    n = min(len(btc), len(eth))
    b, e = btc[-n:], eth[-n:]
    b_ret = [b[i + 1] / b[i] - 1 for i in range(n - 1) if b[i]]
    e_ret = [e[i + 1] / e[i] - 1 for i in range(n - 1) if e[i]]
    if not b_ret or not e_ret or len(b_ret) != len(e_ret):
        return out
    bm, em = sum(b_ret) / len(b_ret), sum(e_ret) / len(e_ret)
    cov = sum((b_ret[i] - bm) * (e_ret[i] - em) for i in range(len(b_ret))) / len(b_ret)
    bv = (sum((x - bm) ** 2 for x in b_ret) / len(b_ret)) ** 0.5
    ev = (sum((x - em) ** 2 for x in e_ret) / len(e_ret)) ** 0.5
    if bv * ev > 0:
        out["btc_eth"] = round(cov / (bv * ev), 3)
    btc_chg = (b[-1] / b[0] - 1) * 100 if b[0] else 0
    eth_chg = (e[-1] / e[0] - 1) * 100 if e[0] else 0
    out["btc_24h_pct"] = round(btc_chg, 2)
    out["eth_24h_pct"] = round(eth_chg, 2)
    out["lead_lag"] = ("BTC leads" if abs(btc_chg) > abs(eth_chg) * 1.15
                       else "ETH leads" if abs(eth_chg) > abs(btc_chg) * 1.15 else "in sync")
    return out


def compute_strategy_stats(journal: List[Dict[str, Any]], strategy_ids: List[str]) -> Dict[str, Any]:
    """Per-strategy realised performance from the trade journal."""
    by: Dict[str, Dict[str, Any]] = {
        sid: {"total": 0, "wins": 0, "tp": 0, "sl": 0, "exit": 0, "sum_r": 0.0} for sid in strategy_ids
    }
    for e in journal:
        sid = e.get("strategy")
        if sid not in by:
            by[sid] = {"total": 0, "wins": 0, "tp": 0, "sl": 0, "exit": 0, "sum_r": 0.0}
        row = by[sid]
        row["total"] += 1
        row["wins"] += 1 if e.get("won") else 0
        row[e.get("kind", "exit")] = row.get(e.get("kind", "exit"), 0) + 1
        row["sum_r"] += e.get("pnl_r", 0.0)
    out: Dict[str, Any] = {}
    for sid, row in by.items():
        t = row["total"]
        out[sid] = {
            "total": t,
            "wins": row["wins"],
            "win_rate": round(row["wins"] / t * 100, 1) if t else None,
            "avg_r": round(row["sum_r"] / t, 3) if t else None,
            "tp": row["tp"], "sl": row["sl"], "exit": row["exit"],
        }
    return out


def distance_to_signal(strategy: Strategy, series: Dict[str, List[Optional[float]]], i: int) -> Dict[str, Any]:
    """How far the strategy's signal sits from its long/short trigger right now."""
    val = series[strategy.source][i]
    adx_v = series["adx"][i]
    return {
        "source": strategy.source,
        "value": round(val, 4) if val is not None else None,
        "long_at": strategy.long_below,
        "short_at": strategy.short_above,
        "adx": round(adx_v, 1) if adx_v is not None else None,
        "adx_ok": (adx_v is not None and adx_v < strategy.adx_max),
    }


__all__ = [
    "compute_trade_verdict", "update_period_stats", "aggregate_periods", "update_heatmap",
    "compute_weekly_summary", "compute_correlation", "compute_strategy_stats", "distance_to_signal",
]
