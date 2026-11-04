@echo off
chcp 65001 >nul
title 放行手机访问 · 需要管理员
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
  echo 需要管理员权限，正在申请（请在弹窗里点“是”）…
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

netsh advfirewall firewall delete rule name="首板冷度选股-8765" >nul 2>&1
netsh advfirewall firewall add rule name="首板冷度选股-8765" dir=in action=allow protocol=TCP localport=8765 >nul
if errorlevel 1 (
  echo 设置失败，请确认当前窗口是管理员权限。
) else (
  echo.
  echo  已放行 Windows 防火墙的 TCP 8765 端口，手机现在可以访问了。
  echo  只放行一次即可，重装系统或换网络环境后再运行本文件。
)
echo.
pause
