import unittest
from unittest.mock import patch
from mind_shot import paper
from mind_shot.trading import Trade


def trade(side='long'):
    return Trade('test','ETH','4h',side,100,90,90,120,'bracket',1,0)

class LedgerTests(unittest.TestCase):
    def test_long_and_short_costs(self):
        a={'fee_bps':5,'slippage_bps':2}
        for side, price in [('long',110),('short',90)]:
            r=paper.net_result(trade(side),price,a)
            self.assertLess(r['net_per_unit'],10)
            self.assertAlmostEqual(r['net_per_unit'],10-r['fees_per_unit']-r['slippage_per_unit'])
            self.assertTrue(r['net_won'])
        self.assertFalse(paper.net_result(trade(),100,a)['net_won'])

    def test_frozen_assumptions_and_snapshot(self):
        gs={}; t=trade(); t.ml_snap={'p':0.54}
        with patch.dict('os.environ',{'PAPER_FEE_BPS':'5','PAPER_SLIPPAGE_BPS':'2'}):
            row=paper.record_open(gs,t,False)
        t.ml_snap['p']=0.9
        with patch.dict('os.environ',{'PAPER_FEE_BPS':'50'}):
            paper.record_close(gs,t,{'exit_price':110,'exit_bar':2},True)
        self.assertEqual(row['cost_assumptions']['fee_bps'],5)
        self.assertEqual(row['entry']['ml_snap']['p'],0.54)
        self.assertFalse(row['entry_delivery_ok'])
        self.assertTrue(row['exit_delivery_ok'])
        self.assertEqual(len(gs['paper_ledger_v1']),1)

    def test_legacy_unknown_costs_and_delivery(self):
        gs={};t=trade()
        paper.record_close(gs,t,{'exit_price':110})
        row=next(iter(gs['paper_ledger_v1'].values()))
        self.assertTrue(row['legacy_import'])
        self.assertIsNone(row['net_result'])
        self.assertIsNone(row['entry_delivery_ok'])

    def test_no_500_record_truncation(self):
        gs={}
        for i in range(501):
            t=trade();t.opened_bar=i
            paper.record_open(gs,t)
        self.assertEqual(len(gs['paper_ledger_v1']),501)

    def test_invalid_costs(self):
        for value in ['nan','-1','inf','10000']:
            with patch.dict('os.environ',{'PAPER_FEE_BPS':value}):
                with self.assertRaises(ValueError): paper.cost_assumptions()
