@echo off
chcp 65001 >nul
cd /d %~dp0

set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
  where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo ไม่พบ Python 3 - ติดตั้งจาก https://www.python.org/downloads/ แล้วรัน setup.bat
  pause
  exit /b 1
)

%PY% auto_export_gui.py %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
exit /b %RC%
