@echo off
rem Marginalia 一键部署包装（Windows）
rem
rem 只做三件事：找 Python、设 UTF-8、把参数转给 CLI。
rem 逻辑全在 marginalia/setup.py —— 脚本不做业务决策。
setlocal
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0..;%PYTHONPATH%"

rem 按「真的能跑」探测：Windows 上 python 常是应用商店占位符，
rem where 能找到但执行会报 “Python was not found ... install from the Microsoft Store”。
where py >nul 2>nul
if errorlevel 1 goto :try_python
py -3 -c "import sys" >nul 2>nul
if errorlevel 1 goto :try_python
py -3 -X utf8 -m marginalia setup %*
exit /b %ERRORLEVEL%

:try_python
where python >nul 2>nul
if errorlevel 1 goto :nopython
python -c "import sys" >nul 2>nul
if errorlevel 1 goto :nopython
python -X utf8 -m marginalia setup %*
exit /b %ERRORLEVEL%

:nopython
echo 找不到可用的 Python（需要 3.9+）。 1>&2
echo   -^> 安装后重试；或直接运行 python -m marginalia setup ^<参数^> 1>&2
exit /b 1
