import unittest
from unittest.mock import patch
from mind_shot import telegram_ui as ui

class MenuTests(unittest.TestCase):
    def test_empty_and_stats(self):
        self.assertIn('Активных сигналов сейчас нет',ui.render('/eth',{}))
        self.assertIn('пока нет данных',ui.render('/stats',{}))
        self.assertIn('задержка',ui.render('/start',{}))

    def test_card_old_prediction_not_invented(self):
        s={'rsi2_bracket_eth':{'active_trade':{'asset':'ETH','tf':'4h','entry':100,'init_sl':110,'sl':110,'tp':95,'side':'short'}}}
        text=ui.render('/eth',s)
        self.assertIn('1:0.50',text)
        self.assertIn('нет сохранённой оценки',text)
        self.assertIn('не рекомендация нового входа',text)
        self.assertNotIn('SHORT',ui.render('/btc',s))

    @patch.object(ui.config,'TG_TOKEN','test')
    @patch.object(ui.config,'TG_CHAT_ID','7')
    def test_owner_only_no_private_data_saved(self):
        s={};updates=[{'update_id':1,'message':{'chat':{'id':8},'text':'private'}},{'update_id':2,'message':{'chat':{'id':7},'text':'/start'}}]
        with patch.object(ui,'api',side_effect=[updates,{}]) as api:
            ui.poll(s,lambda:None)
            self.assertEqual(api.call_count,2)
        self.assertEqual(s['__global']['telegram_ui']['offset'],3)
        self.assertNotIn('private',str(s))

    @patch.object(ui.config,'TG_TOKEN','test')
    @patch.object(ui.config,'TG_CHAT_ID','7')
    def test_failed_reply_retried(self):
        s={};u=[{'update_id':10,'message':{'chat':{'id':7},'text':'/start'}}]
        with patch.object(ui,'api',side_effect=[u,RuntimeError('secret')]):ui.poll(s,lambda:None)
        self.assertNotIn('offset',s['__global']['telegram_ui'])
        self.assertNotIn('secret',str(s))
