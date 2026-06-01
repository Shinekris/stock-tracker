@echo off
REM ============================================================
REM  sync_up.bat  -  Push your local changes up to GitHub
REM  Streamlit then auto-rebuilds, so the online app updates.
REM  Handles the daily-robot conflict automatically.
REM ============================================================
cd /d C:\D-Drive\Personal\Finance\Stock\StockScreening

echo.
echo === Syncing UP: sending your changes to the cloud ===
echo.

REM 1. Discard local generated-data changes so pull can't conflict
git checkout -- data/tracker.db 2>nul

REM 2. Pull any robot commits first (no editor prompt)
git pull --no-edit

REM 3. Stage everything and commit with a timestamped message
git add .
git commit -m "Local update %DATE% %TIME%"

REM 4. Push to GitHub (Streamlit auto-rebuilds from here)
git push

echo.
echo === Done. The online app will refresh in a minute or two. ===
echo.
pause
