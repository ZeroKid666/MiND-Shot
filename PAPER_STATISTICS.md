# Paper statistics

The engine keeps `__global.paper_ledger_v1`, `delivery_outbox`, `paper_report`
and `last_poll_health` in the existing atomically saved state.json. The workflow
already commits this file. No reset or retrospective reconstruction is performed.
Existing active trades are marked legacy; old closed journal rows are not presented
as newly collected evidence. Ledger entries are not truncated at 500 records.

Two distinct measurements are retained:

* Original strategy lifecycle: candle-open reference fills and original ML labels.
* `observed_execution`: sampled-price simulation starting at the first detection
  price. Pre-detection candle highs/lows are never used here. A crossed entry level
  causes a skip. Exits use the price observed on a later poll, including overshoot.
  This simulation continues even after the reference lifecycle closes.

Neither model represents an actual exchange order. Sampling can miss TP/SL touches
between polls. No funding, spread model, liquidity constraints or receipt-time fills
are available. Per-side scenario defaults: 5 basis points fee, 2 basis points
slippage. PAPER_FEE_BPS and PAPER_SLIPPAGE_BPS override these environment values;
GitHub repository variables require wiring into workflow env before they take effect.
Costs are frozen at entry. Existing records with unknown assumptions stay unknown.
Net R is relative to the observed entry-to-original-stop distance. Summed R is not
a portfolio return.

The Actions run summary contains paper counts, sampled net R, Brier score,
log loss and calibration bins. Predictions are evaluated only against the original
theoretical gross-win target; this does not prove profitability after costs.
No sample size automatically certifies probabilities. ML training remains on its
existing target; Telegram explicitly labels its estimate unvalidated.

Entry and exit notifications use stable event IDs and pending/sent/expired statuses.
Retries use backoff and expire after 24 hours. Pending entries are superseded when
the reference trade closes. Local state is saved before sending and after attempts.
GitHub durability occurs at the later state commit: a crash or failed push after
sending can duplicate a message. This is at-least-once delivery, not exactly-once.
Telegram API success does not prove that the user read the message.

Remaining infrastructure limit: the existing workflow reports success even after
exhausting state-push retries. Monitor its commit logs; local outbox persistence
cannot fix lost runner storage. A durable service/database is required before
commercial reliability claims or broad multi-user rollout.

Validation: `python3 -m unittest discover -s tests -q`.
