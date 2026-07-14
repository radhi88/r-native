cd C:\Users\Radhi\MT5

# 1) Export trained profiles to MT5 Common Files
.\.venv\Scripts\python.exe Build_MT5_Tester_Profile_CSV.py

# 2) Copy this EA manually:
# Agentic_Profiled_Grid_Tester_GOLD.mq5
# to:
# MQL5\Experts\
#
# Then Compile from MetaEditor.

# MT5 Strategy Tester settings:
# Expert: Agentic_Profiled_Grid_Tester_GOLD
# Symbol: XAUUSDm
# Timeframe: M1
# Model: Every tick based on real ticks
# Date: Last 1 year
