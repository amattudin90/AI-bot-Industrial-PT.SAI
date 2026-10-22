@echo off
cd /d "%~dp0"
echo Starting Factory AI Control Tower...
echo Working directory: %CD%
echo.
.venv\Scripts\python.exe -m streamlit run app.py
echo.
echo App stopped. Press any key to close...
pause >nul
