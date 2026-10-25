# -*- coding: utf-8 -*-
"""rnative_pb.py - R-Native signals as trainee playbooks (install into MT5\\employee next to repos_pb.py).

Radhi 2026-10-25: «انفذ صفقات عن طريق نظامي نفسه ... نربط معه متدربينها». R-Native (github.com/radhi88/r-native)
no longer sends orders; r_native/employee_link.py appends each entry to data/rnative/signals.jsonl. This module turns
those lines into votes for trainee.pb():

  rn_<strategy>  +1 buy / -1 sell on the first closed M1 bar after the signal (signal no older than MAX_AGE_S).

Every vote is graded by the trainee on paper like any playbook. A real demo order needs the playbook in armed of
data/trainee/playbook_gate.json (Radhi's yes) and then goes through the central gateway. Replays see no signals,
so rn_* votes are 0 there (nothing to look ahead into).
Hook in trainee.pb(), after repos_pb:
    try:
        import rnative_pb
        out.update(rnative_pb.votes(S, i))
    except Exception:
        pass
"""
from __future__ import annotations

import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INBOX = os.path.join(HERE, 'data', 'rnative', 'signals.jsonl')
MAX_AGE_S = 120          # a signal older than two minutes when its bar closes is stale
SYMBOL_PREFIX = 'XAUUSD'  # the trainee trades gold; other markets are kept for stats()
_STATE = {'offset': 0, 'pending': [], 'seen': set(), 'by_symbol': {}}


def _pull(path=INBOX):
    """Read lines appended since the last call (partial last line waits for the next call)."""
    st = _STATE
    try:
        size = os.path.getsize(path)
    except OSError:
        return
    if size < st['offset']:
        st['offset'] = 0
    with open(path, 'rb') as f:
        f.seek(st['offset'])
        data = f.read()
    end = data.rfind(b'\n') + 1
    st['offset'] += end
    for raw in data[:end].splitlines():
        try:
            row = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            continue
        if row.get('source') != 'r-native' or row.get('side') not in ('BUY', 'SELL') or row.get('id') in st['seen']:
            continue
        st['seen'].add(row['id'])
        sym = str(row.get('symbol', ''))
        st['by_symbol'][sym] = st['by_symbol'].get(sym, 0) + 1
        if sym.startswith(SYMBOL_PREFIX):
            st['pending'].append(row)


def votes(S, i, now=None, path=INBOX):
    """Votes for the M1 bar i that just closed. Each signal votes once."""
    try:
        _pull(path)
        close_t = float(S['t'][i]) + 60.0
        now = time.time() if now is None else now
        out, keep = {}, []
        for row in _STATE['pending']:
            ts = float(row.get('ts', 0))
            if ts > close_t:              # arrived after this bar closed: wait for the next bar
                keep.append(row)
                continue
            if close_t - ts > MAX_AGE_S or now - ts > MAX_AGE_S + 60:
                continue                  # stale, dropped
            name = str(row.get('strategy') or 'rn_signal')[:27]
            out[name] = 1 if row['side'] == 'BUY' else -1
        _STATE['pending'] = keep
        return out
    except Exception:
        return {}


def stats():
    """Signals seen per symbol since start (for the status / Telegram حالة line)."""
    return dict(_STATE['by_symbol'])
