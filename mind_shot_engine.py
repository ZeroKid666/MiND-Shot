#!/usr/bin/env python3
"""
MiND-Shot — entrypoint.

The engine now lives in the ``mind_shot`` package (a clean, typed, tested core).
Its signal brain runs the five backtested mean-reversion strategies; every other
feature — the self-learning ML ensemble, whale-flow, market context, Trade Verdict,
risk controls, SL/TP management, and Telegram/webhook delivery — is preserved.

This file stays as the stable entrypoint so the GitHub Actions workflows and the
Electron host (`python mind_shot_engine.py`) keep working unchanged.
"""
from mind_shot.engine import main

if __name__ == "__main__":
    main()
