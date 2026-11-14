@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    set "ADMISSIONS_PYTHON=%~dp0.venv\Scripts\python.exe"
) else (
    set "ADMISSIONS_PYTHON=python"
)
"%ADMISSIONS_PYTHON%" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
set "ADMISSIONS_EXIT=%ERRORLEVEL%"
pause
exit /b %ADMISSIONS_EXIT%
