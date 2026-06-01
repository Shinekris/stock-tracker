@echo off
REM ============================================================
REM  sync_down.bat  -  Pull the latest from GitHub into local
REM  Use this to bring the daily robot's fresh data to your PC.
REM ============================================================
cd /d C:\D-Drive\Personal\Finance\Stock\StockScreening

echo.
echo === Syncing DOWN: getting latest from the cloud ===
echo.

REM tracker.db is generated data - let the cloud version win
git checkout -- data/tracker.db 2>nul

git pull --no-edit

echo.
echo === Done. Your local copy now matches the cloud. ===
echo.
pause
