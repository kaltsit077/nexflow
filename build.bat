@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Packaging deferred. Daily: start.bat. Later: build.bat --force (onedir).

set "NOPAUSE="
if /I "%~1"=="--no-pause" set "NOPAUSE=1"
if /I "%~2"=="--no-pause" set "NOPAUSE=1"
if /I "%GAME_RUNNER_NOPAUSE%"=="1" set "NOPAUSE=1"

set "FORCE="
if /I "%~1"=="--force" set "FORCE=1"
if /I "%~2"=="--force" set "FORCE=1"

if not defined FORCE (
    echo ========================================
    echo   Game Runner - packaging deferred
    echo ========================================
    echo.
    echo Primary workflow - folder / source:
    echo   1. pip install -r requirements.txt
    echo   2. tools\setup_maafw.bat
    echo   3. start.bat
    echo.
    echo Do NOT use dist\GameRunner.exe for daily work.
    echo When ready later: build.bat --force
    echo   produces dist\GameRunner\ folder release
    echo.
    echo Docs: docs\ and README.md
    echo.
    if not defined NOPAUSE pause
    endlocal
    exit /b 0
)

set "LOGDIR=%~dp0logs"
set "ERRLOG=%LOGDIR%\build_errors.log"
set "BUILDLOG=%LOGDIR%\build_last.log"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo ========================================
echo   Game Runner - FORCE folder release
echo ========================================
echo Log: %BUILDLOG%
echo.

where python >nul 2>nul
if errorlevel 1 (
    call :fail "Python not found on PATH."
    goto :eof
)

python -c "import PySide6, psutil, maa, numpy" >nul 2>nul
if errorlevel 1 (
    python -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (call :fail "pip install failed" & goto :eof)
)

python -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    python -m pip install "pyinstaller>=6.0"
    if errorlevel 1 (call :fail "pyinstaller install failed" & goto :eof)
)

taskkill /F /IM GameRunner.exe >nul 2>nul
timeout /t 1 /nobreak >nul
if exist "build" rmdir /s /q "build"
if exist "dist\GameRunner" rmdir /s /q "dist\GameRunner"
if exist "dist\GameRunner.exe" del /f /q "dist\GameRunner.exe"

echo Running PyInstaller onedir ...
echo -------- build start %DATE% %TIME% -------- > "%BUILDLOG%"
python -m PyInstaller --noconfirm --clean "%~dp0game_runner.spec" >> "%BUILDLOG%" 2>&1
if errorlevel 1 (
    type "%BUILDLOG%"
    call :fail "PyInstaller failed. See logs\build_last.log"
    goto :eof
)

if not exist "%~dp0dist\GameRunner\GameRunner.exe" (
    call :fail "dist\GameRunner\GameRunner.exe missing"
    goto :eof
)

if exist "%~dp0maafw\MaaPiCli.exe" (
    echo Copy maafw to dist\GameRunner\maafw ...
    python "%~dp0tools\_copy_maafw_to_dist.py"
)

> "%~dp0dist\GameRunner\HOW_TO_RUN.txt" echo Game Runner folder release
>>"%~dp0dist\GameRunner\HOW_TO_RUN.txt" echo 1. Keep this whole folder together
>>"%~dp0dist\GameRunner\HOW_TO_RUN.txt" echo 2. Run GameRunner.exe inside this folder
>>"%~dp0dist\GameRunner\HOW_TO_RUN.txt" echo 3. maafw must sit next to the exe
>>"%~dp0dist\GameRunner\HOW_TO_RUN.txt" echo 4. Prefer repo start.bat until product is done

echo.
echo FORCE build OK: %~dp0dist\GameRunner\
echo Daily work still: start.bat
echo.
if not defined NOPAUSE pause
endlocal
exit /b 0

:fail
echo.
echo [ERROR] %~1
>>"%ERRLOG%" echo [%DATE% %TIME%] %~1
if not defined NOPAUSE pause
endlocal
exit /b 1
