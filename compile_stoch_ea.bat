@echo off
echo Compiling Stoch_Reversion_M3.mq5...

SET METAEDITOR="C:\Program Files\MetaTrader 5 EXNESS\metaeditor64.exe"
SET EA_SRC=C:\Users\Radhi\MT5\live_ea\Stoch_Reversion_M3.mq5
SET EXPERTS_DIR=C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\53785E099C927DB68A545C249CDBCE06\MQL5\Experts

REM First copy to Experts folder
copy /Y "%EA_SRC%" "%EXPERTS_DIR%\Stoch_Reversion_M3.mq5"
echo Copied to Experts folder.

REM Compile using MetaEditor CLI
%METAEDITOR% /compile:"%EXPERTS_DIR%\Stoch_Reversion_M3.mq5" /log:"%TEMP%\stoch_ea_compile.log"
echo.
echo Compilation done. Log: %TEMP%\stoch_ea_compile.log
type "%TEMP%\stoch_ea_compile.log" 2>nul
echo.
pause
