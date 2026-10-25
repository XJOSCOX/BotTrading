@echo off
cd /d "%~dp0"
set "GOX_PYTHON=C:\Python313\python.exe"
if exist "%~dp0.venv\Scripts\python.exe" set "GOX_PYTHON=%~dp0.venv\Scripts\python.exe"
"%GOX_PYTHON%" -m goxtrade.runtime.native_app menu
if errorlevel 1 pause
