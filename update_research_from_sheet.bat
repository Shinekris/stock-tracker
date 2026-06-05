@echo off
REM ============================================================
REM  update_research_from_sheet.bat
REM  Turns your downloaded Google Sheet into the app's research
REM  data and publishes it (local + online).
REM
REM  BEFORE running: download your Google Sheet as CSV and save it
REM  as  research_sheet.csv  in the portfolio folder.
REM ============================================================
cd /d C:\D-Drive\Personal\Finance\Stock\StockScreening

echo.
echo ============================================================
echo   UPDATE RESEARCH FROM GOOGLE SHEET
echo ============================================================
echo.

REM Check the sheet export exists
if not exist "research_sheet.csv" (
    echo ERROR: research_sheet.csv not found in this folder.
    echo.
    echo Please download your Google Sheet first:
    echo   File - Download - Comma-separated values
    echo   Save it as research_sheet.csv in:
    echo   C:\D-Drive\Personal\Finance\Stock\StockScreening
    echo.
    pause
    exit /b
)

echo Step 1: Converting the sheet into research_notes.csv...
python build_research_from_sheet.py

echo.
echo Step 2: Publishing (local is already updated; pushing online)...
git checkout -- data/tracker.db 2>nul
git pull --no-edit
git add research_notes.csv
git commit -m "Update research from Google Sheet"
git push

echo.
echo ============================================================
echo   Done.
echo   - Local app: refresh the dashboard to see the new ranking
echo   - Online app: updates in 1-2 minutes (Streamlit rebuild)
echo   Check above for any SKIPPED rows (bad ticker/score) to fix
echo   in the sheet.
echo ============================================================
echo.
pause
