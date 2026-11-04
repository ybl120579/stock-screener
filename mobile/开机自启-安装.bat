@echo off
chcp 65001 >nul
title 开机自启 · 安装
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$dir = Split-Path -Parent '%~f0'; $bat = Join-Path $dir '启动手机App服务.bat';" ^
  "$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) '首板冷度选股.lnk';" ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk);" ^
  "$s.TargetPath = $bat; $s.WorkingDirectory = $dir; $s.WindowStyle = 7;" ^
  "$s.Description = '开机自动启动首板冷度选股 App 服务'; $s.Save();" ^
  "Write-Host ('已创建开机启动项：' + $lnk)"

echo.
echo  以后每次登录 Windows 会自动在后台启动服务（任务栏可见，最小化）。
echo  想取消自启，运行「取消开机自启.bat」。
echo.
pause
