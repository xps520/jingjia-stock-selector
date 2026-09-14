@echo off
cd /d "%~dp0"
echo ==========================================
echo   Jingjia Auction Stock Picker (Daily)
echo   Data: Tencent + EastMoney (free)
echo ==========================================
echo.
".venv\Scripts\python.exe" scripts\run_daily.py %*
echo.
echo ==========================================
echo   Done. Press any key to close.
echo ==========================================
pause >nul
