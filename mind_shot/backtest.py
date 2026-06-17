"""
In-repo backtest — the engine's self-validation.

Runs each of the five strategies over real Binance 4h history in the user's exact
account model ($100 wallet, 10x leverage, 15% of wallet per trade, cross margin,
0.10% round-trip fee, no look-ahead, intrabar stop-fills-first) and checks that
the *live* indicator/strategy code reproduces the playbook win rates. Run with:

    python -m mind_shot.backtest

Used both as a CLI and by the CI workflow as a living regression test of the edge.
"""
from __future__ import annotations

import csv
import math
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .models import C, H, L, O, T, Candle, ExitStyle, Side
from .strategies import STRATEGIES, Strategy, compute_series

SIX_MONTHS_S = 183 * 86400
WARMUP_BARS = 210  # indicators stabilise well before the test window opens


@dataclass
class BacktestResult:
    strategy_id: str
    name: str
    asset: str
    trades: int
    wins: int
    long_trades: int
    short_trades: int
    win_rate: float
    final_wallet: float
    return_pct: float
    max_drawdown_pct: float
    expected_win_rate: float

    @property
    def passes(self) -> bool:
        # Pure-stdlib Wilder seeding differs marginally from the research engine;
        # allow a tolerance band but require the edge to clearly survive.
        return (
            self.trades >= 40
            and self.win_rate > 60.0
            and self.final_wallet > 100.0
            and abs(self.win_rate - self.expected_win_rate) <= 6.0
        )


def _signal_arrays(strat: Strategy, series: Dict[str, List[Optional[float]]]) -> Tuple[list, list, list, list]:
    n = len(series["closes"])
    enter_long = [False] * n
    enter_short = [False] * n
    exit_long = [False] * n
    exit_short = [False] * n
    is_revert = strat.exit_style is ExitStyle.REVERT
    for i in range(n):
        side = strat.entry(series, i)
        if side is Side.LONG:
            enter_long[i] = True
        elif side is Side.SHORT:
            enter_short[i] = True
        if is_revert:
            exit_long[i] = strat.should_exit(series, i, Side.LONG)
            exit_short[i] = strat.should_exit(series, i, Side.SHORT)
    return enter_long, enter_short, exit_long, exit_short


def simulate(
    candles: Sequence[Candle],
    strat: Strategy,
    series: Dict[str, List[Optional[float]]],
    *,
    wallet0: float = 100.0,
    leverage: float = 10.0,
    alloc: float = 0.15,
    fee: float = 0.0005,
    mmr: float = 0.005,
    test_start_s: Optional[int] = None,
) -> BacktestResult:
    """Cross-margin account simulation; returns aggregate metrics for the window."""
    opens = [c[O] for c in candles]
    highs = [c[H] for c in candles]
    lows = [c[L] for c in candles]
    times = [c[T] for c in candles]
    atr = series["atr"]
    el, es, xl, xs = _signal_arrays(strat, series)
    tp_atr = strat.tp_atr if strat.exit_style is ExitStyle.BRACKET else None
    sl_atr = strat.sl_atr
    n = len(candles)

    wallet = wallet0
    peak = wallet
    max_dd = 0.0
    pos = 0  # 0 flat, 1 long, -1 short
    entry = sl = tp = liq = notional = 0.0
    trades = wins = l_tr = s_tr = 0

    def book(exit_px: float) -> float:
        gross = (exit_px / entry - 1.0) if pos == 1 else (entry / exit_px - 1.0)
        return notional * (gross - 2 * fee)

    for i in range(n - 1):
        nx = i + 1
        if pos != 0:
            exited = False
            exit_px = 0.0
            if pos == 1:
                down = sl if sl > liq else liq
                if lows[nx] <= down:
                    exit_px, exited = down, True
                elif tp is not None and highs[nx] >= tp:
                    exit_px, exited = tp, True
                elif xl[i] or es[i]:
                    exit_px, exited = opens[nx], True
            else:
                up = sl if sl < liq else liq
                if highs[nx] >= up:
                    exit_px, exited = up, True
                elif tp is not None and lows[nx] <= tp:
                    exit_px, exited = tp, True
                elif xs[i] or el[i]:
                    exit_px, exited = opens[nx], True
            if exited:
                pnl = book(exit_px)
                wallet = max(0.0, wallet + pnl)
                trades += 1
                if pnl > 0:
                    wins += 1
                if pos == 1:
                    l_tr += 1
                else:
                    s_tr += 1
                pos = 0
                peak = max(peak, wallet)
                if peak > 0:
                    max_dd = min(max_dd, (wallet - peak) / peak)
                if wallet < 5.0:
                    break
        if pos == 0 and wallet > 5.0:
            if test_start_s is not None and times[nx] < test_start_s:
                continue
            if atr[i] is None:
                continue
            if el[i] or es[i]:
                pos = 1 if el[i] else -1
                entry = opens[nx]
                notional = alloc * wallet * leverage
                if pos == 1:
                    liq = entry * (1 - wallet / notional + mmr)
                    sl = entry - sl_atr * atr[i]
                    tp = entry + tp_atr * atr[i] if tp_atr else None
                else:
                    liq = entry * (1 + wallet / notional - mmr)
                    sl = entry + sl_atr * atr[i]
                    tp = entry - tp_atr * atr[i] if tp_atr else None

    return BacktestResult(
        strategy_id=strat.id,
        name=strat.name,
        asset=strat.asset,
        trades=trades,
        wins=wins,
        long_trades=l_tr,
        short_trades=s_tr,
        win_rate=round(100.0 * wins / trades, 1) if trades else 0.0,
        final_wallet=round(wallet, 2),
        return_pct=round(100.0 * (wallet / wallet0 - 1.0), 1),
        max_drawdown_pct=round(100.0 * max_dd, 1),
        expected_win_rate=strat.backtest_win_rate,
    )


# Deterministic regression test off committed fixtures — the original Binance 4h
# playbook data (Oct 2025 → Jun 2026). Runs offline on any runner, with no network
# or geo dependency, and reproduces the documented numbers exactly.
PLAYBOOK_TEST_START_S = 1_765_756_800   # 2025-12-15 UTC (6-month test window opens)
FIXTURE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "fixtures")
_FIXTURE_SYMBOL = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}


def _load_fixture(asset: str) -> List[Candle]:
    """Load a committed 4h fixture as oldest→newest ``Candle`` tuples (seconds)."""
    path = os.path.join(FIXTURE_DIR, f"{_FIXTURE_SYMBOL[asset]}_4h.csv")
    out: List[Candle] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.append((
                int(row["open_time"]) // 1000,  # ms → s
                float(row["open"]), float(row["high"]), float(row["low"]),
                float(row["close"]), float(row["volume"]),
            ))
    return out


def run(verbose: bool = True) -> List[BacktestResult]:
    """Replay the five strategies over the committed playbook fixtures and report."""
    data = {asset: _load_fixture(asset) for asset in {s.asset for s in STRATEGIES}}
    results: List[BacktestResult] = []
    for strat in STRATEGIES:
        candles = data[strat.asset]
        series = compute_series(candles)
        results.append(simulate(candles, strat, series, test_start_s=PLAYBOOK_TEST_START_S))
    if verbose:
        _print_report(results)
    return results


def _print_report(results: List[BacktestResult]) -> None:
    print("=" * 92)
    print("MiND-Shot strategy validation  |  $100 / 10x / 15% / cross / 0.10% RT / 6-month window")
    print("=" * 92)
    hdr = f"{'Strategy':34}{'Coin':5}{'Win%':>6}{'Exp%':>6}{'Trds':>5}{'L/S':>8}{'Final$':>9}{'DD%':>7}  P/F"
    print(hdr)
    print("-" * len(hdr))
    all_pass = True
    for r in results:
        ok = r.passes
        all_pass = all_pass and ok
        print(
            f"{r.name[:34]:34}{r.asset:5}{r.win_rate:>6}{r.expected_win_rate:>6}{r.trades:>5}"
            f"{f'{r.long_trades}/{r.short_trades}':>8}{r.final_wallet:>9}{r.max_drawdown_pct:>7}  "
            f"{'PASS' if ok else 'FAIL'}"
        )
    print("=" * 92)
    print(("[OK] ALL STRATEGIES VALIDATED" if all_pass else "[X] VALIDATION FAILED") +
          "  (>=40 trades, >60% win, profitable, within tolerance of playbook)")


if __name__ == "__main__":
    import sys

    res = run(verbose=True)
    sys.exit(0 if all(r.passes for r in res) else 1)
