@echo off
setlocal EnableExtensions

REM Portable entry: double-click start.bat
REM Keep this file ASCII-only (UTF-8 Chinese breaks cmd.exe).

cd /d "%~dp0"

if not exist "%~dp0yoloe\1-start_review.bat" (
  echo [ERROR] missing yoloe\1-start_review.bat
  echo Unpack the full zip, then run start.bat from the package root.
  pause
  exit /b 1
)

if not exist "%~dp0yoloe\runtime\python\python.exe" (
  echo [ERROR] missing yoloe\runtime\python\python.exe
  echo This portable package is incomplete. Ask the maintainer to rebuild.
  pause
  exit /b 1
)

REM Open browser shortly after the server starts
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:8090/"

call "%~dp0yoloe\1-start_review.bat" %*
endlocal & exit /b %ERRORLEVEL%
