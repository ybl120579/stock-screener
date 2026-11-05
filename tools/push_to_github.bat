@echo off
chcp 65001 >nul
title 推送到 GitHub（自用）
cd /d "%~dp0.."

echo.
echo ==============================
echo   把本地改动推送到 GitHub
echo ==============================
echo.

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo [错误] 当前目录不是 git 仓库
  pause
  exit /b 1
)

echo [1/3] 检查改动...
git add -A
git diff --staged --quiet
if errorlevel 1 (
  echo [2/3] 提交改动...
  git -c core.quotepath=false commit -q -m "data: 本地快照"
) else (
  echo [2/3] 没有需要提交的改动
)

echo [3/3] 推送到 origin main（可能需要浏览器登录 GitHub）...
git push origin main
if errorlevel 1 (
  echo.
  echo [提示] 推送失败，常见原因：
  echo   - 没有登录 GitHub：在弹出的窗口里用浏览器登录即可
  echo   - 仓库地址不对：git remote -v 看一下
  echo   - 网络问题：重试一次
  pause
  exit /b 1
)

echo.
echo 推送成功。GitHub Actions 约 1 分钟后开始重建页面：
echo   https://ybl120579.github.io/stock-screener/
echo.
pause
