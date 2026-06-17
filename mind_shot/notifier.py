"""
Delivery — webhook (Make.com / n8n / Pipedream) or the direct Telegram Bot API,
plus the human-readable HTML alert formatting.

If ``WEBHOOK_URL`` is set it wins; otherwise a ``TG_TOKEN`` + ``TG_CHAT_ID`` pair
posts straight to Telegram. With neither, :func:`deliver` is a no-op (dry run),
so the engine runs end-to-end locally without any secrets.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, Tuple

from . import config
from .models import Side
from .strategies import Strategy
from .trading import Trade

log = logging.getLogger("mind_shot.notifier")

_TIMEOUT = 15.0


def deliver(payload: Dict[str, Any], fallback_text: str) -> bool:
    """Send ``payload`` to the configured channel. Never raises."""
    if config.WEBHOOK_URL:
        return _post_json(config.WEBHOOK_URL, payload)
    if config.TG_TOKEN and config.TG_CHAT_ID:
        url = f"https://api.telegram.org/bot{config.TG_TOKEN}/sendMessage"
        body = {
            "chat_id": config.TG_CHAT_ID,
            "text": fallback_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        return _post_json(url, body)
    log.debug("dry-run: %s", payload.get("type"))
    return False


def _post_json(url: str, body: Dict[str, Any]) -> bool:
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as err:
        log.warning("delivery failed: %s", err)
        return False


def fmt(price: float) -> str:
    return f"{price:,.2f}" if price >= 1000 else f"{price:,.4f}"


def entry_alert(trade: Trade, strategy: Strategy, ml_conf: float) -> Tuple[Dict[str, Any], str]:
    """Build the (payload, html_text) pair for a new entry."""
    lev = config.LEVERAGE
    is_long = trade.side == Side.LONG.value
    emoji = "🟢" if is_long else "🔴"
    side_t = "L O N G" if is_long else "S H O R T"

    if trade.tp is not None:
        target_line = f"🎯 <b>TP</b>     <code>{fmt(trade.tp)}</code>   ·  R:R {strategy.tp_atr:g}:{strategy.sl_atr:g}"
    else:
        anchor = "VWAP" if strategy.mean_price_key == "vwap" else "mean"
        tgt = fmt(trade.target) if trade.target else "—"
        target_line = f"🎯 <b>Target</b> <code>{tgt}</code>   ·  exit at {anchor} (dynamic)"

    text = (
        f"{emoji}━━━━━━━━━━━━━━━━━━━━━━{emoji}\n"
        f"      <b>MiND-Shot</b>\n"
        f"        <b>{side_t}</b>   ⚡<code>{lev}x</code>\n"
        f"{emoji}━━━━━━━━━━━━━━━━━━━━━━{emoji}\n\n"
        f"📊  <code>{trade.asset}/USD</code>   ⏱  <b>{trade.tf}</b>\n"
        f"🧩  <i>{strategy.name}</i>\n"
        f"🧠  ML Confidence  ·  <b>{ml_conf * 100:.1f}%</b>\n\n"
        f"▰▰▰▰  <b>POSITION</b>  ▰▰▰▰▰▰\n"
        f"📍 <b>Entry</b>   <code>{fmt(trade.entry)}</code>\n"
        f"🛡 <b>Stop</b>    <code>{fmt(trade.sl)}</code>   ·  {strategy.sl_atr:g}×ATR\n"
        f"{target_line}\n\n"
        f"<i>💡 {strategy.description}</i>"
    )
    payload = {
        "type": "entry",
        "side": trade.side.upper(),
        "asset": trade.asset,
        "tf": trade.tf,
        "strategy": strategy.id,
        "strategy_name": strategy.name,
        "preset": strategy.name,        # back-compat alias for v1 webhook mappings
        "ml_conf": round(ml_conf * 100, 1),
        "leverage": lev,
        "entry": trade.entry,
        "sl": trade.sl,
        "tp": trade.tp,
        "tp1": trade.tp,                # back-compat: single TP exposed as tp1
        "tp2": None, "tp3": None, "tp4": None,
        "target": trade.target,
        "text": text,
    }
    return payload, text


def event_alert(event: Dict[str, Any], trade: Trade, strategy: Strategy) -> Tuple[Dict[str, Any], str]:
    """Build the (payload, html_text) pair for a TP / SL / exit event."""
    lev = config.LEVERAGE
    kind = event["type"]
    price = event["price"]
    sign = 1 if trade.side == Side.LONG.value else -1
    pct = (price - trade.entry) / trade.entry * 100 * sign
    lev_pct = pct * lev
    emoji = "🛡" if kind == "sl" else ("🚀" if kind == "tp" else "🎯")
    label = {"sl": "STOP", "tp": "TAKE-PROFIT", "exit": "EXIT"}.get(kind, kind.upper())
    sign_str = "+" if lev_pct >= 0 else ""

    text = (
        f"{emoji}━━━━━━━━━━━━━━━━━━━━━{emoji}\n"
        f"     <b>{label} HIT</b>\n"
        f"     <b>{sign_str}{lev_pct:.2f}%</b>   @  ⚡<code>{lev}x</code>\n"
        f"{emoji}━━━━━━━━━━━━━━━━━━━━━{emoji}\n\n"
        f"📊  <code>{trade.asset}/USD</code>  ·  <b>{trade.tf}</b>\n"
        f"🧩  <i>{strategy.name}</i>\n"
        f"💰  Price:  <code>{fmt(price)}</code>"
    )
    payload = {
        "type": "event",
        "event": kind,
        "asset": trade.asset,
        "tf": trade.tf,
        "strategy": strategy.id,
        "side": trade.side.upper(),     # back-compat aliases for v1 webhook mappings
        "entry": trade.entry,
        "leverage": lev,
        "price": price,
        "pct": round(pct, 2),
        "pct_leveraged": round(lev_pct, 2),
        "text": text,
    }
    return payload, text


__all__ = ["deliver", "fmt", "entry_alert", "event_alert"]
