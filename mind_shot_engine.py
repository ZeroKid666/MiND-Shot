#!/usr/bin/env python3
"""
MiND-Shot Standalone Engine
─────────────────────────────────────────────────────────────────
Polls Kraken's free public OHLCV API for BTC + ETH on multiple
timeframes, runs the IDENTICAL MiND-Shot signal logic that lives
in the Pine Script indicator, tracks open trades with the universal
SL ratchet, persists ML state to JSON, and sends rich-formatted
alerts directly to your Telegram bot.

Designed to run on GitHub Actions cron every 5 minutes — no
TradingView Pro subscription needed.

Author : MiND
License: MIT
"""
import os, json, time, urllib.request, urllib.error
from collections import deque
from pathlib import Path
from datetime import datetime, timezone

# ════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ════════════════════════════════════════════════════════════════

# ── Delivery method (pick ONE) ──
#   Option A: Make.com / Pipedream / n8n webhook URL — simplest, no Telegram setup needed
#   Option B: Telegram Bot API direct — requires TG_TOKEN + TG_CHAT_ID
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '')   # paste your Make.com hook here
TG_TOKEN    = os.environ.get('TG_TOKEN', '')
TG_CHAT_ID  = os.environ.get('TG_CHAT_ID', '')

# Display leverage on alerts (does not affect signal logic)
LEVERAGE = int(os.environ.get('LEVERAGE', '10'))

# Where ML / open-trade state lives — committed back to the repo by the workflow
STATE_DIR = Path(__file__).parent / 'state'
STATE_DIR.mkdir(exist_ok=True)
STATE_FILE = STATE_DIR / 'state.json'

# Active (asset, timeframe) pairs to monitor SIMULTANEOUSLY.
# Each pair runs independently every 5 min — its own signal logic, its own
# preset config, its own ML state, its own Telegram alerts. You'll get
# notified about all of them in real time.
#
# Default = the 4 starred (🏆) presets from the indicator's Quick Asset Preset
# dropdown. Add more (asset, TF) tuples below to monitor extra pairs;
# anything not in the PRESETS dict falls back to DEFAULT_PRESET.
ACTIVE = [
    ('BTC', '4h'),   # 🏆 BTC 4h Optimal       (88.9% WR · +12.4R)
    ('ETH', '4h'),   # 🏆 ETH 4h Optimal       (90.5% WR · +9.2R)
    ('BTC', '1h'),   # 🏆 BTC 1h Oscillator    (77.3% WR · +8.0R)
    ('ETH', '1d'),   # 🏆 ETH 1d Swing         (82.6% WR · +5.9R)
    # Uncomment any of these to monitor additional pairs:
    # ('BTC', '15m'),
    # ('BTC', '30m'),
    # ('BTC', '1d'),
    # ('ETH', '15m'),
    # ('ETH', '30m'),
    # ('ETH', '1h'),
]

# ── Asset Presets — match the indicator's "🚀 Quick Asset Preset" options ──
#    These are the BACKTESTED-OPTIMAL configs found via 21,892 grid runs.
PRESETS = {
    ('BTC', '4h'): {  # 88.9% WR · +12.4R · 27 trades
        'mode':'advanced', 'profile':'balanced',
        'tps':(0.7, 1.4, 2.4, 3.6), 'sl':1.0,
        'don':20, 'atrLen':21, 'fi':2,
        'volFilt':False, 'oscByTrend':False,
    },
    ('ETH', '4h'): {  # 90.5% WR · +9.2R · 21 trades
        'mode':'advanced', 'profile':'sharp',
        'tps':(0.7, 1.4, 2.4, 3.6), 'sl':1.0,
        'don':20, 'atrLen':21, 'fi':2,
        'volFilt':False, 'oscByTrend':True,
    },
    ('BTC', '1h'): {  # 77.3% WR · +8.0R · 22 trades — pure oscillator mode
        'mode':'oscillator', 'profile':'balanced',
        'tps':(0.7, 1.4, 2.4, 3.6), 'sl':1.0,
        'don':20, 'atrLen':14, 'fi':0,
        'volFilt':False, 'oscByTrend':True,
    },
    ('ETH', '1d'): {  # 82.6% WR · +5.9R · 23 trades — daily swing
        'mode':'advanced', 'profile':'sharp',
        'tps':(1.5, 3.0, 5.0, 7.5), 'sl':2.0,
        'don':20, 'atrLen':14, 'fi':0,
        'volFilt':True,  'oscByTrend':False,
    },
    ('BTC', '15m'): {
        'mode':'advanced', 'profile':'sharp',
        'tps':(0.5, 1.0, 1.7, 2.5), 'sl':0.7,
        'don':20, 'atrLen':21, 'fi':2,
        'volFilt':False, 'oscByTrend':False,
    },
    ('ETH', '15m'): {
        'mode':'advanced', 'profile':'sharp',
        'tps':(1.0, 2.0, 3.5, 5.0), 'sl':1.5,
        'don':14, 'atrLen':21, 'fi':1,
        'volFilt':False, 'oscByTrend':False,
    },
    ('BTC', '30m'): {
        'mode':'channel', 'profile':'sharp',
        'tps':(1.0, 2.0, 3.5, 5.0), 'sl':1.5,
        'don':14, 'atrLen':21, 'fi':2, 'channelType':'keltner',
        'volFilt':False, 'oscByTrend':False,
    },
    ('ETH', '30m'): {
        'mode':'advanced', 'profile':'sharp',
        'tps':(0.7, 1.4, 2.4, 3.6), 'sl':1.0,
        'don':20, 'atrLen':21, 'fi':0,
        'volFilt':False, 'oscByTrend':False,
    },
    ('ETH', '1h'): {
        'mode':'advanced', 'profile':'smooth',
        'tps':(0.7, 1.4, 2.4, 3.6), 'sl':1.0,
        'don':20, 'atrLen':21, 'fi':1,
        'volFilt':False, 'oscByTrend':False,
    },
    ('BTC', '1d'): {
        'mode':'standard', 'profile':'balanced',
        'tps':(0.5, 1.0, 1.7, 2.5), 'sl':0.7,
        'don':20, 'atrLen':14, 'fi':0,
        'volFilt':False, 'oscByTrend':True,
    },
}

# Universal default fallback if a (asset, TF) is not in PRESETS
DEFAULT_PRESET = {
    'mode':'advanced', 'profile':'balanced',
    'tps':(0.7, 1.4, 2.4, 3.6), 'sl':1.0,
    'don':20, 'atrLen':14, 'fi':2,
    'volFilt':False, 'oscByTrend':True,
}

# ML thresholds — Bayesian per-feature-bucket gating
ML_MIN_TRADES = 10
ML_MIN_CONF   = 0.40
ML_PENALTY_SL = 2

# ── Internal poll loop ──
# GitHub Actions cron is best-effort (often delayed 5-10 min during peak load).
# To get reliable 1-min granularity, each workflow execution does N internal
# polls with a sleep between them. Defaults give 5 polls × 60 sec = 5 min coverage,
# matching the workflow's */1 cron so polls happen ~every minute even if cron skips.
POLLS_PER_RUN     = int(os.environ.get('POLLS_PER_RUN',     '1'))
POLL_INTERVAL_SEC = int(os.environ.get('POLL_INTERVAL_SEC', '60'))

# ════════════════════════════════════════════════════════════════
#  KRAKEN PUBLIC API (no auth required)
# ════════════════════════════════════════════════════════════════

TF_MIN = {'5m':5,'15m':15,'30m':30,'1h':60,'4h':240,'1d':1440}
PAIRS  = {'BTC':'XBTUSDT','ETH':'ETHUSDT'}

def fetch_klines(asset, tf, limit=720):
    """Fetch up to 720 OHLCV candles for the given asset + timeframe."""
    pair = PAIRS[asset]
    interval = TF_MIN[tf]
    url = f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval={interval}"
    req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode())
    if d.get('error'):
        raise RuntimeError(f"Kraken API error: {d['error']}")
    res = d['result']
    pair_key = next(k for k in res if k != 'last')
    # Kraken row: [time, open, high, low, close, vwap, volume, count]
    rows = res[pair_key][-limit:]
    return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]),
             float(r[4]), float(r[6])) for r in rows]

# ════════════════════════════════════════════════════════════════
#  INDICATOR HELPERS  (ported from the Pine Script logic)
# ════════════════════════════════════════════════════════════════

def ema(src, length):
    out = [None] * len(src)
    if not src: return out
    k = 2.0 / (length + 1)
    out[0] = src[0]
    for i in range(1, len(src)):
        out[i] = src[i] * k + out[i-1] * (1-k)
    return out

def ema_safe(src, length):
    """EMA tolerant of None entries (e.g. EMA-of-RSI)."""
    n = len(src); out = [None] * n
    if n == 0: return out
    k = 2.0 / (length + 1)
    seed = next((i for i in range(n) if src[i] is not None), None)
    if seed is None: return out
    out[seed] = src[seed]
    for i in range(seed+1, n):
        out[i] = (src[i]*k + out[i-1]*(1-k)) if src[i] is not None else out[i-1]
    return out

def wilder_atr(highs, lows, closes, length):
    n = len(closes); out = [None]*n
    if n < 2: return out
    trs = [None]*n
    trs[0] = highs[0] - lows[0]
    for i in range(1, n):
        h,l,pc = highs[i], lows[i], closes[i-1]
        trs[i] = max(h-l, abs(h-pc), abs(l-pc))
    if n <= length: return out
    seed = sum(trs[1:length+1]) / length
    out[length] = seed
    for i in range(length+1, n):
        out[i] = (out[i-1]*(length-1) + trs[i]) / length
    return out

def rsi(closes, length=14):
    n = len(closes); out = [None]*n
    if n <= length: return out
    gains = [0.0]*n; losses = [0.0]*n
    for i in range(1, n):
        d = closes[i] - closes[i-1]
        gains[i]  = d if d > 0 else 0
        losses[i] = -d if d < 0 else 0
    avg_g = sum(gains[1:length+1]) / length
    avg_l = sum(losses[1:length+1]) / length
    out[length] = 100 - 100/(1 + avg_g/avg_l) if avg_l > 0 else 100
    for i in range(length+1, n):
        avg_g = (avg_g*(length-1) + gains[i]) / length
        avg_l = (avg_l*(length-1) + losses[i]) / length
        out[i] = 100 - 100/(1 + avg_g/avg_l) if avg_l > 0 else 100
    return out

def sma(src, length):
    n = len(src); out = [None]*n
    if n < length: return out
    s = sum(src[:length]); out[length-1] = s / length
    for i in range(length, n):
        s += src[i] - src[i-length]
        out[i] = s / length
    return out

def stdev_pop(src, length):
    n = len(src); out = [None]*n
    if n < length: return out
    s  = sum(src[:length])
    s2 = sum(x*x for x in src[:length])
    out[length-1] = ((s2/length) - (s/length)**2) ** 0.5
    for i in range(length, n):
        s  += src[i] - src[i-length]
        s2 += src[i]*src[i] - src[i-length]*src[i-length]
        var = (s2/length) - (s/length)**2
        out[i] = max(var, 0.0) ** 0.5
    return out

def fast_highest(src, length):
    n = len(src); out = [None]*n; dq = deque()
    for i in range(n):
        while dq and dq[0] <= i-length: dq.popleft()
        while dq and src[dq[-1]] <= src[i]: dq.pop()
        dq.append(i)
        if i >= length-1: out[i] = src[dq[0]]
    return out

def fast_lowest(src, length):
    n = len(src); out = [None]*n; dq = deque()
    for i in range(n):
        while dq and dq[0] <= i-length: dq.popleft()
        while dq and src[dq[-1]] >= src[i]: dq.pop()
        dq.append(i)
        if i >= length-1: out[i] = src[dq[0]]
    return out

# ════════════════════════════════════════════════════════════════
#  SIGNAL DETECTION  (mirrors the Pine `switch modeIn` block)
# ════════════════════════════════════════════════════════════════

PROFILES = {'sharp':(8,21), 'balanced':(21,55), 'smooth':(50,200)}

def compute_indicators(candles, cfg):
    """Returns a dict of all indicator series needed by check_signal."""
    n = len(candles)
    highs  = [c[2] for c in candles]
    lows   = [c[3] for c in candles]
    closes = [c[4] for c in candles]
    vols   = [c[5] for c in candles]
    fL, sL = PROFILES[cfg['profile']]
    return {
        'highs': highs, 'lows': lows, 'closes': closes, 'vols': vols,
        'atr':   wilder_atr(highs, lows, closes, cfg['atrLen']),
        'emaF':  ema(closes, fL),
        'emaS':  ema(closes, sL),
        'rsi':   rsi(closes, 14),
        'donHi': fast_highest(highs, cfg['don']),
        'donLo': fast_lowest(lows,  cfg['don']),
        'chHi':  fast_highest(highs, 50),
        'chLo':  fast_lowest(lows,  50),
        'volSma': sma(vols, 20),
    }

def check_signal_at(ind, i, cfg):
    """Returns ('long' | 'short' | None) for bar index i."""
    n = len(ind['closes'])
    if i < 60 or i >= n: return None
    if any(ind[k][i] is None for k in ('atr','emaF','emaS','rsi')): return None
    if ind['donHi'][i-1] is None or ind['donLo'][i-1] is None: return None
    if ind['volSma'][i] is None or ind['volSma'][i] <= 0: return None

    closes = ind['closes']; highs = ind['highs']; lows = ind['lows']
    emaF, emaS, rsiV = ind['emaF'], ind['emaS'], ind['rsi']
    midline = (emaF[i] + emaS[i]) / 2

    # Filters
    volRatio = ind['vols'][i] / ind['volSma'][i]
    passVol  = (not cfg['volFilt']) or volRatio >= 1.5
    passFlat = (ind['atr'][i] / closes[i] * 100) >= 0.20

    fi = cfg['fi']
    rsiUpper = 70 - 5*fi
    rsiLower = 30 + 5*fi

    tBull = emaF[i] > emaS[i] and rsiV[i] > 50 and closes[i] > midline
    tBear = emaF[i] < emaS[i] and rsiV[i] < 50 and closes[i] < midline
    pOL = (not cfg['oscByTrend']) or tBull
    pOS = (not cfg['oscByTrend']) or tBear

    longSig = shortSig = False
    mode = cfg['mode']
    donHi = ind['donHi']; donLo = ind['donLo']
    chHi  = ind['chHi'];  chLo  = ind['chLo']

    if mode == 'advanced':
        boL = highs[i] > donHi[i-1] and closes[i] > donHi[i-1]
        boS = lows[i]  < donLo[i-1] and closes[i] < donLo[i-1]
        # midline cross
        midPrev = (emaF[i-1] + emaS[i-1]) / 2
        swL = closes[i] > emaF[i] and closes[i-1] <= midPrev and closes[i] > midline
        swS = closes[i] < emaF[i] and closes[i-1] >= midPrev and closes[i] < midline
        longSig  = (boL or swL) and rsiV[i] < rsiUpper
        shortSig = (boS or swS) and rsiV[i] > rsiLower

    elif mode == 'standard':
        longSig  = highs[i] > donHi[i-1] and closes[i] > donHi[i-1] and rsiV[i] < rsiUpper
        shortSig = lows[i]  < donLo[i-1] and closes[i] < donLo[i-1] and rsiV[i] > rsiLower

    elif mode == 'classic':
        longSig  = closes[i-1] <= emaF[i-1] and closes[i] > emaF[i] and emaF[i] > emaS[i]
        shortSig = closes[i-1] >= emaF[i-1] and closes[i] < emaF[i] and emaF[i] < emaS[i]

    elif mode == 'channel':
        longSig  = closes[i] <= chLo[i]*1.002 and rsiV[i-1] < rsiLower and rsiV[i] >= rsiLower
        shortSig = closes[i] >= chHi[i]*0.998 and rsiV[i-1] > rsiUpper and rsiV[i] <= rsiUpper

    elif mode == 'oscillator':
        # G-Line (EMA-7 of RSI) crosses Red-Line (EMA-14 of RSI)
        gLine = ema_safe(rsiV, 7)
        rLine = ema_safe(rsiV, 14)
        if gLine[i] is None or rLine[i] is None: return None
        if gLine[i-1] is None or rLine[i-1] is None: return None
        gxUp = gLine[i-1] <= rLine[i-1] and gLine[i] > rLine[i]
        gxDn = gLine[i-1] >= rLine[i-1] and gLine[i] < rLine[i]
        longSig  = gxUp and rsiV[i] < rsiUpper
        shortSig = gxDn and rsiV[i] > rsiLower

    if longSig  and pOL and passVol and passFlat: return 'long'
    if shortSig and pOS and passVol and passFlat: return 'short'
    return None

def calc_tp_sl(entry, atr_val, cfg, is_long):
    direction = 1 if is_long else -1
    safeAtr = atr_val if atr_val and atr_val > 0 else entry * 0.005
    tp1 = entry + direction * safeAtr * cfg['tps'][0]
    tp2 = entry + direction * safeAtr * cfg['tps'][1]
    tp3 = entry + direction * safeAtr * cfg['tps'][2]
    tp4 = entry + direction * safeAtr * cfg['tps'][3]
    sl  = entry - direction * safeAtr * cfg['sl']
    return sl, tp1, tp2, tp3, tp4

# ════════════════════════════════════════════════════════════════
#  TRADE LIFECYCLE  (universal SL ratchet — TP1→BE, TP2→TP1, etc.)
# ════════════════════════════════════════════════════════════════

def update_open_trade(candles, trade):
    """Walks new candles since trade['last_bar'] checking for TP/SL hits.
       Returns (events_list, updated_trade_or_None_if_closed)."""
    events = []
    last_bar = trade.get('last_bar', trade['opened_bar'])
    is_long  = trade['side'] == 'long'

    for c in candles:
        bar_time = c[0]
        if bar_time <= last_bar: continue   # already processed
        h, l = c[2], c[3]

        # Check TPs in order
        if is_long:
            if not trade['tp1_hit'] and h >= trade['tp1']:
                trade['tp1_hit'] = True
                if not trade['be_moved']:
                    trade['sl'] = trade['entry']
                    trade['be_moved'] = True
                events.append(('tp1', trade['tp1'], bar_time))
            if trade['tp1_hit'] and not trade['tp2_hit'] and h >= trade['tp2']:
                trade['tp2_hit'] = True
                trade['sl'] = trade['tp1']
                events.append(('tp2', trade['tp2'], bar_time))
            if trade['tp2_hit'] and not trade['tp3_hit'] and h >= trade['tp3']:
                trade['tp3_hit'] = True
                trade['sl'] = trade['tp2']
                events.append(('tp3', trade['tp3'], bar_time))
            if trade['tp3_hit'] and not trade['tp4_hit'] and h >= trade['tp4']:
                trade['tp4_hit'] = True
                events.append(('tp4', trade['tp4'], bar_time))
            if l <= trade['sl']:
                events.append(('sl', trade['sl'], bar_time))
                trade['last_bar'] = bar_time
                return events, None    # trade closed
        else:  # short
            if not trade['tp1_hit'] and l <= trade['tp1']:
                trade['tp1_hit'] = True
                if not trade['be_moved']:
                    trade['sl'] = trade['entry']
                    trade['be_moved'] = True
                events.append(('tp1', trade['tp1'], bar_time))
            if trade['tp1_hit'] and not trade['tp2_hit'] and l <= trade['tp2']:
                trade['tp2_hit'] = True
                trade['sl'] = trade['tp1']
                events.append(('tp2', trade['tp2'], bar_time))
            if trade['tp2_hit'] and not trade['tp3_hit'] and l <= trade['tp3']:
                trade['tp3_hit'] = True
                trade['sl'] = trade['tp2']
                events.append(('tp3', trade['tp3'], bar_time))
            if trade['tp3_hit'] and not trade['tp4_hit'] and l <= trade['tp4']:
                trade['tp4_hit'] = True
                events.append(('tp4', trade['tp4'], bar_time))
            if h >= trade['sl']:
                events.append(('sl', trade['sl'], bar_time))
                trade['last_bar'] = bar_time
                return events, None
        last_bar = bar_time

    trade['last_bar'] = last_bar
    if trade['tp4_hit']:
        return events, None
    return events, trade

# ════════════════════════════════════════════════════════════════
#  ML SELF-LEARNING — Naive Bayes per-feature-bucket
# ════════════════════════════════════════════════════════════════

def vol_bucket(volRegime): return 0 if volRegime < 0.7 else (2 if volRegime > 1.3 else 1)
def rsi_bucket(r):         return 0 if r < 30 else 1 if r < 50 else 2 if r < 70 else 3
def ses_bucket(hr):        return 0 if hr < 7 else 1 if hr < 13 else 2 if hr < 21 else 3
def mode_bucket(m):
    return {'advanced':0,'standard':1,'classic':2,'channel':3,'oscillator':4}.get(m, 0)

def laplace_conf(wins, losses):
    return (wins + 1) / (wins + losses + 2)

def ml_predict(ml_state, vol_b, rsi_b, ses_b, mode_b):
    """Geometric mean of per-bucket confidences across 4 feature dimensions."""
    cV = laplace_conf(ml_state['vol'].get(str(vol_b),  [0,0])[0], ml_state['vol'].get(str(vol_b),  [0,0])[1])
    cR = laplace_conf(ml_state['rsi'].get(str(rsi_b),  [0,0])[0], ml_state['rsi'].get(str(rsi_b),  [0,0])[1])
    cS = laplace_conf(ml_state['ses'].get(str(ses_b),  [0,0])[0], ml_state['ses'].get(str(ses_b),  [0,0])[1])
    cM = laplace_conf(ml_state['mode'].get(str(mode_b),[0,0])[0], ml_state['mode'].get(str(mode_b),[0,0])[1])
    return (cV * cR * cS * cM) ** 0.25

def ml_update(ml_state, snapshot, won):
    """On trade close, credit (or debit ×penalty) each bucket touched."""
    delta = 1 if won else ML_PENALTY_SL
    idx = 0 if won else 1
    for dim, key in [('vol','vol_b'),('rsi','rsi_b'),('ses','ses_b'),('mode','mode_b')]:
        bucket = str(snapshot[key])
        if bucket not in ml_state[dim]:
            ml_state[dim][bucket] = [0, 0]
        ml_state[dim][bucket][idx] += delta

# ════════════════════════════════════════════════════════════════
#  TELEGRAM
# ════════════════════════════════════════════════════════════════

def deliver(payload, fallback_text):
    """Sends an alert via the configured channel.
       Priority: WEBHOOK_URL (Make.com etc.) > Telegram Bot API > stdout dry-run."""
    if WEBHOOK_URL:
        body = json.dumps(payload).encode()
        req = urllib.request.Request(WEBHOOK_URL, data=body,
                                     headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status == 200
        except Exception as e:
            print(f"[webhook-error] {e}")
            return False
    if TG_TOKEN and TG_CHAT_ID:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        body = json.dumps({
            'chat_id': TG_CHAT_ID,
            'text': fallback_text,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True,
        }).encode()
        req = urllib.request.Request(url, data=body, headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status == 200
        except urllib.error.HTTPError as e:
            print(f"[TG-error] {e.code}: {e.read().decode()[:200]}")
            return False
        except Exception as e:
            print(f"[TG-error] {e}")
            return False
    print(f"[dry-run] {fallback_text[:120]}…")
    return False

def fmt(price):
    if price >= 1000:    return f"{price:,.2f}"
    if price >= 1:       return f"{price:,.4f}"
    return f"{price:.6g}"

def fmt_pct(pct):
    return f"{pct:+.2f}%"

def alert_entry(asset, tf, side, entry, sl, tps, ml_conf, preset_name):
    """Beautifully formatted entry alert — visual hierarchy + symmetrical layout."""
    is_long = side == 'long'
    bar     = "🟢" if is_long else "🔴"
    arrow   = "🟢" if is_long else "🔴"
    side_t  = "L O N G" if is_long else "S H O R T"

    # Risk distance for context
    risk_pct = abs(entry - sl) / entry * 100

    msg  = f"{bar}━━━━━━━━━━━━━━━━━━━━━━{bar}\n"
    msg += f"      <b>M i N D - S h o t</b>\n"
    msg += f"        <b>{side_t}</b>   ⚡<code>{LEVERAGE}x</code>\n"
    msg += f"{bar}━━━━━━━━━━━━━━━━━━━━━━{bar}\n\n"

    msg += f"📊  <code>{asset}/USD</code>   ⏱  <b>{tf}</b>\n"
    msg += f"🎯  <i>{preset_name}</i>\n"
    msg += f"🧠  ML Confidence  ·  <b>{ml_conf*100:.1f}%</b>\n\n"

    msg += f"▰▰▰▰  <b>POSITION</b>  ▰▰▰▰▰▰\n"
    msg += f"📍 <b>Entry</b>   <code>{fmt(entry)}</code>\n"
    msg += f"🛡 <b>Stop</b>    <code>{fmt(sl)}</code>   <i>(−{risk_pct*LEVERAGE:.2f}% @ {LEVERAGE}x)</i>\n\n"

    msg += f"▰▰▰▰▰  <b>TARGETS</b>  ▰▰▰▰▰\n"
    pcts = [50, 25, 15, 10]
    icons = ["✅", "✅", "✅", "🚀"]
    for i, (tp, pct, icon) in enumerate(zip(tps, pcts, icons)):
        gain = abs(tp - entry) / entry * 100 * LEVERAGE
        msg += f"{icon} <b>TP{i+1}</b>  <code>{fmt(tp)}</code>  ·  <i>{pct}%  →  +{gain:.1f}%</i>\n"

    msg += f"\n<i>💡 SL auto-moves: TP1→BE  ·  TP2→TP1  ·  TP3→TP2</i>"
    return msg


def alert_event(asset, tf, ev_type, price, entry, side, leverage):
    """Beautifully formatted TP/SL hit alert."""
    is_long = side == 'long'
    raw_pct = abs(price - entry) / entry * 100
    lev_pct = raw_pct * leverage

    if ev_type == 'sl':
        is_loss = (is_long and price < entry) or (not is_long and price > entry)
        if is_loss:
            bar = "🛡"
            title = "S T O P   L O S S"
            sub   = f"<b>−{lev_pct:.2f}%</b>"
            tail  = "✗ <b>INVALID</b> trade — no TP achieved"
        else:
            bar = "🛡"
            title = "B R E A K E V E N"
            sub   = f"<b>{'+0.00' if abs(lev_pct) < 0.1 else f'+{lev_pct:.2f}'}%</b>"
            tail  = "✓ <b>VALID</b> trade — TP1 secured prior"
    else:  # tp1/2/3/4
        bar = "🚀" if ev_type == 'tp4' else "✅"
        labels = {
            'tp1': "T P  1   P R I N T E D",
            'tp2': "T P  2   S E C U R E D",
            'tp3': "T P  3   L O C K E D",
            'tp4': "T P  4   ·   F U L L   R I D E",
        }
        title = labels[ev_type]
        sub   = f"<b>+{lev_pct:.2f}%</b>"
        next_sl_msg = {
            'tp1': "🛡 SL → moved to <b>Entry</b> (BE)",
            'tp2': "🛡 SL → moved to <b>TP1</b> (locked profit)",
            'tp3': "🛡 SL → moved to <b>TP2</b> (more locked)",
            'tp4': "🏆 <b>Trade complete</b>  ·  full target hit!",
        }
        tail = next_sl_msg[ev_type]

    msg  = f"{bar}━━━━━━━━━━━━━━━━━━━━━{bar}\n"
    msg += f"     <b>{title}</b>\n"
    msg += f"     {sub}   @  ⚡<code>{leverage}x</code>\n"
    msg += f"{bar}━━━━━━━━━━━━━━━━━━━━━{bar}\n\n"
    msg += f"📊  <code>{asset}/USD</code>  ·  <b>{tf}</b>\n"
    msg += f"💰  Price:  <code>{fmt(price)}</code>\n"
    msg += f"\n{tail}"
    return msg

# ════════════════════════════════════════════════════════════════
#  STATE PERSISTENCE
# ════════════════════════════════════════════════════════════════

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception as e:
            print(f"[state] Load error, starting fresh: {e}")
    return {}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))

def empty_ml(): return {'vol':{},'rsi':{},'ses':{},'mode':{},'total_trades':0}

# ════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════

def process_pair(asset, tf, state):
    key = f"{asset}_{tf}"
    cfg = PRESETS.get((asset, tf), DEFAULT_PRESET)
    preset_name = f"{asset} {tf} Optimal" if (asset, tf) in PRESETS else "Default"
    print(f"  ▸ {asset} {tf} (mode={cfg['mode']}, profile={cfg['profile']})")

    try:
        candles = fetch_klines(asset, tf)
    except Exception as e:
        print(f"    fetch failed: {e}")
        return

    st = state.setdefault(key, {'active_trade': None, 'last_signal_bar': 0, 'ml': empty_ml()})

    # ── Step 1: progress any open trade through new candles ──
    if st['active_trade']:
        events, updated = update_open_trade(candles, st['active_trade'])
        for ev_type, price, _t in events:
            ent = st['active_trade']['entry']
            side = st['active_trade']['side']
            raw_pct = abs(price - ent) / ent * 100
            payload = {
                'type':'event','event':ev_type,'asset':asset,'tf':tf,'side':side,
                'price':price,'entry':ent,'leverage':LEVERAGE,
                'pct':raw_pct, 'pct_leveraged': raw_pct * LEVERAGE,
            }
            deliver(payload, alert_event(asset, tf, ev_type, price, ent, side, LEVERAGE))
        if updated is None:
            # Trade closed — record outcome to ML
            tr = st['active_trade']
            won = tr['tp1_hit'] or tr['tp2_hit'] or tr['tp3_hit'] or tr['tp4_hit']
            ml_update(st['ml'], tr['ml_snap'], won)
            st['ml']['total_trades'] = st['ml'].get('total_trades', 0) + 1
            st['active_trade'] = None
            print(f"    trade closed: {'WIN' if won else 'LOSS'}, ML total={st['ml']['total_trades']}")
        else:
            st['active_trade'] = updated

    # ── Step 2: check for new signal on the latest CLOSED bar ──
    if st['active_trade'] is None and len(candles) > 60:
        last_bar = candles[-1][0]
        # Use the second-to-last candle as confirmed (last is in progress)
        confirm_idx = len(candles) - 2
        if candles[confirm_idx][0] > st['last_signal_bar']:
            ind = compute_indicators(candles, cfg)
            sig = check_signal_at(ind, confirm_idx, cfg)
            if sig:
                ent = candles[confirm_idx][4]
                atr_v = ind['atr'][confirm_idx] or ent * 0.005
                sl, t1, t2, t3, t4 = calc_tp_sl(ent, atr_v, cfg, sig == 'long')

                # ML snapshot
                volRegime = atr_v / (ind['atr'][confirm_idx-50] or atr_v) if confirm_idx >= 50 else 1.0
                hr_utc = datetime.fromtimestamp(candles[confirm_idx][0], tz=timezone.utc).hour
                snap = {
                    'vol_b':  vol_bucket(volRegime),
                    'rsi_b':  rsi_bucket(ind['rsi'][confirm_idx]),
                    'ses_b':  ses_bucket(hr_utc),
                    'mode_b': mode_bucket(cfg['mode']),
                }
                ml_conf = ml_predict(st['ml'], snap['vol_b'], snap['rsi_b'], snap['ses_b'], snap['mode_b'])

                # ML gate (only if enough trades have closed for this pair)
                if st['ml']['total_trades'] >= ML_MIN_TRADES and ml_conf < ML_MIN_CONF:
                    print(f"    signal {sig} BLOCKED by ML (conf {ml_conf*100:.1f}% < {ML_MIN_CONF*100}%)")
                else:
                    payload = {
                        'type':'entry','side':sig.upper(),'asset':asset,'tf':tf,
                        'preset':preset_name,'ml_conf':round(ml_conf*100,1),
                        'leverage':LEVERAGE,
                        'entry':ent,'sl':sl,
                        'tp1':t1,'tp2':t2,'tp3':t3,'tp4':t4,
                        'text':alert_entry(asset, tf, sig, ent, sl, [t1,t2,t3,t4], ml_conf, preset_name),
                    }
                    deliver(payload, payload['text'])
                    st['active_trade'] = {
                        'side': sig, 'entry': ent, 'sl': sl,
                        'tp1': t1, 'tp2': t2, 'tp3': t3, 'tp4': t4,
                        'tp1_hit': False, 'tp2_hit': False, 'tp3_hit': False, 'tp4_hit': False,
                        'be_moved': False,
                        'opened_bar': candles[confirm_idx][0],
                        'last_bar':   candles[confirm_idx][0],
                        'ml_snap':    snap,
                    }
                    print(f"    NEW {sig} entry @ {fmt(ent)}  ML={ml_conf*100:.1f}%")

            st['last_signal_bar'] = candles[confirm_idx][0]

def run_one_poll(state):
    """Run a single full poll across all ACTIVE pairs."""
    for asset, tf in ACTIVE:
        process_pair(asset, tf, state)
    save_state(state)

def main():
    if WEBHOOK_URL:
        print(f"📡 Delivery: webhook ({WEBHOOK_URL[:50]}…)")
    elif TG_TOKEN and TG_CHAT_ID:
        print(f"📡 Delivery: Telegram bot direct (chat_id={TG_CHAT_ID})")
    else:
        print("⚠️  No WEBHOOK_URL or Telegram creds set — running DRY-RUN (alerts go to stdout)")
    print(f"MiND-Shot Engine — {datetime.now(tz=timezone.utc).isoformat()}")
    print(f"Active pairs: {len(ACTIVE)}  ·  Polls/run: {POLLS_PER_RUN}  ·  Interval: {POLL_INTERVAL_SEC}s")

    state = load_state()
    for poll_num in range(1, POLLS_PER_RUN + 1):
        print(f"\n── Poll {poll_num}/{POLLS_PER_RUN}  @  {datetime.now(tz=timezone.utc).strftime('%H:%M:%S')} UTC ──")
        try:
            run_one_poll(state)
        except Exception as e:
            print(f"    poll error: {e}")
        # Sleep between polls (skip after final iteration to exit cleanly)
        if poll_num < POLLS_PER_RUN:
            time.sleep(POLL_INTERVAL_SEC)
    print("\nDone.")

if __name__ == '__main__':
    main()
