@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Source / folder launcher. Errors -> logs\start_errors.log
REM Self-elevate so Win32 connect / after_launch click work on elevated helpers (MAA PC).

net session >nul 2>&1
if errorlevel 1 (
    echo Requesting Administrator for Game Runner...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "Start-Process -FilePath '%~f0' -Verb RunAs -WorkingDirectory '%~dp0'"
    exit /b 0
)

set "LOGDIR=%~dp0logs"
set "ERRLOG=%LOGDIR%\start_errors.log"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo ========================================
echo   Game Runner - source / folder mode
echo ========================================
echo   Entry: start.bat  (Administrator)
echo.

where python >nul 2>nul
if errorlevel 1 (
    call :fail "Python not found on PATH. Install Python 3.9+ and Add to PATH."
    goto :eof
)

echo [1/3] Checking Python packages...
python -c "import PySide6, psutil, numpy" >nul 2>nul
if errorlevel 1 (
    echo Installing requirements.txt ...
    python -m pip install --upgrade pip
    if errorlevel 1 (
        call :fail "pip upgrade failed"
        goto :eof
    )
    python -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        call :fail "pip install failed. Try mirror: pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple"
        goto :eof
    )
    python -c "import PySide6, psutil, numpy" >nul 2>nul
    if errorlevel 1 (
        call :fail "Import check failed for PySide6, psutil, numpy"
        goto :eof
    )
) else (
    echo [1/3] Packages OK
)

echo [2/3] Checking maafw runtime...
if not exist "%~dp0maafw\MaaPiCli.exe" (
    echo maafw\MaaPiCli.exe missing - running tools\setup_maafw.bat ...
    call "%~dp0tools\setup_maafw.bat"
    if not exist "%~dp0maafw\MaaPiCli.exe" (
        call :fail "maafw setup failed. Run tools\setup_maafw.bat manually."
        goto :eof
    )
)
if not exist "%~dp0maafw\MaaFramework.dll" (
    call :fail "maafw\MaaFramework.dll missing. Re-run tools\setup_maafw.bat"
    goto :eof
)
echo [2/3] maafw OK

echo [3/3] Starting UI (main.py)...
echo.
python "%~dp0main.py"
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" (
    call :fail "main.py exited with code %APP_EXIT%"
    goto :eof
)

endlocal
exit /b 0

:fail
set "REASON=%~1"
echo.
echo [ERROR] %REASON%
echo.
>>"%ERRLOG%" echo [%DATE% %TIME%] %REASON%
echo Error reason written to: %ERRLOG%
echo Tip: python tools\doctor.py
echo.
pause
endlocal
exit /b 1
