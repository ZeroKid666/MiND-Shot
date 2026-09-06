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


def observe_open(row, price, now):
    """Separate sampled-price simulation; never reuse pre-alert candle extrema."""
    t = row['entry']
    sign = 1 if t['side'] == 'long' else -1
    tp = t.get('tp')
    if sign * (price - t['sl']) <= 0 or (tp is not None and sign * (price - tp) >= 0):
        row['observed_execution'] = {'status': 'skipped', 'reason': 'level_already_crossed'}
        return
    row['observed_execution'] = {'status': 'open', 'entry': price, 'entry_at': now,
                                 'last_observed_at': now, 'model': 'sampled_price_v1'}


def observe_poll(gs, strategy, candles, series, now):
    from .trading import Trade
    from .models import Side
    price = candles[-1][4]
    for row in gs.get('paper_ledger_v1', {}).values():
        ex = row.get('observed_execution', {})
        if ex.get('status') != 'open' or row['entry']['strategy_id'] != strategy.id:
            continue
        t = row['entry']; sign = 1 if t['side'] == 'long' else -1
        ex['last_observed_at'] = now
        kind = None
        if sign * (price - t['sl']) <= 0:
            kind = 'sl_observed'
        elif t.get('tp') is not None and sign * (price - t['tp']) >= 0:
            kind = 'tp_observed'
        elif strategy.exit_style.value == 'revert' and strategy.should_exit(series, len(candles)-2, Side(t['side'])):
            kind = 'exit_observed'
        if kind:
            simulated = Trade.from_dict(t); simulated.entry = ex['entry']
            ex.update(status='closed', exit=price, exit_at=now, kind=kind,
                      result=net_result(simulated, price, row['cost_assumptions']))


def report(gs):
    rows = list(gs.get('paper_ledger_v1', {}).values())
    observed = [r for r in rows if r.get('observed_execution', {}).get('status') == 'closed']
    values = [r['observed_execution']['result']['net_r'] for r in observed]
    values = [v for v in values if v is not None]
    predictions = []
    for r in rows:
        p = r['entry'].get('entry_ml_probability')
        if r['status'] == 'closed' and not r['legacy_import'] and isinstance(p,(int,float)) and 0 <= p <= 1:
            predictions.append((p, bool(r['outcome']['won'])))
    n = len(predictions)
    metrics = {'n': n, 'target': 'theoretical_gross_win_not_net_execution',
               'brier': sum((p-int(y))**2 for p,y in predictions)/n if n else None,
               'log_loss': -sum(math.log(max(1e-12, p if y else 1-p)) for p,y in predictions)/n if n else None}
    metrics['bins'] = []
    for lo in range(0,100,10):
        bucket = [(p,y) for p,y in predictions if lo/100 <= p < (lo+10)/100 or (lo==90 and p==1)]
        if bucket:
            metrics['bins'].append({'lower':lo/100,'n':len(bucket),'mean_prediction':sum(p for p,y in bucket)/len(bucket),'win_rate':sum(y for p,y in bucket)/len(bucket)})
    return {'signals':len(rows),'legacy':sum(r['legacy_import'] for r in rows),
            'sampled_closed':len(observed), 'sampled_net_r_sum':sum(values) if values else None,
            'calibration':metrics, 'probabilities_validated':False,
            'limitations':['Sampled prices may miss intrapoll TP/SL touches.',
                            'No funding, order-book fills or Telegram receipt-time execution.',
                            'R sum is not portfolio return; costs are configured scenarios.']}
