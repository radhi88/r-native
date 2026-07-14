@ECHO OFF
REM MT5 AI Directory Setup Script
REM This batch file creates the required directory structure

SETLOCAL ENABLEDELAYEDEXPANSION

REM Navigate to the target directory
CD /D "C:\Users\Radhi\MT5\src\mt5_ai"

REM Create directories
ECHO Creating directories...
ECHO.

SET "dirs=strategies learning genetics integrations interfaces utils"

FOR %%D IN (%dirs%) DO (
    IF NOT EXIST %%D (
        MKDIR %%D
        ECHO ✓ Created: %%D
    ) ELSE (
        ECHO ✓ Already exists: %%D
    )
)

ECHO.
ECHO ======================================================================
ECHO All directories have been processed!
ECHO ======================================================================

REM Run verification with Python
ECHO.
ECHO Verifying with Python...
python.exe C:\Users\Radhi\MT5\mt5_auto_setup.py

PAUSE
