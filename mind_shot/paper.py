"""Versioned theoretical paper ledger. Costs are scenarios, not exchange quotes."""
import copy
import math
import os
import time


def cost_assumptions():
    result = {}
    for key, env, default in [('fee_bps', 'PAPER_FEE_BPS', '5'), ('slippage_bps', 'PAPER_SLIPPAGE_BPS', '2')]:
        value = float(os.environ.get(env, default))
        if not math.isfinite(value) or not 0 <= value < 10000:
            raise ValueError(f'{env} must be finite and between 0 and 10000')
        result[key] = value
    result['funding_included'] = False
    result['source'] = 'configured_scenario'
    return result


def trade_id(trade):
    return f'{trade.strategy_id}:{trade.opened_bar}:{trade.side}'


def record_open(gs, trade, delivery_ok=None, legacy=False):
    ledger = gs.setdefault('paper_ledger_v1', {})
    key = trade_id(trade)
    if key not in ledger:
        ledger[key] = {
            'id': key, 'status': 'open', 'recorded_at': int(time.time()),
            'legacy_import': legacy, 'entry': copy.deepcopy(trade.to_dict()),
            'cost_assumptions': None if legacy else cost_assumptions(),
            'entry_delivery_ok': delivery_ok,
            'fill_model': 'theoretical_candle_open_not_alert_execution',
        }
    return ledger[key]


def net_result(trade, exit_price, assumptions):
    fee = assumptions['fee_bps'] / 10000
    slip = assumptions['slippage_bps'] / 10000
    sign = 1 if trade.side == 'long' else -1
    entry_fill = trade.entry * (1 + sign * slip)
    exit_fill = exit_price * (1 - sign * slip)
    gross = sign * (exit_price - trade.entry)
    fees = fee * (entry_fill + exit_fill)
    net = sign * (exit_fill - entry_fill) - fees
    risk = trade.risk_per_unit
    return {'gross_per_unit': gross, 'net_per_unit': net, 'fees_per_unit': fees,
            'slippage_per_unit': gross - sign * (exit_fill - entry_fill),
            'entry_fill': entry_fill, 'exit_fill': exit_fill,
            'net_r': net / risk if risk > 0 else None, 'net_won': net > 0}


def record_close(gs, trade, info, delivery_ok=None):
    row = record_open(gs, trade, legacy=True)
    row.update(status='closed', close_detected_at=int(time.time()),
               outcome=copy.deepcopy(info), exit_delivery_ok=delivery_ok)
    assumptions = row['cost_assumptions']
    row['net_result'] = net_result(trade, info['exit_price'], assumptions) if assumptions else None
