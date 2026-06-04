@echo off
REM Launch the PORTFOLIO tracker on port 8501
cd /d C:\D-Drive\Personal\Finance\Stock\StockScreening
start "Portfolio Tracker" cmd /c "python -m streamlit run app.py"
timeout /t 6 /nobreak >nul
start "" "http://localhost:8501"