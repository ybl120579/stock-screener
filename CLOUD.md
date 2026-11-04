# 云端版：不用电脑，手机随时随地打开

本地版（`mobile/app.py`）要电脑开着、同一个 WiFi。云端版把「跑筛选」和「看页面」都搬到云上：

```
GitHub Actions（每天北京时间 15:40 自动跑）
      │  ① python build_static.py  ← 拉东财数据、跑四条件、算出冷度分
      │  ② 把结果写进 docs/data/*.json
      ▼
GitHub 仓库（自动提交一次）
      ▼
GitHub Pages（静态托管，7×24 在线）
      ▼
手机浏览器 / 加到主屏的图标     ← 任何网络都能打开，家里电脑可以关着
```

前端是同一套代码：`ui/app.js` 启动时先探测 `api/status`——

- 探测成功 → **live 模式**，走本地服务（`mobile/app.py`，能手动刷新、能看实时状态）
- 探测失败 → **static 模式**，改读 `data/list.json` 等静态文件（就是 Pages 上的形态）

所以同一个 `index.html` 放在哪里都能跑，不用维护两份。

## 站点结构

```
docs/
├── index.html  style.css  app.js  sw.js  manifest.webmanifest  icon-*.png
└── data/
    ├── list.json               最新名单（含 16 只的 60 根 K 线，约 60KB）
    ├── archive/YYYY-MM-DD.json 每个交易日的完整快照
    ├── history.json           有哪些日期（页面顶部的日期标签）
    └── status.json            上次生成时间、下次更新时间
```

## 每天是怎么更新的

`.github/workflows/daily.yml`：

1. `cron: 40 7 * * 1-5`（UTC 07:40 = 北京时间 15:40，周一到周五）
2. 装 `requirements-ci.txt`（requests / pandas / akshare）
3. `python build_static.py --if-missing`——当天已有快照就跳过，节假日不会重复跑
4. 有变化就 `git commit` + `git push`，Pages 自动重新发布

GitHub 的定时任务偶尔会延迟几分钟到半小时才触发，对**日线**数据没有影响。如果那天 GitHub 完全没跑（平台故障），第二天会照常更新，也可以手动补。

## 已经部署好的地址

| 用途 | 地址 |
| --- | --- |
| **手机打开（收藏这个）** | https://ybl120579.github.io/stock-screener/ |
| 仓库 | https://github.com/ybl120579/stock-screener |
| 每天跑的任务 | 仓库 → Actions → 「每日选股」 |

手机上打开后用浏览器的「分享 → 添加到主屏幕」，桌面就会出现「首板·低冷度」图标，点开像 App 一样全屏。

> 站点是公开的（GitHub Pages 免费版只能公开），里面只有公开行情算出来的名单，不含任何密钥。想私密可以改成 Cloudflare Pages + 密码，或者只在本地用。

## 从零再部署一次（换账号时）

1. **推代码**：`python tools/deploy_github.py --token <你的token> --repo stock-screener`
2. **开 Pages**：仓库 → Settings → Pages → Source 选 `Deploy from a branch`，分支 `main`、目录 `/docs`
3. 等 1～2 分钟，打开 `https://<用户名>.github.io/stock-screener/`

`--token` 需要 `repo` + `workflow` 两个权限，用完就可以在 GitHub → Settings → Developer settings → Personal access tokens 里删掉；脚本只在内存里用它，不写进 `.git/config`。

## 手动补跑 / 重跑

仓库 → Actions → 「每日选股」→ Run workflow：

- 默认勾选「force」以外的行为：当天已有快照就跳过
- 勾上 `force`：无视已有快照，强制重跑（适合修了参数想立刻看结果）

## 想改筛选条件

改 `config.json`（阈值、权重都在里面）→ 提交 → 手动 Run workflow（勾 force）。

## 常见问题

**Actions 跑失败了**
点进那次运行看日志。最常见是数据源临时抽风（东财的接口对云机房 IP 偶尔返回空数据）。现在已经有三层兜底：

1. K 线接口在 4 个镜像域名之间轮换，`data: null` 也会换域名重试；
2. 交易日历拿不到时改用 akshare 的新浪日历，再不行用工作日近似；
3. 整个筛选失败会等 20 秒重跑一次；**当天 20:10 还有一次兜底定时任务**，15:40 那次失败它会自动补上。

所以偶尔失败一般不用管；连续两天没更新再看日志。

**Pages 打开是 404**
Settings → Pages 里确认分支和目录选的是 `main` / `/docs`，且 `docs/index.html` 确实推上去了。

**手机上打开很慢**
GitHub Pages 走的是海外 CDN，国内访问偶尔慢。可用性一般够用；如果实在慢，把仓库再挂一份到 Cloudflare Pages（同一个 `docs/` 目录，免费），或换成国内静态托管。

**数据要保密吗**
仓库是公开的，但里面只有公开行情算出来的名单，没有你的账号密钥。你的 API 密钥一个都不在这里（东财接口本身不需要 key）。
