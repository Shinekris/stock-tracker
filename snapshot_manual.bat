@echo off
REM ============================================================
REM  snapshot.bat  -  Save a dated weekly copy of the database
REM  Builds a research archive so you can later check whether
REM  high-scoring stocks actually outperformed.
REM ============================================================
cd /d C:\D-Drive\Personal\Finance\Stock\StockScreening

echo.
echo === Weekly snapshot: archiving current data ===
echo.

REM Pull the latest data from the cloud first (so the snapshot is current)
git checkout -- data/tracker.db 2>nul
git pull --no-edit

REM Make sure the archive folder exists
if not exist "archive" mkdir archive

REM Build a date stamp: YYYY-MM-DD (locale-independent via PowerShell)
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%i

REM Copy the database with the date in the filename
copy /Y "data\tracker.db" "archive\tracker_%TODAY%.db" >nul

echo Saved snapshot:  archive\tracker_%TODAY%.db
echo.
echo Snapshots so far:
dir /b archive\tracker_*.db
echo.
echo === Done. ===
echo.
pause
