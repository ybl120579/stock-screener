@echo off
chcp 65001 >nul
title 开机自启 · 取消
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) '首板冷度选股.lnk';" ^
  "if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Host '已删除开机启动项' }" ^
  "else { Write-Host '没有找到开机启动项，无需取消' }"
echo.
pause
