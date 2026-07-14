@echo off
chcp 65001 >nul
title R Trader - تشغيل الأسطول الكامل
echo.
echo ========================================================
echo    R Trader - تشغيل الاسطول الكامل عبر الوصي
echo ========================================================
echo.
echo [1/2] الرابح اولا: الحارس (gold_level_sentinel - الكود الرابح) ...
start "" "C:\Users\Radhi\MT5\.venv\Scripts\pythonw.exe" "C:\Users\Radhi\MT5\gold_level_sentinel.py"
timeout /t 3 >nul
echo [2/2] الوصي (watchdog) - يشغل باقي المحركات خلال دقيقة...
start "" "C:\Users\Radhi\MT5\.venv\Scripts\pythonw.exe" "C:\Users\Radhi\MT5\watchdog_guard.py"
echo.
echo تم. الوصي يشغل الان:
echo    - المحركات: الحارس + حارس العملات + قناص المجلس + R Core
echo    - الخدمات:  المعالج الذاتي + منمي المعرفة + مشرح الصفقات + ماسح الحافة + معدن اليد
echo    - الحاجز:   master_floor + kill_switch (الحماية)
echo    - الواجهة:  الكوكبيت  http://127.0.0.1:8020   +   المخ  /rt/brain
echo.
echo ملاحظة: تاكد ان MT5 (Exness) شغال اولا (يبدا تلقائيا مع الجهاز).
echo لاعادة تطويري ذاتيا: افتح Claude Code في هذا المجلد واكتب:   /loop
echo.
timeout /t 12
