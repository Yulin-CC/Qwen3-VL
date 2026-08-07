@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>nul

REM ============================================================
REM  维护者一键打包入口（双击本文件即可）
REM  真正逻辑: build\util\build_portable.ps1
REM  产物:     build\0-dist\GroundingReview-portable-*.zip
REM  运行时:   build\runtime\python\
REM ============================================================

cd /d "%~dp0"
set "BUILD=%CD%"
cd /d "%~dp0.."
set "YOLOE=%CD%"
set "PS1=%BUILD%\util\build_portable.ps1"

echo.
echo ========================================
echo   Grounding 检验工具 - 一键打包
echo ========================================
echo   yoloe: %YOLOE%
echo   build: %BUILD%
echo.

if not exist "%PS1%" (
  echo [ERROR] 找不到 build\util\build_portable.ps1
  pause
  exit /b 1
)

set "EXTRA="
if exist "%BUILD%\runtime\python\python.exe" (
  echo [提示] 已检测到 build\runtime\python：跳过下载/重装，依赖已齐则跳过 pip
  echo        拷贝用 robocopy，压缩用 tar/快速 zip（比以前快很多）
  echo        若要强制重装 Python：删掉 build\runtime 后再运行
  set "EXTRA=-SkipPythonInstall"
  echo.
) else (
  echo [提示] 首次打包会：
  echo   1^) 下载便携 Python（GitHub，约 30-50MB，需联网）
  echo   2^) 解压到 build\runtime\python\
  echo   3^) pip 安装 flask / pillow 等
  echo   4^) 打出 build\0-dist\GroundingReview-portable-*.zip
  echo   首次可能要几分钟；之后再打包通常几十秒内。
  echo.
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %EXTRA%
set "ERR=%ERRORLEVEL%"

echo.
if not "%ERR%"=="0" (
  echo [失败] 打包出错，退出码 %ERR%
  echo 常见原因：没联网 / 杀软拦截 / 磁盘空间不足
  pause
  exit /b %ERR%
)

echo [成功] 把下面的 zip 发给同事即可（他们解压后双击 start.bat）
echo.
dir /b "%BUILD%\0-dist\GroundingReview-portable-*.zip" 2>nul
echo.

if exist "%BUILD%\0-dist" (
  echo 正在打开 build\0-dist 文件夹...
  start "" explorer "%BUILD%\0-dist"
)

pause
endlocal & exit /b 0
