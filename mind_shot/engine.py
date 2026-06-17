"""
Engine orchestration — one poll cycle.

Fetches 4h data once per (asset, timeframe) pair, runs every strategy registered
for that pair, manages open trades, fires alerts, folds outcomes back into the
self-learning ML, and emits the full dashboard blob — the same schema as v1 so the
Electron host and any webhook consumers keep working unchanged.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import config, context, intelligence, market, ml, notifier, whale
from .models import C, T
from .state import (
    GLOBAL_KEY,
    ensure_global,
    ensure_strategy,
    load_state,
    load_trained_model,
    save_state,
)
from .strategies import STRATEGIES, active_pairs, compute_series
from .trading import Trade, manage_trade, open_trade

log = logging.getLogger("mind_shot.engine")

TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
WARMUP_BARS = 60


def _risk_block(strategy, state: Dict[str, Any], gs: Dict[str, Any]) -> Optional[str]:
    """Return a human reason to suppress a fresh entry, or ``None`` to allow it."""
    today_r = intelligence.aggregate_periods(gs["daily_r"])["today"]
    if today_r <= gs.get("daily_loss_limit_r", -3.0):
        return f"daily loss limit ({today_r:.2f}R)"
    open_count = sum(
        1 for k, v in state.items()
        if k != GLOBAL_KEY and isinstance(v, dict) and v.get("active_trade")
    )
    if open_count >= gs.get("max_concurrent_trades", 4):
        return f"{open_count} trades open (max {gs.get('max_concurrent_trades', 4)})"
    last_sl = gs.get("sl_cooldowns", {}).get(strategy.id, 0)
    if last_sl > 0:
        cd_min = gs.get("cooldown_minutes_after_sl", 240)
        elapsed = (datetime.now(tz=timezone.utc).timestamp() - last_sl) / 60
        if elapsed < cd_min:
            return f"cool-down after SL ({int(cd_min - elapsed)}min left)"
    return None


def _record_close(gs: Dict[str, Any], trade: Trade, info: Dict[str, Any]) -> None:
    won = info["won"]
    if won:
        gs["cur_win_streak"] += 1
        gs["cur_loss_streak"] = 0
        gs["max_win_streak"] = max(gs["max_win_streak"], gs["cur_win_streak"])
    else:
        gs["cur_loss_streak"] += 1
        gs["cur_win_streak"] = 0
        gs["max_loss_streak"] = max(gs["max_loss_streak"], gs["cur_loss_streak"])
        gs.setdefault("sl_cooldowns", {})[trade.strategy_id] = datetime.now(tz=timezone.utc).timestamp()
    intelligence.update_period_stats(gs["daily_r"], trade.opened_bar, info["pnl_r"])
    intelligence.update_heatmap(gs["heatmap"], trade.opened_bar, won)
    gs["journal"].append({
        "strategy": trade.strategy_id, "asset": trade.asset, "tf": trade.tf, "side": trade.side,
        "entry": trade.entry, "exit": info["exit_price"], "kind": info["kind"],
        "pnl_r": info["pnl_r"], "won": won, "opened_at": trade.opened_bar, "closed_at": trade.last_bar,
    })
    if len(gs["journal"]) > config.JOURNAL_CAP:
        gs["journal"] = gs["journal"][-config.JOURNAL_CAP:]


def process_strategy(strategy, candles, series, state, gs, results, ml_summary) -> None:
    st = ensure_strategy(state, strategy.id)
    n = len(candles)
    last_close = candles[-1][C]
    sample = candles[-48:] if n >= 48 else candles
    res: Dict[str, Any] = {
        "strategy": strategy.id, "strategy_name": strategy.name,
        "asset": strategy.asset, "tf": strategy.timeframe,
        "events": [], "new_entry": None, "active_trade": None, "trade_closed": False,
        "distance_to_signal": None, "candle_close_at": candles[-1][T] * 1000 + TF_MIN[strategy.timeframe] * 60 * 1000,
        "last_close": last_close, "price_24h": [round(c[C], 6) for c in sample],
    }
    confirm_idx = n - 2
    if confirm_idx >= 0:
        res["distance_to_signal"] = intelligence.distance_to_signal(strategy, series, confirm_idx)

    # ── manage an open trade ──
    if st["active_trade"]:
        trade = Trade.from_dict(st["active_trade"])
        events, closed, info = manage_trade(trade, strategy, candles, series)
        for ev in events:
            res["events"].append(ev)
            payload, text = notifier.event_alert(ev, trade, strategy)
            notifier.deliver(payload, text)
        if closed and info:
            ml.update(st["ml"], trade.ml_snap, info["won"], info["gross_profit"], info["gross_loss"])
            _record_close(gs, trade, info)
            st["active_trade"] = None
            res["trade_closed"] = True
            res["closed_outcome"] = {"won": info["won"], "pnl_r": info["pnl_r"], "kind": info["kind"]}
        else:
            trade.update_live(last_close, config.LEVERAGE, candles[-1][T])
            st["active_trade"] = trade.to_dict()
            res["active_trade"] = st["active_trade"]

    # ── look for a fresh entry ──
    if st["active_trade"] is None and confirm_idx >= WARMUP_BARS and candles[confirm_idx][T] > st["last_signal_bar"]:
        side = strategy.entry(series, confirm_idx)
        if side is not None:
            snap = ml.build_snapshot(series, confirm_idx, strategy.id, candles[confirm_idx][T])
            ml_conf = ml.predict(st["ml"], snap)
            blocked = _risk_block(strategy, state, gs)
            ml_trades = st["ml"].get("total_trades", 0)
            if blocked:
                res["blocked_by"] = blocked
                log.info("[%s] %s blocked: %s", strategy.id, side.value, blocked)
            elif config.ML_GATING_ENABLED and ml_trades >= config.ML_MIN_TRADES and ml_conf < config.ML_MIN_CONF:
                res["blocked_by"] = f"ML conf {ml_conf*100:.1f}% < {config.ML_MIN_CONF*100:.0f}%"
                log.info("[%s] %s blocked by ML (%.1f%%)", strategy.id, side.value, ml_conf * 100)
            else:
                trade = open_trade(strategy, candles, confirm_idx, series, snap)
                if trade is not None:
                    st["active_trade"] = trade.to_dict()
                    res["active_trade"] = st["active_trade"]
                    res["new_entry"] = {"side": trade.side, "entry": trade.entry, "ml_conf": round(ml_conf, 4)}
                    payload, text = notifier.entry_alert(trade, strategy, ml_conf)
                    notifier.deliver(payload, text)
                    log.info("[%s] NEW %s @ %s  ml=%.1f%%", strategy.id, trade.side.upper(),
                             notifier.fmt(trade.entry), ml_conf * 100)
        st["last_signal_bar"] = candles[confirm_idx][T]

    mlst = st["ml"]
    if mlst.get("total_trades", 0) > 0:
        ml_summary[strategy.id] = {
            "total_trades": mlst["total_trades"], "wins": mlst["wins"],
            "wr": mlst["wins"] / mlst["total_trades"],
            "conf": ml.laplace(mlst["wins"], mlst["total_trades"] - mlst["wins"]),
        }
    results.append(res)


def run_one_poll() -> Dict[str, Any]:
    state = load_state()
    gs = ensure_global(state)
    trained_model = load_trained_model()

    pair_candles: Dict[tuple, List] = {}
    pair_series: Dict[tuple, Dict] = {}
    for pair in active_pairs():
        try:
            candles = market.fetch_klines(pair[0], pair[1], limit=720)
            pair_candles[pair] = candles
            pair_series[pair] = compute_series(candles)
        except Exception as err:  # noqa: BLE001
            log.error("fetch %s %s failed: %s", pair[0], pair[1], err)

    results: List[Dict[str, Any]] = []
    ml_summary: Dict[str, Any] = {}
    for strategy in STRATEGIES:
        candles = pair_candles.get(strategy.pair)
        series = pair_series.get(strategy.pair)
        if not candles or not series:
            results.append({"strategy": strategy.id, "asset": strategy.asset, "tf": strategy.timeframe,
                            "error": "data unavailable", "events": [], "price_24h": []})
            continue
        try:
            process_strategy(strategy, candles, series, state, gs, results, ml_summary)
        except Exception as err:  # noqa: BLE001 — one bad strategy must not sink the poll
            log.exception("strategy %s errored: %s", strategy.id, err)

    # Persist trade-lifecycle state NOW — it must never depend on the best-effort
    # enrichment below succeeding (a Binance hiccup must not roll back real trades).
    save_state(state)

    try:
        market_ctx = context.fetch_market_context()
    except Exception as err:  # noqa: BLE001
        log.warning("market context unavailable: %s", err)
        market_ctx = {}
    try:
        whale_ctx = whale.fetch_whale_flow()
    except Exception as err:  # noqa: BLE001
        log.warning("whale flow unavailable: %s", err)
        whale_ctx = {"BTC": {}, "ETH": {}, "whale_alerts": [], "net_signal": {}}

    verdicts: Dict[str, Any] = {}
    hour = datetime.now(tz=timezone.utc).hour
    for r in results:
        if r.get("error"):
            continue
        asset = r["asset"]
        candles = pair_candles.get((asset, r["tf"]))
        ml_conf = (ml_summary.get(r["strategy"]) or {}).get("conf")
        whale_sig = (whale_ctx.get("net_signal") or {}).get(asset)
        funding = market_ctx.get(f"{asset.lower()}_funding")
        trained_prob = ml.apply_trained_model(trained_model, candles, len(candles) - 2, asset) if candles else None
        verdicts[r["strategy"]] = intelligence.compute_trade_verdict(
            asset, ml_conf, whale_sig, funding, None, hour, trained_prob
        )

    weekly = intelligence.compute_weekly_summary(gs)
    correlation = intelligence.compute_correlation(results)
    strat_stats = intelligence.compute_strategy_stats(gs["journal"], [s.id for s in STRATEGIES])

    blob = _build_blob(results, ml_summary, market_ctx, whale_ctx, strat_stats, verdicts,
                       weekly, correlation, trained_model, gs)
    if config.OUTPUT_JSON:
        sys.stdout.write("<<<MINDSHOT_JSON>>>")
        sys.stdout.write(json.dumps(blob))
        sys.stdout.write("<<</MINDSHOT_JSON>>>\n")
        sys.stdout.flush()
    return blob


def _build_blob(results, ml_summary, market_ctx, whale_ctx, strat_stats, verdicts,
                weekly, correlation, trained_model, gs) -> Dict[str, Any]:
    return {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "polls": results,
        "ml_summary": ml_summary,
        "market": market_ctx,
        "whale": whale_ctx,
        "strategy_stats": strat_stats,
        "tp_accuracy": strat_stats,  # kept for dashboard back-compat
        "verdicts": verdicts,
        "weekly_summary": weekly,
        "correlation": correlation,
        "trained_model_summary": {
            "btc_oos_wr": (trained_model or {}).get("btc_oos_wr"),
            "eth_oos_wr": (trained_model or {}).get("eth_oos_wr"),
            "trained_at": (trained_model or {}).get("trained_at"),
        } if trained_model else None,
        "risk_controls": {
            "daily_loss_limit_r": gs.get("daily_loss_limit_r"),
            "max_concurrent_trades": gs.get("max_concurrent_trades"),
            "cooldown_minutes_after_sl": gs.get("cooldown_minutes_after_sl"),
            "funding_pause_threshold": gs.get("funding_pause_threshold"),
            "risk_per_trade_pct": gs.get("risk_per_trade_pct"),
            "paper_mode": gs.get("paper_mode"),
            "sl_cooldowns": gs.get("sl_cooldowns", {}),
        },
        "periods": intelligence.aggregate_periods(gs["daily_r"]),
        "streaks": {
            "cur_win": gs["cur_win_streak"], "cur_loss": gs["cur_loss_streak"],
            "max_win": gs["max_win_streak"], "max_loss": gs["max_loss_streak"],
        },
        "heatmap": gs["heatmap"],
        "daily_r": gs["daily_r"],
        "journal": gs["journal"][-30:],
        "account_size": gs.get("account_size", config.ACCOUNT_USD),
        "leverage": config.LEVERAGE,
        "strategies": [
            {"id": s.id, "name": s.name, "asset": s.asset, "tf": s.timeframe,
             "backtest_win_rate": s.backtest_win_rate, "description": s.description}
            for s in STRATEGIES
        ],
    }


def main() -> None:
    config.configure_logging()
    if config.TEST_ALERT:
        payload, text = notifier.heartbeat_alert()
        ok = notifier.deliver(payload, text)
        log.info("Test alert: %s (%s)", "delivered" if ok else "not delivered", config.delivery_label())
        return
    log.info("Delivery: %s", config.delivery_label())
    log.info("MiND-Shot Engine %s — %s", _version(), datetime.now(tz=timezone.utc).isoformat())
    log.info("Strategies: %d  ·  pairs: %s  ·  polls/run: %d  ·  interval: %ds",
             len(STRATEGIES), active_pairs(), config.POLLS_PER_RUN, config.POLL_INTERVAL_SEC)
    for poll_num in range(1, config.POLLS_PER_RUN + 1):
        log.info("── Poll %d/%d @ %s UTC ──", poll_num, config.POLLS_PER_RUN,
                 datetime.now(tz=timezone.utc).strftime("%H:%M:%S"))
        try:
            run_one_poll()
        except Exception as err:  # noqa: BLE001
            log.exception("poll error: %s", err)
        if poll_num < config.POLLS_PER_RUN:
            time.sleep(config.POLL_INTERVAL_SEC)
    log.info("Done.")


def _version() -> str:
    from . import __version__
    return __version__


__all__ = ["run_one_poll", "main", "process_strategy"]
