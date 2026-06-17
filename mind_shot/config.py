"""
Central configuration — environment, paths, logging, and tunable constants.

All runtime knobs are read from environment variables (set as GitHub Actions
secrets/vars, or by the Electron host) so the same code runs everywhere with no
edits. Nothing here has side effects beyond reading ``os.environ`` and creating
the state directory.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}


# ── Delivery ────────────────────────────────────────────────────────────────
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()
TG_TOKEN = os.environ.get("TG_TOKEN", "").strip()
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "").strip()

# ── Display / account ───────────────────────────────────────────────────────
LEVERAGE = _env_int("LEVERAGE", 10)
ACCOUNT_USD = _env_float("ACCOUNT_USD", 100.0)
ALLOC_PCT = _env_float("ALLOC_PCT", 15.0)          # % of wallet per trade (margin)

# ── Engine loop ─────────────────────────────────────────────────────────────
POLLS_PER_RUN = _env_int("POLLS_PER_RUN", 1)
POLL_INTERVAL_SEC = _env_int("POLL_INTERVAL_SEC", 60)
OUTPUT_JSON = _env_bool("OUTPUT_JSON", False)       # Electron reads stdout JSON

# ── ML gating (the Bayesian second opinion may veto a strategy signal) ──────
ML_MIN_TRADES = _env_int("ML_MIN_TRADES", 12)
ML_MIN_CONF = _env_float("ML_MIN_CONF", 0.40)
ML_PENALTY_SL = _env_int("ML_PENALTY_SL", 2)
ML_GATING_ENABLED = _env_bool("ML_GATING_ENABLED", True)

# ── Paths ───────────────────────────────────────────────────────────────────
PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent
# Support both the Electron layout (engine/ subfolder) and the repo root layout.
STATE_DIR = (REPO_DIR.parent / "state") if REPO_DIR.name == "engine" else (REPO_DIR / "state")
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = STATE_DIR / "state.json"
TRAINED_MODEL_FILE = STATE_DIR / "trained_model.json"

# ── Default risk controls (persisted into global state, editable there) ─────
DEFAULT_RISK = {
    "daily_loss_limit_r": -3.0,
    "max_concurrent_trades": 4,
    "cooldown_minutes_after_sl": 240,
    "funding_pause_threshold": 0.05,
    "risk_per_trade_pct": ALLOC_PCT,
    "paper_mode": False,
}

JOURNAL_CAP = 500


def configure_logging() -> None:
    """Force UTF-8 stdout/stderr and a clean log format. Safe to call repeatedly."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )


def delivery_label() -> str:
    if WEBHOOK_URL:
        return f"webhook ({WEBHOOK_URL[:48]}...)"
    if TG_TOKEN and TG_CHAT_ID:
        return f"Telegram bot direct (chat={TG_CHAT_ID})"
    return "DRY-RUN (no webhook / no Telegram)"


__all__ = [name for name in dir() if name.isupper()] + [
    "configure_logging",
    "delivery_label",
]
