#!/usr/bin/env python3
"""
MiND-Shot Engine — Electron Edition
─────────────────────────────────────────────────────────────────
Runs one poll cycle, emits a structured JSON blob between
⌬JSON⌬ delimiters for the Electron main process to parse,
optionally fires a webhook (Make.com / Telegram), persists ML
state to disk between invocations.

Activated by Electron's setInterval — no internal sleep loop.
"""
import os, sys, json, urllib.request, urllib.error
from collections import deque
from pathlib import Path
from datetime import datetime, timezone

# ── Force UTF-8 stdout/stderr (Windows defaults to cp1252 which chokes on emoji/Unicode) ──
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass  # Python <3.7 or unusual environment — best-effort

# ── Delivery + leverage from env (Electron passes them in) ──
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '')
TG_TOKEN    = os.environ.get('TG_TOKEN', '')
TG_CHAT_ID  = os.environ.get('TG_CHAT_ID', '')
LEVERAGE    = int(os.environ.get('LEVERAGE', '10'))
OUTPUT_JSON = os.environ.get('OUTPUT_JSON', '0') == '1'

# State directory — handle both Electron layout (engine/ subfolder) and GitHub layout (root)
ENGINE_DIR = Path(__file__).resolve().parent
if ENGINE_DIR.name == 'engine':
    STATE_DIR = ENGINE_DIR.parent / 'state'      # Electron: mind_shot_app/state/
else:
    STATE_DIR = ENGINE_DIR / 'state'             # GitHub: mind_shot_github/state/
STATE_DIR.mkdir(exist_ok=True)
STATE_FILE = STATE_DIR / 'state.json'

# Active pairs — Electron sends them as JSON env var, else fall back to defaults
ACTIVE = None
try:
    raw = os.environ.get('ACTIVE_PAIRS')
    if raw:
        ACTIVE = [(p['asset'], p['tf']) for p in json.loads(raw)]
except Exception:
    pass
if not ACTIVE:
    ACTIVE = [('BTC','4h'),('ETH','4h'),('BTC','1h'),('ETH','1d')]

# Asset Presets — backtested-optimal configs
PRESETS = {
    ('BTC','4h'): {'mode':'advanced','profile':'balanced','tps':(0.7,1.4,2.4,3.6),'sl':1.0,'don':20,'atrLen':21,'fi':2,'volFilt':False,'oscByTrend':False},
    ('ETH','4h'): {'mode':'advanced','profile':'sharp',   'tps':(0.7,1.4,2.4,3.6),'sl':1.0,'don':20,'atrLen':21,'fi':2,'volFilt':False,'oscByTrend':True},
    ('BTC','1h'): {'mode':'oscillator','profile':'balanced','tps':(0.7,1.4,2.4,3.6),'sl':1.0,'don':20,'atrLen':14,'fi':0,'volFilt':False,'oscByTrend':True},
    ('ETH','1d'): {'mode':'advanced','profile':'sharp',   'tps':(1.5,3.0,5.0,7.5),'sl':2.0,'don':20,'atrLen':14,'fi':0,'volFilt':True, 'oscByTrend':False},
    ('BTC','15m'):{'mode':'advanced','profile':'sharp',   'tps':(0.5,1.0,1.7,2.5),'sl':0.7,'don':20,'atrLen':21,'fi':2,'volFilt':False,'oscByTrend':False},
    ('ETH','15m'):{'mode':'advanced','profile':'sharp',   'tps':(1.0,2.0,3.5,5.0),'sl':1.5,'don':14,'atrLen':21,'fi':1,'volFilt':False,'oscByTrend':False},
    ('BTC','30m'):{'mode':'channel','profile':'sharp',    'tps':(1.0,2.0,3.5,5.0),'sl':1.5,'don':14,'atrLen':21,'fi':2,'volFilt':False,'oscByTrend':False},
    ('ETH','30m'):{'mode':'advanced','profile':'sharp',   'tps':(0.7,1.4,2.4,3.6),'sl':1.0,'don':20,'atrLen':21,'fi':0,'volFilt':False,'oscByTrend':False},
    ('ETH','1h'): {'mode':'advanced','profile':'smooth',  'tps':(0.7,1.4,2.4,3.6),'sl':1.0,'don':20,'atrLen':21,'fi':1,'volFilt':False,'oscByTrend':False},
    ('BTC','1d'): {'mode':'standard','profile':'balanced','tps':(0.5,1.0,1.7,2.5),'sl':0.7,'don':20,'atrLen':14,'fi':0,'volFilt':False,'oscByTrend':True},
}
DEFAULT_PRESET = {'mode':'advanced','profile':'balanced','tps':(0.7,1.4,2.4,3.6),'sl':1.0,'don':20,'atrLen':14,'fi':2,'volFilt':False,'oscByTrend':True}

ML_MIN_TRADES = 10
ML_MIN_CONF   = 0.40
ML_PENALTY_SL = 2

# ── Kraken public API ──
TF_MIN = {'5m':5,'15m':15,'30m':30,'1h':60,'4h':240,'1d':1440}
PAIRS  = {'BTC':'XBTUSDT','ETH':'ETHUSDT'}

def fetch_klines(asset, tf, limit=720):
    pair = PAIRS[asset]; interval = TF_MIN[tf]
    url = f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval={interval}"
    req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode())
    if d.get('error'): raise RuntimeError(f"Kraken: {d['error']}")
    res = d['result']
    pair_key = next(k for k in res if k != 'last')
    rows = res[pair_key][-limit:]
    return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[6])) for r in rows]

# ── Indicator helpers ──
def ema(src, length):
    out=[None]*len(src)
    if not src: return out
    k=2.0/(length+1); out[0]=src[0]
    for i in range(1, len(src)): out[i] = src[i]*k + out[i-1]*(1-k)
    return out

def ema_safe(src, length):
    n=len(src); out=[None]*n
    if n==0: return out
    k=2.0/(length+1)
    seed=next((i for i in range(n) if src[i] is not None), None)
    if seed is None: return out
    out[seed]=src[seed]
    for i in range(seed+1, n):
        out[i] = (src[i]*k + out[i-1]*(1-k)) if src[i] is not None else out[i-1]
    return out

def wilder_atr(highs, lows, closes, length):
    n=len(closes); out=[None]*n
    if n<2: return out
    trs=[None]*n; trs[0]=highs[0]-lows[0]
    for i in range(1,n):
        h,l,pc=highs[i],lows[i],closes[i-1]
        trs[i]=max(h-l,abs(h-pc),abs(l-pc))
    if n<=length: return out
    seed=sum(trs[1:length+1])/length; out[length]=seed
    for i in range(length+1,n): out[i]=(out[i-1]*(length-1)+trs[i])/length
    return out

def rsi(closes, length=14):
    n=len(closes); out=[None]*n
    if n<=length: return out
    gains=[0.0]*n; losses=[0.0]*n
    for i in range(1,n):
        d=closes[i]-closes[i-1]
        gains[i]=d if d>0 else 0; losses[i]=-d if d<0 else 0
    ag=sum(gains[1:length+1])/length; al=sum(losses[1:length+1])/length
    out[length] = 100 - 100/(1+ag/al) if al>0 else 100
    for i in range(length+1,n):
        ag=(ag*(length-1)+gains[i])/length; al=(al*(length-1)+losses[i])/length
        out[i] = 100 - 100/(1+ag/al) if al>0 else 100
    return out

def sma(src, length):
    n=len(src); out=[None]*n
    if n<length: return out
    s=sum(src[:length]); out[length-1]=s/length
    for i in range(length,n):
        s += src[i]-src[i-length]; out[i]=s/length
    return out

def fast_highest(src, length):
    n=len(src); out=[None]*n; dq=deque()
    for i in range(n):
        while dq and dq[0]<=i-length: dq.popleft()
        while dq and src[dq[-1]]<=src[i]: dq.pop()
        dq.append(i)
        if i>=length-1: out[i]=src[dq[0]]
    return out

def fast_lowest(src, length):
    n=len(src); out=[None]*n; dq=deque()
    for i in range(n):
        while dq and dq[0]<=i-length: dq.popleft()
        while dq and src[dq[-1]]>=src[i]: dq.pop()
        dq.append(i)
        if i>=length-1: out[i]=src[dq[0]]
    return out

# ── Signal detection ──
PROFILES = {'sharp':(8,21),'balanced':(21,55),'smooth':(50,200)}

def compute_indicators(candles, cfg):
    highs=[c[2] for c in candles]; lows=[c[3] for c in candles]
    closes=[c[4] for c in candles]; vols=[c[5] for c in candles]
    fL,sL = PROFILES[cfg['profile']]
    return {
        'highs':highs,'lows':lows,'closes':closes,'vols':vols,
        'atr':wilder_atr(highs,lows,closes,cfg['atrLen']),
        'emaF':ema(closes,fL),'emaS':ema(closes,sL),'rsi':rsi(closes,14),
        'donHi':fast_highest(highs,cfg['don']),'donLo':fast_lowest(lows,cfg['don']),
        'chHi':fast_highest(highs,50),'chLo':fast_lowest(lows,50),
        'volSma':sma(vols,20),
    }

def check_signal_at(ind, i, cfg):
    n=len(ind['closes'])
    if i<60 or i>=n: return None
    if any(ind[k][i] is None for k in ('atr','emaF','emaS','rsi')): return None
    if ind['donHi'][i-1] is None or ind['donLo'][i-1] is None: return None
    if ind['volSma'][i] is None or ind['volSma'][i]<=0: return None
    closes=ind['closes']; highs=ind['highs']; lows=ind['lows']
    emaF,emaS,rsiV=ind['emaF'],ind['emaS'],ind['rsi']
    midline=(emaF[i]+emaS[i])/2
    volRatio=ind['vols'][i]/ind['volSma'][i]
    passVol=(not cfg['volFilt']) or volRatio>=1.5
    passFlat=(ind['atr'][i]/closes[i]*100)>=0.20
    fi=cfg['fi']; rsiUpper=70-5*fi; rsiLower=30+5*fi
    tBull=emaF[i]>emaS[i] and rsiV[i]>50 and closes[i]>midline
    tBear=emaF[i]<emaS[i] and rsiV[i]<50 and closes[i]<midline
    pOL=(not cfg['oscByTrend']) or tBull
    pOS=(not cfg['oscByTrend']) or tBear
    longSig=shortSig=False
    mode=cfg['mode']; donHi=ind['donHi']; donLo=ind['donLo']; chHi=ind['chHi']; chLo=ind['chLo']
    if mode=='advanced':
        boL=highs[i]>donHi[i-1] and closes[i]>donHi[i-1]
        boS=lows[i]<donLo[i-1]  and closes[i]<donLo[i-1]
        midPrev=(emaF[i-1]+emaS[i-1])/2
        swL=closes[i]>emaF[i] and closes[i-1]<=midPrev and closes[i]>midline
        swS=closes[i]<emaF[i] and closes[i-1]>=midPrev and closes[i]<midline
        longSig=(boL or swL) and rsiV[i]<rsiUpper
        shortSig=(boS or swS) and rsiV[i]>rsiLower
    elif mode=='standard':
        longSig=highs[i]>donHi[i-1] and closes[i]>donHi[i-1] and rsiV[i]<rsiUpper
        shortSig=lows[i]<donLo[i-1]  and closes[i]<donLo[i-1] and rsiV[i]>rsiLower
    elif mode=='classic':
        longSig=closes[i-1]<=emaF[i-1] and closes[i]>emaF[i] and emaF[i]>emaS[i]
        shortSig=closes[i-1]>=emaF[i-1] and closes[i]<emaF[i] and emaF[i]<emaS[i]
    elif mode=='channel':
        longSig=closes[i]<=chLo[i]*1.002 and rsiV[i-1]<rsiLower and rsiV[i]>=rsiLower
        shortSig=closes[i]>=chHi[i]*0.998 and rsiV[i-1]>rsiUpper and rsiV[i]<=rsiUpper
    elif mode=='oscillator':
        gLine=ema_safe(rsiV,7); rLine=ema_safe(rsiV,14)
        if any(x is None for x in (gLine[i],rLine[i],gLine[i-1],rLine[i-1])): return None
        gxUp=gLine[i-1]<=rLine[i-1] and gLine[i]>rLine[i]
        gxDn=gLine[i-1]>=rLine[i-1] and gLine[i]<rLine[i]
        longSig=gxUp and rsiV[i]<rsiUpper
        shortSig=gxDn and rsiV[i]>rsiLower
    if longSig and pOL and passVol and passFlat: return 'long'
    if shortSig and pOS and passVol and passFlat: return 'short'
    return None

def calc_tp_sl(entry, atr_val, cfg, is_long):
    dir_=1 if is_long else -1
    safeAtr = atr_val if atr_val and atr_val>0 else entry*0.005
    tp1=entry+dir_*safeAtr*cfg['tps'][0]; tp2=entry+dir_*safeAtr*cfg['tps'][1]
    tp3=entry+dir_*safeAtr*cfg['tps'][2]; tp4=entry+dir_*safeAtr*cfg['tps'][3]
    sl =entry-dir_*safeAtr*cfg['sl']
    return sl,tp1,tp2,tp3,tp4

# ── Trade lifecycle ──
def update_open_trade(candles, trade):
    events=[]; last_bar=trade.get('last_bar', trade['opened_bar']); is_long = trade['side']=='long'
    for c in candles:
        bar_time=c[0]
        if bar_time<=last_bar: continue
        h,l = c[2],c[3]
        if is_long:
            if not trade['tp1_hit'] and h>=trade['tp1']:
                trade['tp1_hit']=True
                if not trade['be_moved']:
                    trade['sl']=trade['entry']; trade['be_moved']=True
                events.append({'type':'tp1','price':trade['tp1'],'time':bar_time})
            if trade['tp1_hit'] and not trade['tp2_hit'] and h>=trade['tp2']:
                trade['tp2_hit']=True; trade['sl']=trade['tp1']
                events.append({'type':'tp2','price':trade['tp2'],'time':bar_time})
            if trade['tp2_hit'] and not trade['tp3_hit'] and h>=trade['tp3']:
                trade['tp3_hit']=True; trade['sl']=trade['tp2']
                events.append({'type':'tp3','price':trade['tp3'],'time':bar_time})
            if trade['tp3_hit'] and not trade['tp4_hit'] and h>=trade['tp4']:
                trade['tp4_hit']=True
                events.append({'type':'tp4','price':trade['tp4'],'time':bar_time})
            if l<=trade['sl']:
                events.append({'type':'sl','price':trade['sl'],'time':bar_time})
                trade['last_bar']=bar_time; return events, None
        else:
            if not trade['tp1_hit'] and l<=trade['tp1']:
                trade['tp1_hit']=True
                if not trade['be_moved']:
                    trade['sl']=trade['entry']; trade['be_moved']=True
                events.append({'type':'tp1','price':trade['tp1'],'time':bar_time})
            if trade['tp1_hit'] and not trade['tp2_hit'] and l<=trade['tp2']:
                trade['tp2_hit']=True; trade['sl']=trade['tp1']
                events.append({'type':'tp2','price':trade['tp2'],'time':bar_time})
            if trade['tp2_hit'] and not trade['tp3_hit'] and l<=trade['tp3']:
                trade['tp3_hit']=True; trade['sl']=trade['tp2']
                events.append({'type':'tp3','price':trade['tp3'],'time':bar_time})
            if trade['tp3_hit'] and not trade['tp4_hit'] and l<=trade['tp4']:
                trade['tp4_hit']=True
                events.append({'type':'tp4','price':trade['tp4'],'time':bar_time})
            if h>=trade['sl']:
                events.append({'type':'sl','price':trade['sl'],'time':bar_time})
                trade['last_bar']=bar_time; return events, None
        last_bar=bar_time
    trade['last_bar']=last_bar
    if trade['tp4_hit']: return events, None
    return events, trade

# ── ML (Bayes) ──
def vol_bucket(v): return 0 if v<0.7 else (2 if v>1.3 else 1)
def rsi_bucket(r): return 0 if r<30 else 1 if r<50 else 2 if r<70 else 3
def ses_bucket(hr): return 0 if hr<7 else 1 if hr<13 else 2 if hr<21 else 3
def mode_bucket(m): return {'advanced':0,'standard':1,'classic':2,'channel':3,'oscillator':4}.get(m,0)
def laplace(w,l): return (w+1)/(w+l+2)

def ml_predict(ml, vol_b, rsi_b, ses_b, mode_b):
    def lookup(dim, k):
        v = ml.get(dim, {}).get(str(k), [0,0])
        return laplace(v[0], v[1])
    return (lookup('vol',vol_b)*lookup('rsi',rsi_b)*lookup('ses',ses_b)*lookup('mode',mode_b))**0.25

def ml_update(ml, snap, won, gross_p_inc=0.0, gross_l_inc=0.0):
    delta = 1 if won else ML_PENALTY_SL
    idx = 0 if won else 1
    for dim, key in [('vol','vol_b'),('rsi','rsi_b'),('ses','ses_b'),('mode','mode_b')]:
        bucket=str(snap[key])
        if bucket not in ml.setdefault(dim, {}):
            ml[dim][bucket] = [0, 0]
        ml[dim][bucket][idx] += delta
    ml['total_trades']  = ml.get('total_trades',0)+1
    ml['wins']          = ml.get('wins',0) + (1 if won else 0)
    ml['gross_profit']  = ml.get('gross_profit',0.0) + gross_p_inc
    ml['gross_loss']    = ml.get('gross_loss',0.0) + gross_l_inc

# ── Webhook ──
def deliver(payload, fallback_text):
    if WEBHOOK_URL:
        try:
            req=urllib.request.Request(WEBHOOK_URL, data=json.dumps(payload).encode(),
                                       headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req, timeout=15) as r: return r.status==200
        except Exception as e: print(f"[webhook] {e}", file=sys.stderr); return False
    if TG_TOKEN and TG_CHAT_ID:
        try:
            url=f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
            body=json.dumps({'chat_id':TG_CHAT_ID,'text':fallback_text,'parse_mode':'HTML','disable_web_page_preview':True}).encode()
            req=urllib.request.Request(url, data=body, headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req, timeout=15) as r: return r.status==200
        except Exception as e: print(f"[tg] {e}", file=sys.stderr); return False
    return False

def fmt(p): return f"{p:,.2f}" if p>=1000 else f"{p:,.4f}"

# ── State ──
def load_state():
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text())
        except Exception: pass
    return {}
def save_state(state): STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))
def empty_ml(): return {'vol':{},'rsi':{},'ses':{},'mode':{},'total_trades':0,'wins':0,'gross_profit':0.0,'gross_loss':0.0}

# ── Distance-to-signal helper (per-pair "how close to next trigger?") ──
def compute_distance_to_signal(ind, cfg, last_close):
    """Returns [dist_long_pct, dist_short_pct] — how far price is from next trigger."""
    n = len(ind['closes'])
    if n < 60: return [None, None]
    i = n - 1
    if any(ind[k][i] is None for k in ('atr','emaF','emaS','rsi')): return [None, None]
    donHi = ind['donHi'][i] or ind['closes'][i]
    donLo = ind['donLo'][i] or ind['closes'][i]
    emaF  = ind['emaF'][i]
    midline = (emaF + ind['emaS'][i]) / 2
    mode = cfg['mode']
    long_trigger = donHi
    short_trigger = donLo
    if mode == 'advanced':
        long_trigger  = min(donHi, max(midline, last_close))
        short_trigger = max(donLo, min(midline, last_close))
    elif mode == 'classic':
        long_trigger = emaF
        short_trigger = emaF
    long_dist  = (long_trigger - last_close) / last_close * 100   if last_close > 0 else 0
    short_dist = (last_close - short_trigger) / last_close * 100  if last_close > 0 else 0
    return [round(long_dist, 3), round(short_dist, 3)]

# ── Hour-of-day performance grid (24h × 7 weekdays, accumulates wins/losses) ──
def empty_heatmap(): return [[[0,0] for _ in range(24)] for _ in range(7)]

def update_heatmap(state_heatmap, opened_ts, won):
    dt = datetime.fromtimestamp(opened_ts, tz=timezone.utc)
    dow, hr = dt.weekday(), dt.hour
    cell = state_heatmap[dow][hr]
    cell[0 if won else 1] += 1

# ── Daily/weekly aggregation (per-day R) ──
def update_period_stats(daily_dict, ts, pnl_r):
    day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')
    if day not in daily_dict: daily_dict[day] = 0.0
    daily_dict[day] += pnl_r

def aggregate_periods(daily_dict):
    """Returns {today, week, all_time} R-multiples."""
    today_key = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d')
    today = daily_dict.get(today_key, 0.0)
    # Week = last 7 calendar days
    from datetime import timedelta
    now = datetime.now(tz=timezone.utc)
    week_total = 0.0
    for i in range(7):
        d = (now - timedelta(days=i)).strftime('%Y-%m-%d')
        week_total += daily_dict.get(d, 0.0)
    all_time = sum(daily_dict.values())
    return {'today': round(today, 3), 'week': round(week_total, 3), 'all_time': round(all_time, 3)}

def empty_global_state():
    return {
        'daily_r': {},
        'heatmap': empty_heatmap(),
        'cur_win_streak': 0,
        'cur_loss_streak': 0,
        'max_win_streak': 0,
        'max_loss_streak': 0,
        'journal': [],
        'account_size': 0,
        # ── Risk controls (Tier B) ──
        'daily_loss_limit_r': -3.0,      # auto-pause when day's R drops below this
        'max_concurrent_trades': 4,       # don't open more than this many at once
        'cooldown_minutes_after_sl': 240, # 4h cool-down after SL on a pair
        'sl_cooldowns': {},               # {'BTC_4h': unix_ts_of_SL_hit}
        'paper_mode': False,              # if True, signals don't update real state
        'funding_pause_threshold': 0.05,  # pause new entries if funding > this %
        'risk_per_trade_pct': 1.0,        # default 1% per trade for position sizing
        'last_weekly_summary': None,
    }

# ── Trade verdict scoring (Tier A) ──
def compute_trade_verdict(asset, ml_conf, whale_signal, funding, vol_regime, session_hr, trained_ml_prob=None):
    """Returns dict with verdict (0-100 score), reasoning list, action."""
    score = 50  # neutral starting point
    reasons = []

    # ML confidence (biggest factor)
    if ml_conf is not None:
        if ml_conf >= 0.65:   score += 15; reasons.append(f"🧠 Bayesian ML {ml_conf*100:.0f}% (strong)")
        elif ml_conf >= 0.55: score += 8;  reasons.append(f"🧠 Bayesian ML {ml_conf*100:.0f}% (moderate)")
        elif ml_conf >= 0.45: score += 0;  reasons.append(f"🧠 Bayesian ML {ml_conf*100:.0f}% (neutral)")
        elif ml_conf >= 0.35: score -= 8;  reasons.append(f"🧠 Bayesian ML {ml_conf*100:.0f}% (weak)")
        else:                 score -= 15; reasons.append(f"🧠 Bayesian ML {ml_conf*100:.0f}% (poor)")

    # Trained ML walk-forward prediction (Tier A.2 - ensemble)
    if trained_ml_prob is not None:
        if trained_ml_prob >= 0.62:   score += 10; reasons.append(f"📊 Trained ML {trained_ml_prob*100:.0f}% (bullish)")
        elif trained_ml_prob <= 0.38: score -= 10; reasons.append(f"📊 Trained ML {trained_ml_prob*100:.0f}% (bearish)")

    # Whale positioning
    if whale_signal:
        if whale_signal == 'strong_accum':   score += 12; reasons.append("🐋 Whales accumulating strongly")
        elif whale_signal == 'accum':        score += 6;  reasons.append("🐋 Whales accumulating")
        elif whale_signal == 'strong_distrib': score -= 12; reasons.append("🐋 Whales distributing heavily")
        elif whale_signal == 'distrib':      score -= 6;  reasons.append("🐋 Whales distributing")

    # Funding rate extremes (contrarian)
    if funding is not None:
        if abs(funding) > 0.10:
            score -= 6
            reasons.append(f"⚠ Funding {funding:+.3f}% (overextended)")
        elif abs(funding) > 0.05:
            score -= 3
            reasons.append(f"⚠ Funding {funding:+.3f}% (elevated)")

    # Volatility regime
    if vol_regime is not None:
        if vol_regime > 1.4:   score += 3; reasons.append("⚡ Vol expansion (good for breakouts)")
        elif vol_regime < 0.6: score -= 3; reasons.append("🧊 Vol compression (chop risk)")

    # Session
    if session_hr is not None:
        if 13 <= session_hr < 21: score += 3; reasons.append("🌎 NY session active (highest volume)")
        elif 7 <= session_hr < 13: score += 2; reasons.append("🇬🇧 London session active")
        elif 0 <= session_hr < 7:  score -= 2; reasons.append("🌏 Asia session (lower volume)")

    score = max(0, min(100, score))
    if score >= 75:   action, label = 'strong', '✅ STRONG SETUP'
    elif score >= 60: action, label = 'good',   '✓ Good setup'
    elif score >= 45: action, label = 'mixed',  '~ Mixed signals — caution'
    elif score >= 30: action, label = 'weak',   '⚠ Weak setup — consider passing'
    else:             action, label = 'avoid',  '✗ AVOID — strong negative signals'

    return {'score': score, 'action': action, 'label': label, 'reasons': reasons}

# ── Apply trained ML prediction to current features (Tier A.2) ──
def apply_trained_ml(model, ind, i):
    """Loads trained logistic regression model and predicts probability of up move."""
    if not model or 'btc' not in model: return None
    # Build same features the trainer used
    try:
        closes = ind['closes']; vols = ind['vols']
        if i < 50 or any(ind[k][i] is None for k in ('atr','emaF','emaS','rsi')): return None
        ret_1  = (closes[i]/closes[i-1]  - 1) * 100
        ret_3  = (closes[i]/closes[i-3]  - 1) * 100
        ret_6  = (closes[i]/closes[i-6]  - 1) * 100
        ret_12 = (closes[i]/closes[i-12] - 1) * 100
        rsi_v  = (ind['rsi'][i] - 50) / 50
        atr_p  = ind['atr'][i] / closes[i] * 100
        ema_r  = (ind['emaF'][i] - ind['emaS'][i]) / ind['emaS'][i] * 100
        vol_sma = ind['volSma'][i]
        vol_z = 0
        if vol_sma and vol_sma > 0:
            window = vols[max(0,i-19):i+1]
            m = sum(window)/len(window)
            v = sum((x-m)**2 for x in window) / len(window)
            sd = v**0.5 if v > 0 else 1
            vol_z = (vols[i] - m) / sd if sd > 0 else 0
        from datetime import datetime, timezone
        import math
        hr = datetime.fromtimestamp(ind.get('_last_time', 0), tz=timezone.utc).hour if ind.get('_last_time') else 12
        hr_sin = math.sin(2*math.pi*hr/24); hr_cos = math.cos(2*math.pi*hr/24)
        h50 = sum(ind['highs'][max(0,i-49):i+1]) / min(50, i+1)
        l50 = sum(ind['lows'][max(0,i-49):i+1]) / min(50, i+1)
        dist_h = (closes[i] - h50) / closes[i] * 100
        dist_l = (closes[i] - l50) / closes[i] * 100
        x = [ret_1, ret_3, ret_6, ret_12, rsi_v, atr_p, ema_r, vol_z, hr_sin, hr_cos, dist_h, dist_l]
        # Use BTC model (the trainer trained both; for now use whichever matches asset)
        m = model.get('btc')
        if not m: return None
        # Standardize using trainer's saved means/stds
        x_std = [(x[j] - m['means'][j]) / m['stds'][j] for j in range(len(x))]
        z = sum(m['weights'][j] * x_std[j] for j in range(len(x_std))) + m['bias']
        import math
        if z > 30: return 1.0
        if z < -30: return 0.0
        return 1.0 / (1.0 + math.exp(-z))
    except Exception:
        return None

def load_trained_model():
    f = STATE_DIR / 'trained_model.json'
    if f.exists():
        try: return json.loads(f.read_text())
        except Exception: pass
    return None

# ── Weekly summary (Tier A.7) ──
def compute_weekly_summary(global_state):
    """Compare last 7d vs prior 7d performance across pairs/buckets."""
    from datetime import timedelta
    now = datetime.now(tz=timezone.utc)
    this_week = 0; prior_week = 0
    for i in range(7):
        d = (now - timedelta(days=i)).strftime('%Y-%m-%d')
        this_week += global_state['daily_r'].get(d, 0)
    for i in range(7, 14):
        d = (now - timedelta(days=i)).strftime('%Y-%m-%d')
        prior_week += global_state['daily_r'].get(d, 0)
    delta = this_week - prior_week
    if abs(delta) < 0.5:    trend = 'flat'
    elif delta > 0:         trend = 'improving'
    else:                   trend = 'declining'
    return {'this_week_r': round(this_week, 2), 'prior_week_r': round(prior_week, 2),
            'delta_r': round(delta, 2), 'trend': trend}

# ── Multi-asset correlation (Tier D.27) ──
def compute_correlation(state):
    """Compare last-24h price moves across BTC and ETH using polled data."""
    # This is computed from in-flight poll results — see process_pair caches recent closes
    pass  # populated downstream in main()

# ── Per-pair processing ──
def process_pair(asset, tf, state, results, ml_summary, global_state):
    key=f"{asset}_{tf}"
    cfg=PRESETS.get((asset,tf), DEFAULT_PRESET)
    preset_name = f"🏆 {asset} {tf} Optimal" if (asset,tf) in PRESETS else "Default"
    res = {'asset':asset, 'tf':tf, 'preset':preset_name, 'events':[], 'new_entry':None, 'active_trade':None, 'trade_closed':False,
           'distance_to_signal': [None, None], 'candle_close_at': None, 'last_close': None, 'price_24h': []}

    try:
        candles = fetch_klines(asset, tf)
    except Exception as e:
        print(f"  [{asset} {tf}] fetch failed: {e}", file=sys.stderr)
        results.append(res); return

    # Sparkline data (last ~48 closes — light enough for renderer to draw)
    last_close = candles[-1][4]
    res['last_close'] = last_close
    sample = candles[-48:] if len(candles) >= 48 else candles
    res['price_24h'] = [round(c[4], 6) for c in sample]

    # Candle close timestamp — next bar opens at this UTC ms
    interval_min = TF_MIN[tf]
    bar_ms = interval_min * 60 * 1000
    last_bar_ms = candles[-1][0] * 1000
    res['candle_close_at'] = last_bar_ms + bar_ms

    # Distance-to-signal (always compute, regardless of trade state)
    try:
        ind_for_dist = compute_indicators(candles, cfg)
        res['distance_to_signal'] = compute_distance_to_signal(ind_for_dist, cfg, last_close)
    except Exception: pass

    st = state.setdefault(key, {'active_trade':None,'last_signal_bar':0,'ml':empty_ml()})

    if st['active_trade']:
        events, updated = update_open_trade(candles, st['active_trade'])
        for ev in events: res['events'].append(ev)
        # Live PnL while trade is open (using latest close)
        if updated is not None:
            tr = updated
            dir_ = 1 if tr['side']=='long' else -1
            raw_pct = (last_close - tr['entry']) / tr['entry'] * 100 * dir_
            updated['live_pnl_pct']     = round(raw_pct, 3)
            updated['live_pnl_leveraged'] = round(raw_pct * LEVERAGE, 2)
            updated['duration_sec'] = max(0, int((candles[-1][0] - tr['opened_bar'])))
        if updated is None:
            tr=st['active_trade']
            won = tr['tp1_hit'] or tr['tp2_hit'] or tr['tp3_hit'] or tr['tp4_hit']
            # Approximate R-multiples for stats
            init_sl_dist = abs(tr['entry']-tr['init_sl']) if 'init_sl' in tr else abs(tr['entry']-tr['sl'])
            splits=(0.50,0.25,0.15,0.10); tps_hit=[tr['tp1_hit'],tr['tp2_hit'],tr['tp3_hit'],tr['tp4_hit']]
            tps_val=[tr['tp1'],tr['tp2'],tr['tp3'],tr['tp4']]
            pnl=0.0
            if init_sl_dist>0:
                for k in range(4):
                    if tps_hit[k]: pnl += splits[k]*abs(tps_val[k]-tr['entry'])/init_sl_dist
                rem = sum(splits[k] for k in range(4) if not tps_hit[k])
                pnl += rem * ((tr['sl']-tr['entry']) / init_sl_dist * (1 if tr['side']=='long' else -1))
            gp = pnl if pnl>0 else 0
            gl = abs(pnl) if pnl<=0 else 0
            ml_update(st['ml'], tr['ml_snap'], won, gp, gl)
            # ── Update global state (streaks, daily R, heatmap, journal) ──
            if won:
                global_state['cur_win_streak'] += 1
                global_state['cur_loss_streak'] = 0
                global_state['max_win_streak'] = max(global_state['max_win_streak'], global_state['cur_win_streak'])
            else:
                global_state['cur_loss_streak'] += 1
                global_state['cur_win_streak'] = 0
                global_state['max_loss_streak'] = max(global_state['max_loss_streak'], global_state['cur_loss_streak'])
            update_period_stats(global_state['daily_r'], tr.get('opened_bar', candles[-1][0]), pnl)
            update_heatmap(global_state['heatmap'], tr.get('opened_bar', candles[-1][0]), won)
            # ── Cool-down on SL hit (Tier B) ──
            if not won:
                global_state.setdefault('sl_cooldowns', {})[key] = datetime.now(tz=timezone.utc).timestamp()
            # Auto-journal
            global_state['journal'].append({
                'asset':asset, 'tf':tf, 'side':tr['side'],
                'entry':tr['entry'], 'exit':tr['sl'],
                'tp1_hit':tr['tp1_hit'], 'tp2_hit':tr['tp2_hit'],
                'tp3_hit':tr['tp3_hit'], 'tp4_hit':tr['tp4_hit'],
                'pnl_r':round(pnl, 3), 'won':won,
                'opened_at':tr.get('opened_bar', 0), 'closed_at':candles[-1][0],
            })
            # Cap journal at 500 entries
            if len(global_state['journal']) > 500:
                global_state['journal'] = global_state['journal'][-500:]
            st['active_trade']=None
            res['trade_closed']=True
            res['closed_outcome'] = {'won':won, 'pnl_r':round(pnl, 3)}
        else:
            st['active_trade']=updated
            res['active_trade']=updated

    if st['active_trade'] is None and len(candles)>60:
        confirm_idx = len(candles)-2
        if candles[confirm_idx][0] > st['last_signal_bar']:
            ind = compute_indicators(candles, cfg)
            sig = check_signal_at(ind, confirm_idx, cfg)
            if sig:
                ent = candles[confirm_idx][4]
                atr_v = ind['atr'][confirm_idx] or ent*0.005
                sl,t1,t2,t3,t4 = calc_tp_sl(ent, atr_v, cfg, sig=='long')
                volRegime = atr_v / (ind['atr'][confirm_idx-50] or atr_v) if confirm_idx>=50 else 1.0
                hr_utc = datetime.fromtimestamp(candles[confirm_idx][0], tz=timezone.utc).hour
                snap = {'vol_b':vol_bucket(volRegime),'rsi_b':rsi_bucket(ind['rsi'][confirm_idx]),'ses_b':ses_bucket(hr_utc),'mode_b':mode_bucket(cfg['mode'])}
                ml_conf = ml_predict(st['ml'], snap['vol_b'], snap['rsi_b'], snap['ses_b'], snap['mode_b'])
                # ── Apply Tier B risk controls ──
                blocked_by = None
                # Daily loss limit
                today_r = aggregate_periods(global_state['daily_r'])['today']
                if today_r <= global_state.get('daily_loss_limit_r', -3.0):
                    blocked_by = f'daily loss limit hit ({today_r:.2f}R)'
                # Max concurrent trades
                open_count = sum(1 for k, v in state.items() if k != '__global' and v and v.get('active_trade'))
                if blocked_by is None and open_count >= global_state.get('max_concurrent_trades', 4):
                    blocked_by = f'{open_count} trades already open (max {global_state["max_concurrent_trades"]})'
                # Cool-down after SL
                last_sl = global_state.get('sl_cooldowns', {}).get(key, 0)
                cd_min = global_state.get('cooldown_minutes_after_sl', 240)
                if blocked_by is None and last_sl > 0:
                    since_sl = (datetime.now(tz=timezone.utc).timestamp() - last_sl) / 60
                    if since_sl < cd_min:
                        blocked_by = f'cool-down after SL ({int(cd_min - since_sl)}min remaining)'
                # Funding pause
                if blocked_by is None:
                    fund_thresh = global_state.get('funding_pause_threshold', 0.05)
                    # cached from previous fetch_market_context — best-effort
                if blocked_by:
                    print(f"  [{asset} {tf}] signal {sig} BLOCKED by risk control: {blocked_by}")
                    res['blocked_by'] = blocked_by
                elif st['ml'].get('total_trades',0) >= ML_MIN_TRADES and ml_conf < ML_MIN_CONF:
                    print(f"  [{asset} {tf}] signal {sig} BLOCKED by ML ({ml_conf*100:.1f}%)")
                    res['blocked_by'] = f'ML conf {ml_conf*100:.1f}% < {ML_MIN_CONF*100}%'
                else:
                    new_trade = {
                        'side':sig,'entry':ent,'sl':sl,'init_sl':sl,
                        'tp1':t1,'tp2':t2,'tp3':t3,'tp4':t4,
                        'tp1_hit':False,'tp2_hit':False,'tp3_hit':False,'tp4_hit':False,
                        'be_moved':False,'opened_bar':candles[confirm_idx][0],
                        'last_bar':candles[confirm_idx][0],'ml_snap':snap,
                    }
                    st['active_trade'] = new_trade
                    res['active_trade'] = new_trade
                    res['new_entry'] = {'side':sig,'entry':ent,'ml_conf':ml_conf}
                    # Build beautiful Telegram payload
                    emoji = "🟢" if sig=='long' else "🔴"
                    side_t = "L O N G" if sig=='long' else "S H O R T"
                    text = (f"{emoji}━━━━━━━━━━━━━━━━━━━━━━{emoji}\n"
                            f"      <b>MiND-Shøt</b>\n"
                            f"        <b>{side_t}</b>   ⚡<code>{LEVERAGE}x</code>\n"
                            f"{emoji}━━━━━━━━━━━━━━━━━━━━━━{emoji}\n\n"
                            f"📊  <code>{asset}/USD</code>   ⏱  <b>{tf}</b>\n"
                            f"🎯  <i>{preset_name}</i>\n"
                            f"🧠  ML Confidence  ·  <b>{ml_conf*100:.1f}%</b>\n\n"
                            f"▰▰▰▰  <b>POSITION</b>  ▰▰▰▰▰▰\n"
                            f"📍 <b>Entry</b>   <code>{fmt(ent)}</code>\n"
                            f"🛡 <b>Stop</b>    <code>{fmt(sl)}</code>\n\n"
                            f"▰▰▰▰▰  <b>TARGETS</b>  ▰▰▰▰▰\n"
                            f"✅ <b>TP1</b>  <code>{fmt(t1)}</code>  ·  50%\n"
                            f"✅ <b>TP2</b>  <code>{fmt(t2)}</code>  ·  25%\n"
                            f"✅ <b>TP3</b>  <code>{fmt(t3)}</code>  ·  15%\n"
                            f"🚀 <b>TP4</b>  <code>{fmt(t4)}</code>  ·  10%\n\n"
                            f"<i>💡 SL auto-moves: TP1→BE  ·  TP2→TP1  ·  TP3→TP2</i>")
                    deliver({'type':'entry','side':sig.upper(),'asset':asset,'tf':tf,
                             'preset':preset_name,'ml_conf':round(ml_conf*100,1),'leverage':LEVERAGE,
                             'entry':ent,'sl':sl,'tp1':t1,'tp2':t2,'tp3':t3,'tp4':t4,'text':text}, text)
                    print(f"  [{asset} {tf}] NEW {sig.upper()} @ {fmt(ent)} ML={ml_conf*100:.1f}%")
            st['last_signal_bar'] = candles[confirm_idx][0]

    # Fire event webhooks
    for ev in res['events']:
        ev_type = ev['type']
        emoji = "🚀" if ev_type=='tp4' else "🛡" if ev_type=='sl' else "✅"
        side_state = st['active_trade'] or {}
        ent = side_state.get('entry')
        if ent:
            raw_pct = abs(ev['price']-ent)/ent*100
            lev_pct = raw_pct * LEVERAGE
            text = (f"{emoji}━━━━━━━━━━━━━━━━━━━━━{emoji}\n"
                    f"     <b>{ev_type.upper()} HIT</b>\n"
                    f"     <b>+{lev_pct:.2f}%</b>   @  ⚡<code>{LEVERAGE}x</code>\n"
                    f"{emoji}━━━━━━━━━━━━━━━━━━━━━{emoji}\n\n"
                    f"📊  <code>{asset}/USD</code>  ·  <b>{tf}</b>\n"
                    f"💰  Price:  <code>{fmt(ev['price'])}</code>")
            deliver({'type':'event','event':ev_type,'asset':asset,'tf':tf,'price':ev['price'],
                     'pct_leveraged':lev_pct,'text':text}, text)

    # ML summary for renderer gauge
    ml = st['ml']
    if ml.get('total_trades',0)>0:
        # Approximate current confidence — use latest cur* readings from the just-computed ind
        try:
            volRegime = (ml.get('total_trades',0)>0) * 1.0
            ml_summary[key] = {
                'total_trades': ml.get('total_trades',0),
                'wins': ml.get('wins',0),
                'wr': ml.get('wins',0)/ml.get('total_trades',1),
                'conf': laplace(ml.get('wins',0), ml.get('total_trades',0)-ml.get('wins',0)),
            }
        except Exception: pass

    results.append(res)

def fetch_market_context():
    """One-shot fetch of macro context: BTC dominance, Fear & Greed, BTC/ETH funding."""
    ctx = {}
    # Fear & Greed (alternative.me — free, no auth)
    try:
        req = urllib.request.Request('https://api.alternative.me/fng/?limit=1',
                                     headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode())
            d0 = d.get('data', [{}])[0]
            ctx['fear_greed'] = {'value': int(d0.get('value', 0)),
                                 'classification': d0.get('value_classification', '—')}
    except Exception: ctx['fear_greed'] = None
    # BTC Dominance + total market cap via CoinGecko (free)
    try:
        req = urllib.request.Request('https://api.coingecko.com/api/v3/global',
                                     headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode()).get('data', {})
            ctx['btc_dominance']  = round(d.get('market_cap_percentage', {}).get('btc', 0), 2)
            ctx['eth_dominance']  = round(d.get('market_cap_percentage', {}).get('eth', 0), 2)
            ctx['mcap_change_24h']= round(d.get('market_cap_change_percentage_24h_usd', 0), 2)
    except Exception:
        ctx['btc_dominance'] = ctx['eth_dominance'] = ctx['mcap_change_24h'] = None
    # 24h ticker (BTC + ETH) from Kraken
    try:
        req = urllib.request.Request('https://api.kraken.com/0/public/Ticker?pair=XBTUSDT,ETHUSDT',
                                     headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode()).get('result', {})
            tickers = {}
            for k, v in d.items():
                price = float(v['c'][0]) if 'c' in v else None
                open24 = float(v['o']) if 'o' in v else None
                chg = ((price - open24) / open24 * 100) if (price and open24) else None
                hi = float(v['h'][1]) if 'h' in v else None
                lo = float(v['l'][1]) if 'l' in v else None
                vol = float(v['v'][1]) if 'v' in v else None
                sym = 'BTC' if 'XBT' in k else 'ETH'
                tickers[sym] = {'price':price, 'change_24h':round(chg, 2) if chg else None,
                                'high_24h':hi, 'low_24h':lo, 'vol_24h':vol}
            ctx['tickers'] = tickers
    except Exception: ctx['tickers'] = {}
    # Funding rates (Binance — public)
    try:
        req = urllib.request.Request('https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT',
                                     headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode())
            ctx['btc_funding'] = round(float(d.get('lastFundingRate', 0)) * 100, 4)
        req = urllib.request.Request('https://fapi.binance.com/fapi/v1/premiumIndex?symbol=ETHUSDT',
                                     headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode())
            ctx['eth_funding'] = round(float(d.get('lastFundingRate', 0)) * 100, 4)
    except Exception:
        ctx['btc_funding'] = ctx['eth_funding'] = None
    return ctx

# ════════════════════════════════════════════════════════════════
# WHALE MONEY DETECTION — FREE APIs only (Binance public + Whale Alert + Coinglass-style)
# ════════════════════════════════════════════════════════════════

def fetch_whale_flow():
    """Aggregate whale-positioning signals from free public APIs.
    Returns: dict with per-asset top-trader L/S ratio, OI change, taker buy/sell,
             plus recent whale-alert transactions when available."""
    out = {'BTC': {}, 'ETH': {}, 'whale_alerts': [], 'net_signal': {}}

    for asset, sym in [('BTC','BTCUSDT'), ('ETH','ETHUSDT')]:
        a = {}
        try:
            # Top-trader account-based long/short ratio (whale positioning by account count)
            req = urllib.request.Request(
                f'https://fapi.binance.com/futures/data/topLongShortAccountRatio?symbol={sym}&period=1h&limit=2',
                headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.loads(r.read().decode())
                if d:
                    latest = d[-1]
                    a['top_trader_ls_account'] = round(float(latest.get('longShortRatio', 0)), 3)
                    if len(d) >= 2:
                        prev = d[-2]
                        a['top_trader_ls_account_chg'] = round(float(latest['longShortRatio']) - float(prev['longShortRatio']), 3)
        except Exception: pass

        try:
            # Top-trader position-weighted L/S ratio (whales by money, not count)
            req = urllib.request.Request(
                f'https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol={sym}&period=1h&limit=2',
                headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.loads(r.read().decode())
                if d:
                    latest = d[-1]
                    a['top_trader_ls_position'] = round(float(latest.get('longShortRatio', 0)), 3)
                    if len(d) >= 2:
                        prev = d[-2]
                        a['top_trader_ls_position_chg'] = round(float(latest['longShortRatio']) - float(prev['longShortRatio']), 3)
        except Exception: pass

        try:
            # Open Interest 24h (perpetual money flow)
            req = urllib.request.Request(
                f'https://fapi.binance.com/futures/data/openInterestHist?symbol={sym}&period=1h&limit=24',
                headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.loads(r.read().decode())
                if d and len(d) >= 2:
                    latest = float(d[-1].get('sumOpenInterest', 0))
                    prior  = float(d[0].get('sumOpenInterest', 0))
                    chg_pct = (latest - prior) / prior * 100 if prior > 0 else 0
                    a['oi_24h_change_pct'] = round(chg_pct, 2)
                    a['oi_now']            = round(latest, 0)
        except Exception: pass

        try:
            # Taker buy/sell ratio (aggressive money — market orders)
            req = urllib.request.Request(
                f'https://fapi.binance.com/futures/data/takerlongshortRatio?symbol={sym}&period=1h&limit=1',
                headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.loads(r.read().decode())
                if d:
                    a['taker_buy_sell'] = round(float(d[-1].get('buySellRatio', 0)), 3)
        except Exception: pass

        # Net signal classification (combine the dimensions)
        out[asset] = a
        score = 0
        if a.get('top_trader_ls_position', 1) > 1.5: score += 2
        elif a.get('top_trader_ls_position', 1) > 1.2: score += 1
        elif a.get('top_trader_ls_position', 1) < 0.7: score -= 2
        elif a.get('top_trader_ls_position', 1) < 0.85: score -= 1
        if a.get('top_trader_ls_position_chg', 0) > 0.1: score += 1
        elif a.get('top_trader_ls_position_chg', 0) < -0.1: score -= 1
        if a.get('oi_24h_change_pct', 0) > 5: score += 1
        elif a.get('oi_24h_change_pct', 0) < -5: score -= 1
        if a.get('taker_buy_sell', 1) > 1.15: score += 1
        elif a.get('taker_buy_sell', 1) < 0.87: score -= 1
        if score >= 3:   out['net_signal'][asset] = 'strong_accum'
        elif score >= 1: out['net_signal'][asset] = 'accum'
        elif score <= -3: out['net_signal'][asset] = 'strong_distrib'
        elif score <= -1: out['net_signal'][asset] = 'distrib'
        else: out['net_signal'][asset] = 'neutral'
        out[asset]['_score'] = score

    # Recent large transactions (Whale Alert free tier — last 60s, $500K+, max 5/req)
    try:
        url = 'https://api.whale-alert.io/v1/transactions?api_key=PUBLIC&min_value=500000&start=' + str(int(datetime.now(tz=timezone.utc).timestamp()) - 600)
        # Whale Alert's free public endpoint (no auth required for limited data)
        req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read().decode())
            txs = d.get('transactions', [])[:5]
            out['whale_alerts'] = [{
                'symbol': tx.get('symbol', '').upper(),
                'amount_usd': int(tx.get('amount_usd', 0)),
                'from_owner': tx.get('from', {}).get('owner_type', 'unknown'),
                'to_owner':   tx.get('to', {}).get('owner_type', 'unknown'),
                'ts': tx.get('timestamp', 0),
            } for tx in txs]
    except Exception:
        out['whale_alerts'] = []  # Whale Alert may rate-limit or require API key; fail silently

    return out

# ════════════════════════════════════════════════════════════════
# TP/SL HIT ACCURACY — compute from journal data
# ════════════════════════════════════════════════════════════════

def compute_tp_accuracy(journal, active_pairs):
    """For each (asset, tf), return TP1/2/3/4/SL hit rates + valid/invalid counts."""
    by_pair = {}
    for entry in journal:
        key = f"{entry['asset']}_{entry['tf']}"
        if key not in by_pair:
            by_pair[key] = {'total':0,'tp1':0,'tp2':0,'tp3':0,'tp4':0,'sl':0,'valid':0,'invalid':0}
        b = by_pair[key]
        b['total'] += 1
        if entry.get('tp1_hit'): b['tp1'] += 1
        if entry.get('tp2_hit'): b['tp2'] += 1
        if entry.get('tp3_hit'): b['tp3'] += 1
        if entry.get('tp4_hit'): b['tp4'] += 1
        # SL hit = trade exited without TP4 (any close that wasn't TP4 = SL hit happened)
        if not entry.get('tp4_hit'): b['sl'] += 1
        if entry.get('won'): b['valid'] += 1
        else: b['invalid'] += 1
    # Add pair rows even if no trades (for visualization completeness)
    for p in active_pairs:
        key = f"{p[0]}_{p[1]}"
        if key not in by_pair:
            by_pair[key] = {'total':0,'tp1':0,'tp2':0,'tp3':0,'tp4':0,'sl':0,'valid':0,'invalid':0}
    # Compute percentages
    result = {}
    for key, b in by_pair.items():
        t = b['total']
        result[key] = {
            'asset': key.split('_')[0],
            'tf':    key.split('_')[1],
            'total': t,
            'tp1_pct': round(b['tp1']/t*100, 1) if t else None,
            'tp2_pct': round(b['tp2']/t*100, 1) if t else None,
            'tp3_pct': round(b['tp3']/t*100, 1) if t else None,
            'tp4_pct': round(b['tp4']/t*100, 1) if t else None,
            'sl_pct':  round(b['sl']/t*100, 1) if t else None,
            'valid_pct':   round(b['valid']/t*100, 1) if t else None,
            'invalid_pct': round(b['invalid']/t*100, 1) if t else None,
            'tp1':b['tp1'],'tp2':b['tp2'],'tp3':b['tp3'],'tp4':b['tp4'],
            'sl':b['sl'],'valid':b['valid'],'invalid':b['invalid'],
        }
    return result

def run_one_poll():
    """Single poll cycle — exactly what main() used to do."""
    state = load_state()
    # Global state lives under a special key in state.json
    if '__global' not in state: state['__global'] = empty_global_state()
    global_state = state['__global']
    # Ensure heatmap exists (in case of old state files)
    if 'heatmap' not in global_state: global_state['heatmap'] = empty_heatmap()

    results = []
    ml_summary = {}
    for asset, tf in ACTIVE:
        try: process_pair(asset, tf, state, results, ml_summary, global_state)
        except Exception as e: print(f"  error {asset} {tf}: {e}", file=sys.stderr)

    # Fetch macro market context (every poll — fast, cached server-side anyway)
    market_ctx = fetch_market_context()

    # Fetch whale-positioning signals (free APIs)
    whale_ctx = fetch_whale_flow()

    # Compute per-pair TP/SL hit accuracy from journal data
    tp_accuracy = compute_tp_accuracy(global_state['journal'], ACTIVE)

    # Load trained ML model (if user has trained one)
    trained_model = load_trained_model()

    # Compute trade verdict for each pair (current "should I take this trade" score)
    verdicts = {}
    for r in results:
        key = f"{r['asset']}_{r['tf']}"
        ml_conf = (ml_summary.get(key) or {}).get('conf')
        whale_sig = (whale_ctx.get('net_signal') or {}).get(r['asset'])
        funding = market_ctx.get(f"{r['asset'].lower()}_funding")
        vol_regime = None  # would need recent ATR / median ratio per pair
        hr = datetime.now(tz=timezone.utc).hour
        verdicts[key] = compute_trade_verdict(r['asset'], ml_conf, whale_sig, funding, vol_regime, hr,
                                              trained_ml_prob=None)  # per-pair trained ML below

    # Weekly summary
    weekly = compute_weekly_summary(global_state)

    # Multi-asset correlation (Tier D): compare last 24h price moves
    correlation = {}
    btc_prices = next((r['price_24h'] for r in results if r['asset']=='BTC'), [])
    eth_prices = next((r['price_24h'] for r in results if r['asset']=='ETH'), [])
    if len(btc_prices) >= 10 and len(eth_prices) >= 10:
        n = min(len(btc_prices), len(eth_prices))
        b = btc_prices[-n:]; e = eth_prices[-n:]
        b_ret = [b[i+1]/b[i]-1 for i in range(n-1)]
        e_ret = [e[i+1]/e[i]-1 for i in range(n-1)]
        bm = sum(b_ret)/len(b_ret); em = sum(e_ret)/len(e_ret)
        cov = sum((b_ret[i]-bm)*(e_ret[i]-em) for i in range(len(b_ret))) / len(b_ret)
        bv = (sum((x-bm)**2 for x in b_ret)/len(b_ret))**0.5
        ev = (sum((x-em)**2 for x in e_ret)/len(e_ret))**0.5
        if bv*ev > 0:
            correlation['btc_eth'] = round(cov / (bv*ev), 3)
        btc_chg = (b[-1]/b[0]-1)*100 if b[0]>0 else 0
        eth_chg = (e[-1]/e[0]-1)*100 if e[0]>0 else 0
        correlation['btc_24h_pct'] = round(btc_chg, 2)
        correlation['eth_24h_pct'] = round(eth_chg, 2)
        correlation['lead_lag'] = 'BTC leads' if abs(btc_chg) > abs(eth_chg) * 1.15 else \
                                  'ETH leads' if abs(eth_chg) > abs(btc_chg) * 1.15 else 'in sync'

    save_state(state)

    blob = {
        'timestamp': datetime.now(tz=timezone.utc).isoformat(),
        'polls': results,
        'ml_summary': ml_summary,
        'market': market_ctx,
        'whale': whale_ctx,
        'tp_accuracy': tp_accuracy,
        'verdicts': verdicts,
        'weekly_summary': weekly,
        'correlation': correlation,
        'trained_model_summary': {
            'btc_oos_wr': (trained_model or {}).get('btc_oos_wr'),
            'eth_oos_wr': (trained_model or {}).get('eth_oos_wr'),
            'trained_at': (trained_model or {}).get('trained_at'),
        } if trained_model else None,
        'risk_controls': {
            'daily_loss_limit_r':       global_state.get('daily_loss_limit_r', -3.0),
            'max_concurrent_trades':    global_state.get('max_concurrent_trades', 4),
            'cooldown_minutes_after_sl':global_state.get('cooldown_minutes_after_sl', 240),
            'funding_pause_threshold':  global_state.get('funding_pause_threshold', 0.05),
            'risk_per_trade_pct':       global_state.get('risk_per_trade_pct', 1.0),
            'paper_mode':               global_state.get('paper_mode', False),
            'sl_cooldowns':             global_state.get('sl_cooldowns', {}),
        },
        'periods': aggregate_periods(global_state['daily_r']),
        'streaks': {
            'cur_win':  global_state['cur_win_streak'],
            'cur_loss': global_state['cur_loss_streak'],
            'max_win':  global_state['max_win_streak'],
            'max_loss': global_state['max_loss_streak'],
        },
        'heatmap':       global_state['heatmap'],
        'daily_r':       global_state['daily_r'],
        'journal':       global_state['journal'][-30:],
        'account_size':  global_state.get('account_size', 0),
    }
    # GitHub Actions doesn't read stdout JSON — only Electron does.
    # Keep the marker output suppressed unless OUTPUT_JSON=1 explicitly.
    if OUTPUT_JSON:
        sys.stdout.write('<<<MINDSHOT_JSON>>>')
        sys.stdout.write(json.dumps(blob))
        sys.stdout.write('<<</MINDSHOT_JSON>>>\n')
        sys.stdout.flush()

# ════════════════════════════════════════════════════════════════
# GitHub Actions polling loop
# ════════════════════════════════════════════════════════════════
# Cron fires every minute (best effort). Each invocation runs N
# internal polls with sleeps between, so even if cron is delayed
# the engine still produces ~1-min granular signal checks.

POLLS_PER_RUN     = int(os.environ.get('POLLS_PER_RUN',     '1'))
POLL_INTERVAL_SEC = int(os.environ.get('POLL_INTERVAL_SEC', '60'))

def main():
    import time as _t
    if WEBHOOK_URL:        delivery = f"webhook ({WEBHOOK_URL[:48]}…)"
    elif TG_TOKEN:         delivery = f"Telegram bot direct (chat={TG_CHAT_ID})"
    else:                  delivery = "DRY-RUN (no webhook / no Telegram)"
    print(f"📡 Delivery: {delivery}")
    print(f"MiND-Shot Engine — {datetime.now(tz=timezone.utc).isoformat()}")
    print(f"Active pairs: {len(ACTIVE)}  ·  Polls/run: {POLLS_PER_RUN}  ·  Interval: {POLL_INTERVAL_SEC}s")
    for poll_num in range(1, POLLS_PER_RUN + 1):
        print(f"\n── Poll {poll_num}/{POLLS_PER_RUN}  @  {datetime.now(tz=timezone.utc).strftime('%H:%M:%S')} UTC ──")
        try:
            run_one_poll()
        except Exception as e:
            print(f"    poll error: {e}", file=sys.stderr)
        if poll_num < POLLS_PER_RUN:
            _t.sleep(POLL_INTERVAL_SEC)
    print("\nDone.")

if __name__ == '__main__': main()
