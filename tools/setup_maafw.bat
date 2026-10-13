@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

REM Install MaaFramework runtime into .\maafw\
REM Prefer: 1) explicit path  2) cached official zip  3) download v5.14.2 (match pip MaaFw)
REM Old BD2MAA\maafw may be older and will NOT work with current pip MaaFw bindings.

set "LOGDIR=%CD%\logs"
set "ERRLOG=%LOGDIR%\setup_maafw_errors.log"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

set "DEST=%CD%\maafw"
set "CACHE=%CD%\.cache"
set "VER=v5.14.2"
set "ZIPNAME=MAA-win-x86_64-%VER%.zip"
set "ZIP=%CACHE%\%ZIPNAME%"
set "EXTRACT=%CACHE%\maa_extract_%VER%"
set "SRC="

if not "%~1"=="" (
    set "SRC=%~1"
)

echo ========================================
echo   Setup MaaFramework %VER% -^> maafw\
echo ========================================
echo.

if not "%SRC%"=="" goto :copy_src

if not exist "%CACHE%" mkdir "%CACHE%"

if exist "%EXTRACT%\bin\MaaPiCli.exe" goto :use_extract

if exist "%ZIP%" goto :do_extract

echo Downloading official %ZIPNAME% ...
where curl >nul 2>nul
if errorlevel 1 (
    where gh >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Need curl or gh to download.
        echo Manual: https://github.com/MaaXYZ/MaaFramework/releases/tag/%VER%
        echo Save as %ZIP% then re-run this script.
        >>"%ERRLOG%" echo [%DATE% %TIME%] download tools missing
        pause
        exit /b 1
    )
    gh release download %VER% --repo MaaXYZ/MaaFramework --pattern "%ZIPNAME%" --dir "%CACHE%"
) else (
    curl -L -o "%ZIP%" "https://github.com/MaaXYZ/MaaFramework/releases/download/%VER%/%ZIPNAME%"
)
if not exist "%ZIP%" (
    echo [ERROR] Download failed
    >>"%ERRLOG%" echo [%DATE% %TIME%] download failed
    pause
    exit /b 1
)

:do_extract
echo Extracting...
if exist "%EXTRACT%" rmdir /s /q "%EXTRACT%"
mkdir "%EXTRACT%"
powershell -NoProfile -Command "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%EXTRACT%' -Force"
if not exist "%EXTRACT%\bin\MaaPiCli.exe" (
    echo [ERROR] Extract failed - bin\MaaPiCli.exe missing
    >>"%ERRLOG%" echo [%DATE% %TIME%] extract failed
    pause
    exit /b 1
)

:use_extract
set "SRC=%EXTRACT%\bin"
goto :copy_src

:copy_src
if not exist "%SRC%\MaaPiCli.exe" (
    if exist "%SRC%\bin\MaaPiCli.exe" set "SRC=%SRC%\bin"
)
if not exist "%SRC%\MaaPiCli.exe" (
    echo [ERROR] MaaPiCli.exe missing in: %SRC%
    >>"%ERRLOG%" echo [%DATE% %TIME%] MaaPiCli.exe missing in %SRC%
    pause
    exit /b 1
)
if not exist "%SRC%\MaaFramework.dll" (
    echo [ERROR] MaaFramework.dll missing - need full bin folder matching pip MaaFw
    pause
    exit /b 1
)

echo Source: %SRC%
echo Dest:   %DEST%
echo.

if exist "%DEST%" (
    echo Removing old maafw\ ...
    rmdir /s /q "%DEST%"
)
mkdir "%DEST%"

echo Copying runtime files...
xcopy /E /I /Y "%SRC%\*" "%DEST%\" >nul
if errorlevel 1 (
    echo [ERROR] xcopy failed
    >>"%ERRLOG%" echo [%DATE% %TIME%] xcopy failed from %SRC%
    pause
    exit /b 1
)

REM Agent binaries live in share\ in official zip
if exist "%EXTRACT%\share\MaaAgentBinary" (
    xcopy /E /I /Y "%EXTRACT%\share\MaaAgentBinary" "%DEST%\MaaAgentBinary\" >nul
)

if not exist "%DEST%\MaaPiCli.exe" (
    echo [ERROR] Copy finished but MaaPiCli.exe missing
    pause
    exit /b 1
)

> "%DEST%\README.txt" echo MaaFramework runtime %VER% ^(MaaPiCli + DLLs^).
>>"%DEST%\README.txt" echo Must match pip package MaaFw version for in-process studio.
>>"%DEST%\README.txt" echo Official: https://github.com/MaaXYZ/MaaFramework/releases/tag/%VER%

REM Drop full zip extract (bin+symbol+docs ~250MB). Keep .cache zip for offline reinstall.
if not "%EXTRACT%"=="" if exist "%EXTRACT%" (
    echo Removing extract cache: %EXTRACT%
    rmdir /s /q "%EXTRACT%"
)
if exist "%CACHE%\maa_extract" (
    echo Removing legacy extract: %CACHE%\maa_extract
    rmdir /s /q "%CACHE%\maa_extract"
)

echo.
echo OK: %DEST%\MaaPiCli.exe
echo Also: pip install "MaaFw==5.14.2"
echo Cache kept: %ZIP% ^(delete via clean.bat --deep if disk-tight^)
echo.
endlocal
exit /b 0
