"""Typed core domain models shared across the engine."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class Side(str, Enum):
    """Trade direction. ``str`` mixin keeps it JSON-friendly and comparable to
    the legacy ``'long'`` / ``'short'`` string literals used elsewhere."""

    LONG = "long"
    SHORT = "short"

    @property
    def sign(self) -> int:
        return 1 if self is Side.LONG else -1

    @property
    def opposite(self) -> "Side":
        return Side.SHORT if self is Side.LONG else Side.LONG


class ExitStyle(str, Enum):
    """How a strategy closes a position."""

    BRACKET = "bracket"   # fixed take-profit + stop, both in ATR units
    REVERT = "revert"     # exit when the signal reverts to its mean; hard ATR stop only


# A candle is kept as a lightweight tuple for zero-copy interop with the engine's
# data layer: (open_time_s, open, high, low, close, volume).
Candle = Tuple[int, float, float, float, float, float]

# Column indices into a Candle tuple (named for readability).
T, O, H, L, C, V = 0, 1, 2, 3, 4, 5


@dataclass(frozen=True)
class Bracket:
    """A computed stop / target pair for a concrete entry."""

    stop: float
    take_profit: float | None


__all__ = ["Side", "ExitStyle", "Candle", "Bracket", "T", "O", "H", "L", "C", "V"]
