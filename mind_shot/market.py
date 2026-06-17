"""
Market data — Binance USD-M perpetual futures klines (pure standard library).

This is the same source the strategies were backtested on, so live signals match
the research. All network calls go through :func:`_get_json`, which retries with
exponential backoff and never raises on transient failures unless the caller asks.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

from .models import Candle

log = logging.getLogger("mind_shot.market")

BINANCE_FAPI = "https://fapi.binance.com"
SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
_USER_AGENT = "MiND-Shot/2.0 (+https://github.com/aashir-athar/MiND-Shot)"
_MAX_LIMIT = 1500  # Binance hard cap per klines request


def _get_json(url: str, timeout: float = 20.0, retries: int = 4):
    """GET ``url`` and parse JSON, retrying transient errors with backoff."""
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as err:
            last_err = err
            sleep_s = min(8.0, 1.5 * (2 ** attempt))
            log.warning("GET failed (attempt %d/%d): %s — retrying in %.1fs", attempt + 1, retries, err, sleep_s)
            if attempt < retries - 1:
                time.sleep(sleep_s)
    raise RuntimeError(f"request failed after {retries} attempts: {url}") from last_err


def _to_candle(row: list) -> Candle:
    # Binance kline row: [openTime_ms, open, high, low, close, volume, closeTime_ms, ...]
    return (
        int(row[0]) // 1000,        # open_time in SECONDS (matches engine convention)
        float(row[1]),
        float(row[2]),
        float(row[3]),
        float(row[4]),
        float(row[5]),
    )


def fetch_klines(asset: str, interval: str, limit: int = 500) -> List[Candle]:
    """Fetch the most recent ``limit`` closed+forming klines for ``asset``.

    Returns oldest→newest. The final element is the still-forming candle.
    """
    if asset not in SYMBOLS:
        raise ValueError(f"unknown asset {asset!r}")
    symbol = SYMBOLS[asset]
    q = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": min(limit, _MAX_LIMIT)})
    rows = _get_json(f"{BINANCE_FAPI}/fapi/v1/klines?{q}")
    return [_to_candle(r) for r in rows]


def fetch_klines_since(asset: str, interval: str, start_ms: int) -> List[Candle]:
    """Fetch every kline from ``start_ms`` (epoch ms) to now, paginating as needed.

    Used by the backtest; deduplicates by open time and returns oldest→newest.
    """
    if asset not in SYMBOLS:
        raise ValueError(f"unknown asset {asset!r}")
    symbol = SYMBOLS[asset]
    rows: dict[int, list] = {}
    cursor = start_ms
    while True:
        q = urllib.parse.urlencode(
            {"symbol": symbol, "interval": interval, "startTime": cursor, "limit": _MAX_LIMIT}
        )
        batch = _get_json(f"{BINANCE_FAPI}/fapi/v1/klines?{q}")
        if not batch:
            break
        for r in batch:
            rows[int(r[0])] = r
        if len(batch) < _MAX_LIMIT:
            break
        cursor = int(batch[-1][0]) + 1
        time.sleep(0.2)  # be polite to the public endpoint
    return [_to_candle(rows[k]) for k in sorted(rows)]


__all__ = ["fetch_klines", "fetch_klines_since", "SYMBOLS", "BINANCE_FAPI"]
