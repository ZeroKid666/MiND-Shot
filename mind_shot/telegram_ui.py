"""Owner-chat menu polled by the existing scheduled engine; no public signup."""
import json
import logging
import time
import urllib.request
from datetime import datetime, timezone
from . import config, paper
from .strategies import STRATEGY_BY_ID

log = logging.getLogger(__name__)
KEYBOARD = {'keyboard': [['Crypto → ETH → 4h', 'Crypto → BTC → 4h'], ['Статистика', 'Помощь']], 'resize_keyboard': True}


def api(method, body):
    req = urllib.request.Request('https://api.telegram.org/bot'+config.TG_TOKEN+'/'+method,
                                 data=json.dumps(body).encode(), headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=10) as response:
        data=json.load(response)
    if not data.get('ok'): raise RuntimeError('Telegram API rejected request')
    return data['result']


def render(text, state):
    gs=state.get('__global',{})
    if text in ('/start','/menu','Помощь','/help'):
        return ('MiND-Shot · Crypto\nВыбери ETH или BTC, таймфрейм 4h.\n'
                'Кнопка показывает сохранённые активные сигналы, а не создаёт новый вход.\n'
                'Ответ приходит при следующем запуске проверки; возможна задержка в несколько минут.\n'
                'Статистика — собственные paper-наблюдения. Оценки ML пока не подтверждены.\n'
                'Автоматические уведомления ETH и BTC продолжают приходить независимо от выбора.')
    if text in ('Статистика','/stats'):
        r=paper.report(gs)
        net=r['sampled_net_r_sum']
        return (f"Paper-статистика\nЗаписей: {r['signals']} (прежних: {r['legacy']})\n"
                f"Закрыто по наблюдаемым ценам: {r['sampled_closed']}\n"
                f"Сумма net R: {net:.3f}\n" if net is not None else
                f"Paper-статистика\nЗаписей: {r['signals']} (прежних: {r['legacy']})\nЗакрыто по наблюдаемым ценам: {r['sampled_closed']}\nNet R: пока нет данных\n") + 'Это симуляция с издержками, не доходность счёта. Funding не учтён. Вероятности ML не валидированы.'
    asset = {'Crypto → ETH → 4h':'ETH','Crypto → BTC → 4h':'BTC','/eth':'ETH','/btc':'BTC'}.get(text)
    if not asset: return 'Выбери инструмент кнопкой ниже или отправь /start.'
    stamp=gs.get('last_poll_health',{}).get('at')
    checked=datetime.fromtimestamp(stamp,timezone.utc).strftime('%d.%m %H:%M UTC') if stamp else 'неизвестно'
    lines=[f'Crypto → {asset} → 4h',f'Последняя проверка: {checked}']
    if not stamp or time.time()-stamp>1800 or gs.get('last_poll_health',{}).get('errors'):
        lines.append('Данные могут быть устаревшими или неполными.')
    count=0
    for sid,node in state.items():
        if not isinstance(node,dict): continue
        t=node.get('active_trade')
        if not t or t.get('asset')!=asset or t.get('tf')!='4h': continue
        count+=1
        strat=STRATEGY_BY_ID.get(sid)
        p=t.get('entry_ml_probability')
        risk=abs(t['entry']-t['init_sl']); tp=t.get('tp')
        rr=abs(tp-t['entry'])/risk if tp is not None and risk else None
        lines.extend(['',strat.name if strat else sid,t['side'].upper(),
            f"Исходный вход: {t['entry']:.2f}",f"Stop Loss: {t['sl']:.2f}",
            f'Take Profit: {tp:.2f}' if tp is not None else 'Выход: динамический, по стратегии',
            f'Risk/Reward: 1:{rr:.2f}' if rr is not None else 'Risk/Reward: не фиксирован',
            f'ML при входе: {p:.0%} — не валидирована' if p is not None else 'ML при входе: нет сохранённой оценки',
            strat.description if strat else '', 'Это ранее выданный активный сигнал, не рекомендация нового входа.'])
    if not count: lines.append('Активных сигналов сейчас нет.')
    return '\n'.join(lines)[:3900]


def poll(state, persist):
    if not config.TG_TOKEN or not config.TG_CHAT_ID: return
    gs=state.setdefault('__global',{}); ui=gs.setdefault('telegram_ui',{})
    try:
        updates=api('getUpdates',{'offset':ui.get('offset',0),'limit':20,'timeout':0,'allowed_updates':['message']})
        for update in updates:
            message=update.get('message',{})
            allowed=str(message.get('chat',{}).get('id'))==str(config.TG_CHAT_ID)
            if allowed and isinstance(message.get('text'),str):
                # Never persist user messages, names or chat IDs into the public repo.
                reply=render(message['text'].strip(),state)
                api('sendMessage',{'chat_id':config.TG_CHAT_ID,'text':reply,'reply_markup':KEYBOARD})
            ui['offset']=update['update_id']+1
            persist()
        ui['last_ok_at']=int(time.time());ui.pop('error',None)
    except Exception:
        # Exception strings from urllib may contain the secret bot URL.
        ui['error']='Telegram menu request failed; retry next poll'
        log.warning('Telegram menu unavailable; check token, chat ID or existing webhook')
    persist()
