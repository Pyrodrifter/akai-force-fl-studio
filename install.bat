@echo off
rem Double-click to install the Akai Force Live Control script into FL Studio.
rem To remove it:  install.bat -Uninstall
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
