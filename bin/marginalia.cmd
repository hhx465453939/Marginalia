@echo off
rem Marginalia launcher (Windows)
rem PYTHONUTF8=1 是必须的：否则中文参数会被按 GBK 解码成乱码。
setlocal
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0..;%PYTHONPATH%"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 -X utf8 -m marginalia %*
) else (
  python -X utf8 -m marginalia %*
)
exit /b %ERRORLEVEL%
