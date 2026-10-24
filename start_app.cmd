@echo off
cd /d "%~dp0"
"C:\Python313\python.exe" -m goxtrade.runtime.manage_app start
if errorlevel 1 (
    echo.
    echo GoXTrade did not start. Review the error above.
    pause
    exit /b 1
)
echo.
echo Open http://localhost:8502 in your browser.
echo Trading controls retain their saved pause state.
pause
