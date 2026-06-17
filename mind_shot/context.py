"""
Macro market context — Fear & Greed, BTC/ETH dominance, 24h tickers, funding.

All sources are free and keyless. Every lookup degrades gracefully to ``None`` so
a single API hiccup never breaks a poll. Output schema is unchanged from v1.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Dict, Optional

log = logging.getLogger("mind_shot.context")
_UA = {"User-Agent": "Mozilla/5.0"}


def _get(url: str, timeout: float = 10.0) -> Optional[Any]:
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as err:  # noqa: BLE001 — context is best-effort by design
        log.debug("context fetch failed for %s: %s", url, err)
        return None


def fetch_market_context() -> Dict[str, Any]:
    """One-shot fetch of macro context. Keys mirror the v1 engine exactly."""
    ctx: Dict[str, Any] = {}

    fng = _get("https://api.alternative.me/fng/?limit=1")
    if isinstance(fng, dict) and isinstance(fng.get("data"), list) and fng["data"]:
        d0 = fng["data"][0]
        ctx["fear_greed"] = {
            "value": int(d0.get("value", 0)),
            "classification": d0.get("value_classification", "—"),
        }
    else:
        ctx["fear_greed"] = None

    glob = _get("https://api.coingecko.com/api/v3/global")
    if isinstance(glob, dict) and isinstance(glob.get("data"), dict):
        d = glob["data"]
        ctx["btc_dominance"] = round(d.get("market_cap_percentage", {}).get("btc", 0), 2)
        ctx["eth_dominance"] = round(d.get("market_cap_percentage", {}).get("eth", 0), 2)
        ctx["mcap_change_24h"] = round(d.get("market_cap_change_percentage_24h_usd", 0), 2)
    else:
        ctx["btc_dominance"] = ctx["eth_dominance"] = ctx["mcap_change_24h"] = None

    tick = _get("https://api.kraken.com/0/public/Ticker?pair=XBTUSDT,ETHUSDT")
    tickers: Dict[str, Any] = {}
    if isinstance(tick, dict) and isinstance(tick.get("result"), dict):
        for k, v in tick["result"].items():
            try:
                price = float(v["c"][0]) if "c" in v else None
                open24 = float(v["o"]) if "o" in v else None
                chg = ((price - open24) / open24 * 100) if (price and open24) else None
                sym = "BTC" if "XBT" in k else "ETH"
                tickers[sym] = {
                    "price": price,
                    "change_24h": round(chg, 2) if chg is not None else None,
                    "high_24h": float(v["h"][1]) if "h" in v else None,
                    "low_24h": float(v["l"][1]) if "l" in v else None,
                    "vol_24h": float(v["v"][1]) if "v" in v else None,
                }
            except (KeyError, ValueError, IndexError):
                continue
    ctx["tickers"] = tickers

    for asset, sym in (("btc", "BTCUSDT"), ("eth", "ETHUSDT")):
        d = _get(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sym}")
        ctx[f"{asset}_funding"] = round(float(d.get("lastFundingRate", 0)) * 100, 4) if isinstance(d, dict) else None

    return ctx


__all__ = ["fetch_market_context"]
