@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
python tools\doctor.py %*
set "EC=%ERRORLEVEL%"
if /I not "%~1"=="--no-pause" if /I not "%GAME_RUNNER_NOPAUSE%"=="1" pause
exit /b %EC%
