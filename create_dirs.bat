@echo off
cd /d C:\Users\Radhi\MT5\src\mt5_ai
echo Creating directories...
echo.

mkdir strategies
if exist strategies echo ✓ strategies created
mkdir learning
if exist learning echo ✓ learning created
mkdir genetics
if exist genetics echo ✓ genetics created
mkdir integrations
if exist integrations echo ✓ integrations created
mkdir interfaces
if exist interfaces echo ✓ interfaces created
mkdir utils
if exist utils echo ✓ utils created

echo.
echo All directories created successfully!
