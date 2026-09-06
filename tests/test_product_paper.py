import unittest
from unittest.mock import patch
from mind_shot import paper, delivery
from mind_shot.trading import Trade
from mind_shot.strategies import STRATEGY_BY_ID

class ProductPaper(unittest.TestCase):
    def setup_row(self):
        t=Trade('vwap_bracket_eth','ETH','4h','long',100,90,90,110,'bracket',0,0)
        t.entry_ml_probability=0.7
        gs={}; row=paper.record_open(gs,t)
        return gs,row,t

    def test_observed_uses_current_price_not_old_extrema(self):
        gs,row,t=self.setup_row();paper.observe_open(row,102,10)
        strat=STRATEGY_BY_ID[t.strategy_id]
        paper.observe_poll(gs,strat,[(0,100,120,80,103,1)],{},20)
        self.assertEqual(row['observed_execution']['status'],'open')
        paper.observe_poll(gs,strat,[(0,100,120,80,111,1)],{},30)
        ex=row['observed_execution']
        self.assertEqual(ex['entry'],102)
        self.assertEqual(ex['exit'],111)
        self.assertEqual(ex['status'],'closed')
        self.assertEqual(paper.report(gs)['sampled_closed'],1)

    def test_already_crossed_skipped(self):
        _,row,_=self.setup_row();paper.observe_open(row,111,10)
        self.assertEqual(row['observed_execution']['status'],'skipped')

    def test_report_calibration_target_and_legacy(self):
        gs,row,t=self.setup_row();paper.record_close(gs,t,{'exit_price':110,'won':True})
        result=paper.report(gs)
        self.assertAlmostEqual(result['calibration']['brier'],0.09)
        self.assertFalse(result['probabilities_validated'])
        row['legacy_import']=True
        self.assertEqual(paper.report(gs)['calibration']['n'],0)

    def test_retry_and_no_resend_after_success(self):
        gs,row,t=self.setup_row();key=paper.trade_id(t)+':entry'
        delivery.enqueue(gs,key,{'type':'entry'},'hello')
        item=gs['delivery_outbox'][key];item['created_at']=0
        with patch('mind_shot.delivery.notifier.deliver',side_effect=[False,True]) as send:
            writes=[]
            delivery.flush(gs,lambda:writes.append(1),now=1)
            delivery.flush(gs,lambda:None,now=2)
            self.assertEqual(send.call_count,1)
            delivery.flush(gs,lambda:None,now=200)
            delivery.flush(gs,lambda:None,now=300)
            self.assertEqual(send.call_count,2)
            self.assertTrue(row['entry_delivery_ok'])
            self.assertNotIn('text',item)
            self.assertGreaterEqual(len(writes),2)

    def test_expired_not_sent(self):
        gs={};delivery.enqueue(gs,'a:entry',{},'x');gs['delivery_outbox']['a:entry']['created_at']=0
        with patch('mind_shot.delivery.notifier.deliver') as send:
            delivery.flush(gs,lambda:None,now=90000)
            send.assert_not_called()
        self.assertEqual(gs['delivery_outbox']['a:entry']['status'],'expired')
