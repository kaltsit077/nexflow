@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

REM Copy PP-OCR onnx models into a MaaFW project.
REM Default target: projects\click_lab
REM Usage:
REM   tools\setup_ocr.bat
REM   tools\setup_ocr.bat "projects\my_game"
REM   tools\setup_ocr.bat "projects\my_game" "E:\path\to\ocr"

set "LOGDIR=%CD%\logs"
set "ERRLOG=%LOGDIR%\setup_ocr_errors.log"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

set "TARGET=%~1"
if "%TARGET%"=="" set "TARGET=projects\click_lab"

set "SRC=%~2"
if "%SRC%"=="" (
  if exist "E:\AAAmobile game\BD2MAA\resource\model\ocr\det.onnx" (
    set "SRC=E:\AAAmobile game\BD2MAA\resource\model\ocr"
  )
)

echo ========================================
echo   Setup OCR models -^> %TARGET%\resource\model\ocr
echo ========================================
echo.

if "%SRC%"=="" (
  echo [ERROR] No OCR source found.
  echo Download from: https://github.com/MaaXYZ/MaaCommonAssets/tree/main/OCR
  echo Then: tools\setup_ocr.bat "projects\click_lab" "D:\OCR\zh_cn"
  >>"%ERRLOG%" echo [%DATE% %TIME%] OCR source missing
  pause
  exit /b 1
)

if not exist "%SRC%\det.onnx" (
  echo [ERROR] det.onnx missing in: %SRC%
  >>"%ERRLOG%" echo [%DATE% %TIME%] det.onnx missing
  pause
  exit /b 1
)

set "DEST=%CD%\%TARGET%\resource\model\ocr"
if not exist "%DEST%" mkdir "%DEST%"

copy /Y "%SRC%\det.onnx" "%DEST%\" >nul
copy /Y "%SRC%\rec.onnx" "%DEST%\" >nul
if exist "%SRC%\keys.txt" copy /Y "%SRC%\keys.txt" "%DEST%\" >nul

if not exist "%DEST%\det.onnx" (
  echo [ERROR] copy failed
  >>"%ERRLOG%" echo [%DATE% %TIME%] OCR copy failed
  pause
  exit /b 1
)

echo OK: %DEST%
echo Next: open projects\click_lab\DEV.md and run MaaPiCli / MXU
echo.
endlocal
exit /b 0
