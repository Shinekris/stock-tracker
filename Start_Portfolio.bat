@echo off
REM ============================================================
REM  morning_launch.bat  -  Start the local dashboard each morning
REM  Pulls the latest data, starts Streamlit, opens the browser.
REM ============================================================
cd /d C:\D-Drive\Personal\Finance\Stock\StockScreening
 
REM Get the latest data from the cloud first (so morning view is fresh)
git checkout -- data/tracker.db 2>nul
git pull --no-edit
 
REM Start Streamlit in the background (new window)
start "Stock Tracker" cmd /c "python -m streamlit run app.py"
 
REM Give the server a few seconds to boot, then open the browser
timeout /t 6 /nobreak >nul
start "" "http://localhost:8501"