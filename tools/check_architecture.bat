@echo off
setlocal
cd /d "%~dp0.."
python tools\check_architecture.py %*
exit /b %ERRORLEVEL%
