"""Persistent delivery attempts. At-least-once: crash after send can duplicate."""
import time
from . import notifier


def enqueue(gs, key, payload, text):
    gs.setdefault('delivery_outbox', {}).setdefault(key, {
        'payload':payload, 'text':text + '\n<code>' + key + '</code>',
        'created_at':int(time.time()), 'attempts':0, 'status':'pending'})


def flush(gs, persist, now=None):
    now = int(time.time()) if now is None else now
    box = gs.setdefault('delivery_outbox', {})
    persist()
    for key,item in box.items():
        if item['status'] != 'pending': continue
        if now-item['created_at'] > 86400:
            item['status']='expired'; persist(); continue
        if now < item.get('next_attempt_at',0): continue
        item['attempts'] += 1
        ok = notifier.deliver(item['payload'],item['text'])
        item['last_attempt_at']=now
        item['next_attempt_at']=now+min(3600,60*2**min(item['attempts'],6))
        if ok:
            item['status']='sent'; item['sent_at']=now
            item.pop('payload',None); item.pop('text',None)
        row_id,phase=key.rsplit(':',1)
        row=gs.get('paper_ledger_v1',{}).get(row_id)
        if row: row[phase+'_delivery_ok']=ok
        persist()
