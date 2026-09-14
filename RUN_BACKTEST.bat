@echo off
cd /d "%~dp0"
echo ==========================================
echo   Jingjia Backtest (last 19 trade days)
echo   Data: Tencent + EastMoney (free)
echo ==========================================
echo.
".venv\Scripts\python.exe" scripts\run_backtest.py --quick
echo.
echo ==========================================
echo   Done. Press any key to close.
echo ==========================================
pause >nul
