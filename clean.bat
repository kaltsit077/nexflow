@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Clean caches / build / optional packaging leftovers.
REM Keeps: source tree, maafw\, library\, .cache\*.zip (unless --deep)

echo ========================================
echo   Game Runner - clean
echo ========================================
echo.

set "DEEP="
if /I "%~1"=="--deep" set "DEEP=1"
if /I "%~1"=="--no-pause" if /I "%~2"=="--deep" set "DEEP=1"
if /I "%~2"=="--deep" set "DEEP=1"

taskkill /F /IM GameRunner.exe >nul 2>nul

echo [1/5] __pycache__ / *.pyc ...
for /d /r %%D in (__pycache__) do @if exist "%%D" rd /s /q "%%D"
del /s /q *.pyc >nul 2>nul

echo [2/5] PyInstaller build\ ...
if exist "build" rd /s /q "build"

echo [3/5] logs\ ...
if exist "logs" (
  del /q "logs\*.*" >nul 2>nul
  for /d %%D in ("logs\*") do rd /s /q "%%D" >nul 2>nul
)

echo [4/5] dist packaging leftovers (daily work uses start.bat, not dist\)...
if exist "dist\GameRunner.exe" del /f /q "dist\GameRunner.exe"
if exist "dist\GameRunner" rd /s /q "dist\GameRunner"
if exist "dist\maafw" rd /s /q "dist\maafw"
if exist "dist\logs" rd /s /q "dist\logs"
if exist "dist\projects" rd /s /q "dist\projects"
if exist "dist\scripts" rd /s /q "dist\scripts"
if exist "dist\library" rd /s /q "dist\library"
if exist "dist\config.json" del /f /q "dist\config.json"
if exist "dist\history.json" del /f /q "dist\history.json"
if exist "dist\HOW_TO_RUN.txt" del /f /q "dist\HOW_TO_RUN.txt"

echo [5/5] .cache extracts / tool_dl (keep zip unless --deep)...
if exist ".cache\maa_extract" rd /s /q ".cache\maa_extract"
for /d %%D in (".cache\maa_extract_*") do rd /s /q "%%D"
if exist ".cache\tool_dl" rd /s /q ".cache\tool_dl"
if defined DEEP if exist ".cache" (
  echo       --deep: remove .cache zip downloads
  del /f /q ".cache\*.zip" >nul 2>nul
  del /f /q ".cache\*.7z" >nul 2>nul
)

echo.
echo Done. Use start.bat to run from source.
echo Packaging later: build.bat --force
echo.
set "NOPAUSE="
if /I "%~1"=="--no-pause" set "NOPAUSE=1"
if /I "%~2"=="--no-pause" set "NOPAUSE=1"
if /I "%GAME_RUNNER_NOPAUSE%"=="1" set "NOPAUSE=1"
if not defined NOPAUSE pause
endlocal
exit /b 0
