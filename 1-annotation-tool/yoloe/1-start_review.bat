@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM Grounding review UI (Windows)
REM Usage:
REM   double-click this file
REM   1-start_review.bat --port 8090
REM   1-start_review.bat --dataset D:\data\your_dataset
REM Close this window to stop the server and free THIS port.
REM Multi-instance: if PORT busy, auto use PORT+1 / +2 ... (keeps other windows).
REM
REM Python resolve order:
REM   1) .\runtime\python\python.exe        (portable zip)
REM   2) .\build\runtime\python\python.exe  (dev / pack runtime)
REM   3) conda env yulin
REM   4) python on PATH
REM NOTE: keep this .bat ASCII-only. UTF-8 Chinese breaks cmd.exe on CN Windows.

cd /d "%~dp0"

REM ---- editable ----
set "VLLM_BASE_URL=http://113.31.108.24:8081/v1"
set "VLLM_MODEL=qwen3.6-35b-a3b"
set "DATASET="
set "PORT=8090"
set "PY_DEV=C:\Users\15959\.conda\envs\yulin\python.exe"
REM ------------------

:parse_args
if "%~1"=="" goto after_args
if /i "%~1"=="--port" (
  set "PORT=%~2"
  shift
  shift
  goto parse_args
)
if /i "%~1"=="--dataset" (
  set "DATASET=%~2"
  shift
  shift
  goto parse_args
)
echo Unknown arg: %~1
shift
goto parse_args

:after_args

set "PY="
if exist "%~dp0runtime\python\python.exe" (
  set "PY=%~dp0runtime\python\python.exe"
) else if exist "%~dp0build\runtime\python\python.exe" (
  set "PY=%~dp0build\runtime\python\python.exe"
) else if exist "%PY_DEV%" (
  set "PY=%PY_DEV%"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] python not found.
    echo   Portable zip: runtime\python\
    echo   Dev tree:     build\runtime\python\
    echo   Or install Python / fix PY_DEV= in this bat.
    pause
    exit /b 1
  )
  set "PY=python"
)

"%PY%" -c "import flask" 2>nul
if errorlevel 1 (
  echo Installing: flask pillow tqdm requests ...
  "%PY%" -m pip install flask pillow tqdm requests -q
  if errorlevel 1 (
    echo [ERROR] pip install failed.
    pause
    exit /b 1
  )
)

echo.
echo   Grounding review UI
echo   preferred port: %PORT%  (auto +1 if busy)
if defined DATASET (
  echo   dataset: %DATASET%
) else (
  echo   dataset: not set, pick in UI
)
echo   vLLM: %VLLM_BASE_URL%
echo   model: %VLLM_MODEL%
echo   python: %PY%
echo   Close this window to free THIS instance port
echo.

if not exist "%~dp0util\win_job_run.ps1" (
  echo [ERROR] missing util\win_job_run.ps1
  pause
  exit /b 1
)

REM Job Object: closing console kills python child; port auto-increments if busy
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0util\win_job_run.ps1" -Port %PORT% -Dataset "%DATASET%" -Python "%PY%" -OpenBrowser
set "ERR=%ERRORLEVEL%"

echo.
if not "%ERR%"=="0" (
  echo Service exited, code %ERR%
) else (
  echo Service exited, this instance port freed
)
pause
endlocal & exit /b %ERR%
