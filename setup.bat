@echo off
chcp 65001 >nul
cd /d %~dp0

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo ไม่พบ Python 3 - ติดตั้งจาก https://www.python.org/downloads/ แล้วลองใหม่
  pause
  exit /b 1
)

%PY% bootstrap.py %*
if errorlevel 1 pause
