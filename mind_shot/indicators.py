"""
Technical indicators — pure Python standard library (no numpy/pandas).

Every function takes plain ``list[float]`` series and returns a list of the same
length, with ``None`` for bars that lack enough history (the warm-up region).
Indices align 1:1 with the input candles, so ``out[i]`` is the indicator value
*as of the close of bar i* — never peeking at future bars.

Smoothing convention: RSI / ATR / ADX use Wilder's RMA implemented as an EWMA
with ``alpha = 1/length`` seeded at the first valid value. This matches the
``ewm(alpha=1/n, adjust=False)`` math used to produce the backtested results, so
the live engine and the backtest agree.
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

Num = Optional[float]


def rma(values: Sequence[Num], length: int) -> List[Num]:
    """Wilder's running moving average (EWMA, alpha = 1/length).

    ``None`` inputs carry the previous value forward (so gaps don't reset the
    average). Output is ``None`` until the first non-``None`` input seeds it.
    """
    if length <= 0:
        raise ValueError("length must be positive")
    out: List[Num] = [None] * len(values)
    alpha = 1.0 / length
    prev: Optional[float] = None
    for i, x in enumerate(values):
        if x is None:
            out[i] = prev
            continue
        prev = x if prev is None else prev + alpha * (x - prev)
        out[i] = prev
    return out


def sma(values: Sequence[Num], length: int) -> List[Num]:
    """Simple moving average over a trailing window of ``length`` bars."""
    if length <= 0:
        raise ValueError("length must be positive")
    n = len(values)
    out: List[Num] = [None] * n
    window_sum = 0.0
    count = 0
    from collections import deque

    win: deque = deque()
    for i, x in enumerate(values):
        if x is None:
            # A gap invalidates any window that would span it; reset.
            win.clear()
            window_sum = 0.0
            out[i] = None
            continue
        win.append(x)
        window_sum += x
        if len(win) > length:
            window_sum -= win.popleft()
        out[i] = window_sum / length if len(win) == length else None
    _ = count  # readability placeholder; not used
    return out


def rolling_std(values: Sequence[Num], length: int, ddof: int = 0) -> List[Num]:
    """Rolling standard deviation (population by default, ``ddof=0``)."""
    if length <= 0:
        raise ValueError("length must be positive")
    if length - ddof <= 0:
        raise ValueError("length must exceed ddof")
    from collections import deque

    n = len(values)
    out: List[Num] = [None] * n
    win: deque = deque()
    s = 0.0
    s2 = 0.0
    for i, x in enumerate(values):
        if x is None:
            win.clear()
            s = s2 = 0.0
            out[i] = None
            continue
        win.append(x)
        s += x
        s2 += x * x
        if len(win) > length:
            old = win.popleft()
            s -= old
            s2 -= old * old
        if len(win) == length:
            mean = s / length
            var = max(0.0, (s2 - length * mean * mean) / (length - ddof))
            out[i] = math.sqrt(var)
        else:
            out[i] = None
    return out


def zscore(values: Sequence[Num], length: int) -> List[Num]:
    """Z-score of ``values`` vs their own ``length``-bar mean and population std."""
    means = sma(values, length)
    stds = rolling_std(values, length, ddof=0)
    out: List[Num] = [None] * len(values)
    for i, x in enumerate(values):
        m, sd = means[i], stds[i]
        if x is None or m is None or sd is None:
            continue
        out[i] = (x - m) / (sd + 1e-12)
    return out


def rsi(closes: Sequence[Num], length: int = 14) -> List[Num]:
    """Wilder's Relative Strength Index."""
    n = len(closes)
    out: List[Num] = [None] * n
    if n < 2:
        return out
    gains: List[Num] = [None] * n
    losses: List[Num] = [None] * n
    for i in range(1, n):
        c, pc = closes[i], closes[i - 1]
        if c is None or pc is None:
            gains[i] = losses[i] = None
            continue
        d = c - pc
        gains[i] = d if d > 0 else 0.0
        losses[i] = -d if d < 0 else 0.0
    avg_gain = rma(gains, length)
    avg_loss = rma(losses, length)
    for i in range(n):
        ag, al = avg_gain[i], avg_loss[i]
        if ag is None or al is None:
            continue
        if al <= 0:
            out[i] = 100.0
        else:
            rs = ag / al
            out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def _true_range(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> List[Num]:
    n = len(closes)
    tr: List[Num] = [None] * n
    if n == 0:
        return tr
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    return tr


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], length: int = 14) -> List[Num]:
    """Wilder's Average True Range."""
    return rma(_true_range(highs, lows, closes), length)


def adx(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    length: int = 14,
) -> List[Num]:
    """Wilder's Average Directional Index (trend-strength, 0-100)."""
    n = len(closes)
    out: List[Num] = [None] * n
    if n < 2:
        return out
    plus_dm: List[Num] = [None] * n
    minus_dm: List[Num] = [None] * n
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm[i] = up if (up > down and up > 0) else 0.0
        minus_dm[i] = down if (down > up and down > 0) else 0.0
    tr = _true_range(highs, lows, closes)
    atr_w = rma(tr, length)
    pdm_w = rma(plus_dm, length)
    mdm_w = rma(minus_dm, length)
    dx: List[Num] = [None] * n
    for i in range(n):
        a, p, m = atr_w[i], pdm_w[i], mdm_w[i]
        if a is None or p is None or m is None or a <= 0:
            continue
        pdi = 100.0 * p / a
        mdi = 100.0 * m / a
        denom = pdi + mdi
        dx[i] = 100.0 * abs(pdi - mdi) / denom if denom > 0 else 0.0
    return rma(dx, length)


def stochastic_k(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    length: int = 14,
) -> List[Num]:
    """Stochastic %K over a trailing ``length``-bar high/low range."""
    from collections import deque

    n = len(closes)
    out: List[Num] = [None] * n
    hi_dq: deque = deque()  # indices, decreasing highs
    lo_dq: deque = deque()  # indices, increasing lows
    for i in range(n):
        while hi_dq and hi_dq[0] <= i - length:
            hi_dq.popleft()
        while lo_dq and lo_dq[0] <= i - length:
            lo_dq.popleft()
        while hi_dq and highs[hi_dq[-1]] <= highs[i]:
            hi_dq.pop()
        while lo_dq and lows[lo_dq[-1]] >= lows[i]:
            lo_dq.pop()
        hi_dq.append(i)
        lo_dq.append(i)
        if i >= length - 1:
            hh = highs[hi_dq[0]]
            ll = lows[lo_dq[0]]
            out[i] = 100.0 * (closes[i] - ll) / (hh - ll + 1e-12)
    return out


def rolling_vwap(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float],
    length: int = 20,
) -> List[Num]:
    """Rolling volume-weighted average price over ``length`` bars."""
    from collections import deque

    n = len(closes)
    out: List[Num] = [None] * n
    win: deque = deque()
    tpv_sum = 0.0
    vol_sum = 0.0
    for i in range(n):
        tp = (highs[i] + lows[i] + closes[i]) / 3.0
        v = volumes[i]
        win.append((tp * v, v))
        tpv_sum += tp * v
        vol_sum += v
        if len(win) > length:
            otpv, ov = win.popleft()
            tpv_sum -= otpv
            vol_sum -= ov
        if len(win) == length:
            out[i] = tpv_sum / vol_sum if vol_sum > 0 else closes[i]
    return out


def vwap_deviation_z(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float],
    length: int = 20,
) -> List[Num]:
    """How far price sits from rolling VWAP, in std-devs of close.

    ``z = (close - VWAP) / std(close, length)`` — the signal for the
    VWAP-reversion strategies.
    """
    vwap = rolling_vwap(highs, lows, closes, volumes, length)
    stds = rolling_std(closes, length, ddof=0)
    out: List[Num] = [None] * len(closes)
    for i in range(len(closes)):
        v, sd = vwap[i], stds[i]
        if v is None or sd is None:
            continue
        out[i] = (closes[i] - v) / (sd + 1e-12)
    return out


def ema(values: Sequence[Num], length: int) -> List[Num]:
    """Exponential moving average (alpha = 2/(length+1)), seeded at first value."""
    if length <= 0:
        raise ValueError("length must be positive")
    out: List[Num] = [None] * len(values)
    k = 2.0 / (length + 1)
    prev: Optional[float] = None
    for i, x in enumerate(values):
        if x is None:
            out[i] = prev
            continue
        prev = x if prev is None else x * k + prev * (1 - k)
        out[i] = prev
    return out


__all__ = [
    "rma",
    "sma",
    "rolling_std",
    "zscore",
    "rsi",
    "atr",
    "adx",
    "stochastic_k",
    "rolling_vwap",
    "vwap_deviation_z",
    "ema",
]
