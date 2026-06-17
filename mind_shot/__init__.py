"""
MiND-Shot — autonomous crypto trading signal engine.

This package houses the modular, senior-grade core. The signal brain runs the
five backtested mean-reversion strategies (see ``strategies.py``); every other
feature of the engine (ML ensemble, whale-flow, market context, verdict scoring,
risk controls, delivery) is preserved and built around them.

Pure Python standard library only — zero third-party dependencies — so the engine
keeps running for $0 on a public repo's GitHub Actions minutes.
"""
from __future__ import annotations

__version__ = "2.0.0"
__all__ = ["__version__"]
