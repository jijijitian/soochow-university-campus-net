@echo off
rem ============================================================
rem  Campus network auto-login - run from source (foreground)
rem  Close this window to stop. Requires Python 3.9+.
rem ============================================================
cd /d "%~dp0"
python app.py %*
if errorlevel 1 pause