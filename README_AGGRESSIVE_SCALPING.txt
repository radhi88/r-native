Aggressive scalping patch

Replace these files into C:\Users\Radhi\MT5 with the same relative paths.

What changed:
- Scalping profile no longer hard-blocks trades because of spread.
- Jarvis spread override now works in paper/demo and is blocked in live.
- friday_auto_trader passes ignore_spread=True for scalping when AGGRESSIVE_SCALPING_IGNORE_SPREAD=True.
- Live broker execution remains blocked by the backend.
- Jarvis live mode command is forced back to paper.

Important:
High spread can destroy scalping expectancy. This patch is meant for Paper/Demo testing unless you later add a separate audited manual-confirmation live flow.

Chat commands after restart:
- فرايدي حولي الوضع إلى demo
- فرايدي استخدمي mt5
- فرايدي اختاري scalping
- فرايدي تجاهلي السبريد
- فرايدي نفذي إذا الصفقة مناسبة
