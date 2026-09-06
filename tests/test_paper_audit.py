import unittest
from mind_shot.trading import Trade, open_trade, manage_trade
from mind_shot.strategies import STRATEGY_BY_ID
from mind_shot.engine import _record_close
from mind_shot.state import empty_global_state

class PaperAudit(unittest.TestCase):
    def test_entry_candle_stop_and_archived_prediction(self):
        s = STRATEGY_BY_ID['vwap_bracket_eth']
        candles = [(0,100,100,100,100,1),(1,100,100,100,100,1),(2,100,100,100,100,1)]
        series = {'adx':[None,20,20], 'vwap_z':[None,-2.5,-2.5], 'atr':[None,10,10]}
        t = open_trade(s,candles,1,series,{'_pred':{'p':0.54}})
        t.entry_ml_probability = 0.54
        t.detected_at = 3
        t = Trade.from_dict(t.to_dict())
        candles[-1] = (2,100,108,84,90,1)
        events, closed, info = manage_trade(t,s,candles,{})
        self.assertTrue(closed)
        self.assertEqual(info['kind'],'sl')
        self.assertEqual(info['exit_bar'],2)
        gs = empty_global_state()
        _record_close(gs,t,info)
        row = gs['journal'][-1]
        self.assertEqual(row['closed_at'],2)
        self.assertEqual(row['entry_ml_probability'],0.54)
        self.assertEqual(row['initial_stop'],85)
        self.assertEqual(row['take_profit'],107.5)
        self.assertFalse(row['costs_included'])
        t.ml_snap.clear()
        self.assertEqual(row['ml_snapshot']['_pred']['p'],0.54)

    def test_legacy_trade_keeps_processing_cursor(self):
        d = dict(strategy_id='vwap_bracket_eth',asset='ETH',tf='4h',side='long',entry=100,init_sl=85,sl=85,tp=107.5,exit_style='bracket',opened_bar=0,last_bar=1)
        t = Trade.from_dict(d)
        self.assertEqual(t.last_bar,1)
        self.assertEqual(t.accounting_version,1)
        self.assertIsNone(t.entry_ml_probability)

    def test_forming_exit_uses_event_bar_not_cursor(self):
        t = Trade('vwap_bracket_eth','ETH','4h','long',100,85,85,107.5,'bracket',0,1)
        _,closed,info = manage_trade(t,STRATEGY_BY_ID[t.strategy_id],[(1,100,100,100,100,1),(2,100,101,84,90,1)],{})
        self.assertTrue(closed)
        self.assertEqual(t.last_bar,1)
        self.assertEqual(info['exit_bar'],2)
