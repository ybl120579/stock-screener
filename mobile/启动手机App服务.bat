@echo off
chcp 65001 >nul
title 首板冷度选股 · 手机 App 服务
cd /d "%~dp0"

set "PY=C:\Users\1\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo  首板回踩 · 低冷度选股  —  手机 App 服务
echo  ==========================================
echo.
echo  正在启动服务，请稍候…
echo  启动后保持本窗口开着即可，关闭窗口 = 停止服务。
echo.
echo  手机与电脑连同一个 WiFi，手机浏览器打开：
echo.

"%PY%" app.py %*

echo.
echo  服务已停止。按任意键关闭窗口。
pause >nul
