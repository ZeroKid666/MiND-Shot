"""
The five backtested mean-reversion strategies — the engine's only signal source.

Each was selected from a 1,620-config sweep across 30 strategy families and is the
single set that clears, simultaneously, on BTC/ETH 4h: both directions, >=40 trades
per 6 months, >60% win rate, profitable, and surviving an out-of-sample window.
The shared edge is "fade an extreme back toward the mean, ONLY while the market is
ranging (ADX < 25)". See ``Top5-Strategies-Detailed-Playbook.md``.

Signals are computed on a CLOSED bar; the engine acts on the next bar's open. No
indicator here ever reads a future bar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from . import indicators as ind
from .models import C, H, L, V, Candle, ExitStyle, Side

Num = Optional[float]
Series = Dict[str, List[Num]]


@dataclass(frozen=True)
class Strategy:
    """A self-contained, parameterised mean-reversion rule set."""

    id: str
    name: str
    asset: str            # "BTC" | "ETH"
    timeframe: str        # "4h"
    source: str           # key into the indicator series driving entries
    long_below: float     # enter long when source < this
    short_above: float    # enter short when source > this
    adx_max: float        # only trade when ADX(14) < this (range filter)
    exit_style: ExitStyle
    sl_atr: float         # stop distance in ATR units
    tp_atr: Optional[float] = None   # take-profit distance (bracket only)
    revert_level: float = 0.0        # signal level that closes a revert trade
    mean_price_key: Optional[str] = None  # series key giving the live exit price (revert only)
    backtest_win_rate: float = 0.0   # informational (from the playbook)
    description: str = ""

    # ── signal logic ──────────────────────────────────────────────────────────
    def entry(self, series: Series, i: int) -> Optional[Side]:
        """Return the side to open at bar ``i``, or ``None``. Range-gated by ADX."""
        adx_i = series["adx"][i]
        if adx_i is None or adx_i >= self.adx_max:
            return None
        v = series[self.source][i]
        if v is None:
            return None
        if v < self.long_below:
            return Side.LONG
        if v > self.short_above:
            return Side.SHORT
        return None

    def should_exit(self, series: Series, i: int, side: Side) -> bool:
        """For REVERT strategies: has the signal returned to its mean at bar ``i``?

        BRACKET strategies always return ``False`` here — they exit purely on
        their take-profit / stop levels.
        """
        if self.exit_style is not ExitStyle.BRACKET:
            v = series[self.source][i]
            if v is None:
                return False
            if side is Side.LONG:
                return v >= self.revert_level
            return v <= self.revert_level
        return False

    @property
    def pair(self) -> tuple[str, str]:
        return (self.asset, self.timeframe)


def compute_series(candles: Sequence[Candle]) -> Series:
    """Compute every indicator the five strategies need, once, from raw candles."""
    highs = [c[H] for c in candles]
    lows = [c[L] for c in candles]
    closes = [c[C] for c in candles]
    vols = [c[V] for c in candles]
    return {
        "highs": highs,
        "lows": lows,
        "closes": closes,
        "vols": vols,
        "atr": ind.atr(highs, lows, closes, 14),
        "adx": ind.adx(highs, lows, closes, 14),
        "rsi2": ind.rsi(closes, 2),
        "rsi14": ind.rsi(closes, 14),
        "stoch_k": ind.stochastic_k(highs, lows, closes, 14),
        "zscore": ind.zscore(closes, 20),
        "vwap_z": ind.vwap_deviation_z(highs, lows, closes, vols, 20),
        # mean-reversion exit anchors (live target price for REVERT strategies)
        "vwap": ind.rolling_vwap(highs, lows, closes, vols, 20),
        "sma20": ind.sma(closes, 20),
    }


# ── The registry ───────────────────────────────────────────────────────────────
STRATEGIES: List[Strategy] = [
    Strategy(
        id="vwap_bracket_eth",
        name="VWAP-Reversion (bracket)",
        asset="ETH", timeframe="4h", source="vwap_z",
        long_below=-2.0, short_above=2.0, adx_max=25.0,
        exit_style=ExitStyle.BRACKET, sl_atr=1.5, tp_atr=0.75,
        backtest_win_rate=78.4,
        description="Fade price ~2σ from rolling VWAP(20) back, TP 0.75×ATR / SL 1.5×ATR.",
    ),
    Strategy(
        id="rsi2_bracket_eth",
        name="RSI-2 Reversion (bracket)",
        asset="ETH", timeframe="4h", source="rsi2",
        long_below=10.0, short_above=90.0, adx_max=25.0,
        exit_style=ExitStyle.BRACKET, sl_atr=1.5, tp_atr=0.75,
        backtest_win_rate=72.3,
        description="Fade RSI(2) <10 / >90 exhaustion, TP 0.75×ATR / SL 1.5×ATR.",
    ),
    Strategy(
        id="vwap_revert_eth",
        name="VWAP-Reversion (exit-at-VWAP)",
        asset="ETH", timeframe="4h", source="vwap_z",
        long_below=-2.0, short_above=2.0, adx_max=25.0,
        exit_style=ExitStyle.REVERT, sl_atr=2.0, tp_atr=None, revert_level=0.0,
        mean_price_key="vwap",
        backtest_win_rate=70.0,
        description="Fade ~2σ from VWAP(20); ride back to VWAP; hard SL 2×ATR.",
    ),
    Strategy(
        id="stoch_bracket_eth",
        name="Stochastic Reversion (bracket)",
        asset="ETH", timeframe="4h", source="stoch_k",
        long_below=20.0, short_above=80.0, adx_max=25.0,
        exit_style=ExitStyle.BRACKET, sl_atr=2.0, tp_atr=0.75,
        backtest_win_rate=75.9,
        description="Fade Stochastic %K(14) <20 / >80, TP 0.75×ATR / SL 2×ATR.",
    ),
    Strategy(
        id="zscore_revert_btc",
        name="Z-Score Reversion (exit-at-mean)",
        asset="BTC", timeframe="4h", source="zscore",
        long_below=-1.5, short_above=1.5, adx_max=25.0,
        exit_style=ExitStyle.REVERT, sl_atr=3.0, tp_atr=None, revert_level=0.0,
        mean_price_key="sma20",
        backtest_win_rate=65.1,
        description="Fade ±1.5σ from SMA(20) on BTC; ride back to mean; hard SL 3×ATR.",
    ),
]

STRATEGY_BY_ID: Dict[str, Strategy] = {s.id: s for s in STRATEGIES}


def strategies_for(asset: str, timeframe: str) -> List[Strategy]:
    """All strategies registered for a given (asset, timeframe) pair."""
    return [s for s in STRATEGIES if s.asset == asset and s.timeframe == timeframe]


def active_pairs() -> List[tuple[str, str]]:
    """The distinct (asset, timeframe) pairs the strategy set needs data for."""
    seen: List[tuple[str, str]] = []
    for s in STRATEGIES:
        if s.pair not in seen:
            seen.append(s.pair)
    return seen


__all__ = [
    "Strategy",
    "STRATEGIES",
    "STRATEGY_BY_ID",
    "compute_series",
    "strategies_for",
    "active_pairs",
]
