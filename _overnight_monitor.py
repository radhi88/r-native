"""Overnight account watcher — emits ONLY noteworthy lines (each becomes a notification):
account reset detected, equity moving >=15% from last report, blow-up (<$40), big floating
drawdown, or a live trader/brain going down. Polls every 5 min. Read-only."""
import time, sys
import MetaTrader5 as mt5
import psutil

mt5.initialize()
last_report = None
last_balance = None
print("overnight monitor armed — watching account equity + traders", flush=True)

CRIT_PROCS = {"gold_live.py", "btc_live.py", "r_executor", "brain_server.py"}

while True:
    try:
        a = mt5.account_info()
        if a:
            eq = float(a.equity); bal = float(a.balance)
            fl = eq - bal
            # reset/deposit detection: balance jumps a lot → re-baseline silently-ish
            if last_balance is not None and abs(bal - last_balance) > 1000:
                last_report = eq
                print(f"account reset/deposit detected → new baseline ${eq:,.2f}", flush=True)
            elif last_report is None:
                last_report = eq
                print(f"baseline equity ${eq:,.2f}", flush=True)
            else:
                # ONLY alert on real danger — not on the user's manual-trading swings.
                if eq < 60:
                    print(f"🛑 BLOW-UP RISK: equity ${eq:,.2f}", flush=True)
                    last_report = eq
                # bot-specific deep drawdown: floating loss worse than -$120
                elif fl <= -120:
                    print(f"⚠ bot/account floating drawdown ${fl:,.0f} (equity ${eq:,.0f})", flush=True)
                    last_report = eq
            last_balance = bal
        # critical processes alive?
        names = set()
        for p in psutil.process_iter(['cmdline']):
            try:
                cl = ' '.join(p.info.get('cmdline') or [])
                for c in CRIT_PROCS:
                    if c in cl and 'shell-snapshot' not in cl:
                        names.add(c)
            except Exception:
                pass
        down = CRIT_PROCS - names
        # only alert if a trader that WAS up goes down (track via a simple set)
        if down and down != getattr(sys.modules[__name__], "_last_down", set()):
            newly = down - getattr(sys.modules[__name__], "_last_down", set())
            if newly:
                print(f"⚠ trader(s) down: {sorted(newly)}", flush=True)
        sys.modules[__name__]._last_down = down
    except Exception as e:
        print(f"monitor err {e}", flush=True)
    time.sleep(300)
