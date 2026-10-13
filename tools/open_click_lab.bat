@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

if not exist "maafw\MaaPiCli.exe" (
  echo Run tools\setup_maafw.bat first
  pause
  exit /b 1
)
if not exist "projects\click_lab\resource\model\ocr\det.onnx" (
  echo Run tools\setup_ocr.bat first
  pause
  exit /b 1
)

echo Open Notepad, type: 确认
echo Then in MaaPiCli choose controller Win32-Notepad and task OCR点确认
echo.
cd /d "%~dp0..\projects\click_lab"
"%~dp0..\maafw\MaaPiCli.exe"
endlocal
