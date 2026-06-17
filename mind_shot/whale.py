"""
Whale-flow detection from free Binance Futures public endpoints.

Aggregates top-trader long/short ratios (by account and by position), open-interest
change, and taker buy/sell pressure into a single per-asset signal
(``strong_accum`` … ``strong_distrib``). Output schema is unchanged from v1.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional

log = logging.getLogger("mind_shot.whale")
_FAPI = "https://fapi.binance.com"
_UA = {"User-Agent": "Mozilla/5.0"}
_ASSETS = (("BTC", "BTCUSDT"), ("ETH", "ETHUSDT"))


def _get(url: str, timeout: float = 10.0) -> Optional[Any]:
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as err:  # noqa: BLE001 — best-effort enrichment
        log.debug("whale fetch failed for %s: %s", url, err)
        return None


def _classify(a: Dict[str, Any]) -> str:
    score = 0
    pos = a.get("top_trader_ls_position", 1)
    if pos > 1.5:
        score += 2
    elif pos > 1.2:
        score += 1
    elif pos < 0.7:
        score -= 2
    elif pos < 0.85:
        score -= 1
    chg = a.get("top_trader_ls_position_chg", 0)
    if chg > 0.1:
        score += 1
    elif chg < -0.1:
        score -= 1
    oi = a.get("oi_24h_change_pct", 0)
    if oi > 5:
        score += 1
    elif oi < -5:
        score -= 1
    taker = a.get("taker_buy_sell", 1)
    if taker > 1.15:
        score += 1
    elif taker < 0.87:
        score -= 1
    a["_score"] = score
    if score >= 3:
        return "strong_accum"
    if score >= 1:
        return "accum"
    if score <= -3:
        return "strong_distrib"
    if score <= -1:
        return "distrib"
    return "neutral"


def fetch_whale_flow() -> Dict[str, Any]:
    out: Dict[str, Any] = {"BTC": {}, "ETH": {}, "whale_alerts": [], "net_signal": {}}

    for asset, sym in _ASSETS:
        a: Dict[str, Any] = {}
        d = _get(f"{_FAPI}/futures/data/topLongShortAccountRatio?symbol={sym}&period=1h&limit=2")
        if isinstance(d, list) and d:
            a["top_trader_ls_account"] = round(float(d[-1].get("longShortRatio", 0)), 3)
            if len(d) >= 2:
                a["top_trader_ls_account_chg"] = round(
                    float(d[-1].get("longShortRatio", 0)) - float(d[-2].get("longShortRatio", 0)), 3
                )
        d = _get(f"{_FAPI}/futures/data/topLongShortPositionRatio?symbol={sym}&period=1h&limit=2")
        if isinstance(d, list) and d:
            a["top_trader_ls_position"] = round(float(d[-1].get("longShortRatio", 0)), 3)
            if len(d) >= 2:
                a["top_trader_ls_position_chg"] = round(
                    float(d[-1].get("longShortRatio", 0)) - float(d[-2].get("longShortRatio", 0)), 3
                )
        d = _get(f"{_FAPI}/futures/data/openInterestHist?symbol={sym}&period=1h&limit=24")
        if isinstance(d, list) and len(d) >= 2:
            latest = float(d[-1].get("sumOpenInterest", 0))
            prior = float(d[0].get("sumOpenInterest", 0))
            a["oi_24h_change_pct"] = round((latest - prior) / prior * 100, 2) if prior > 0 else 0
            a["oi_now"] = round(latest, 0)
        d = _get(f"{_FAPI}/futures/data/takerlongshortRatio?symbol={sym}&period=1h&limit=1")
        if isinstance(d, list) and d:
            a["taker_buy_sell"] = round(float(d[-1].get("buySellRatio", 0)), 3)

        out[asset] = a
        out["net_signal"][asset] = _classify(a)

    start = int(datetime.now(tz=timezone.utc).timestamp()) - 600
    d = _get(f"https://api.whale-alert.io/v1/transactions?api_key=PUBLIC&min_value=500000&start={start}", timeout=8)
    if isinstance(d, dict) and isinstance(d.get("transactions"), list):
        out["whale_alerts"] = [
            {
                "symbol": tx.get("symbol", "").upper(),
                "amount_usd": int(tx.get("amount_usd", 0)),
                "from_owner": tx.get("from", {}).get("owner_type", "unknown"),
                "to_owner": tx.get("to", {}).get("owner_type", "unknown"),
                "ts": tx.get("timestamp", 0),
            }
            for tx in (d.get("transactions", [])[:5])
        ]

    return out


__all__ = ["fetch_whale_flow"]
