@echo off
chcp 936 >nul
title 选股系统 · 手机预览
cd /d "C:\Users\1\Documents\deepseek-harness\default-workspace\stock-screener"
set "PY=C:\Users\1\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"
echo ==================================================
echo   选股系统手机预览（手机需与本机同一 WiFi）
echo ==================================================
for /f "usebackq delims=" %%i in (`"%PY%" tools\lan_ip.py`) do set "IP=%%i"
echo   首板冷度 :  http://%IP%:8770/
echo   强 趋 势 :  http://%IP%:8770/trend/
echo ==================================================
echo   保持本窗口开启；关闭窗口即停止服务。
echo ==================================================
"%PY%" -m http.server 8770 --directory docs --bind 0.0.0.0
echo.
echo 服务已停止。按任意键关闭。
pause >nul
