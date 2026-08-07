# 手机版部署说明（GitHub 免费方案）

## 原理

代码放到 GitHub 私库，GitHub 的免费定时任务每天 20:00（北京时间）自动：
更新行情 → 因子检验 → 选股 → 推送到微信 → 更新手机网页。
手机完全独立，电脑不用开。

## 一次性准备（约 20 分钟）

### 1. 安装 GitHub Desktop（图形界面，免命令）

官网 https://desktop.github.com 下载安装，用你的 GitHub 账号登录。

### 2. 上传代码

1. 打开 GitHub Desktop → File → Add local repository → 选择 `E:\quant_v3` 文件夹
2. 点 Publish repository → 选 **Private（私库，推荐）** → Publish
3. 等上传完成（约 1~2 分钟，大数据文件已被自动排除）

### 3. 配置推送钥匙（微信收消息用，三选一即可，推荐企业微信）

在 GitHub 网页打开仓库 → Settings → Secrets and variables → Actions → New repository secret：

| 钥匙名 | 在哪拿 | 说明 |
|---|---|---|
| `WECHAT_WEBHOOK` | 企业微信 → 群聊 → 添加"群机器人"，复制 webhook 完整链接 | 推荐，安卓/苹果都能收 |
| `SERVERCHAN_KEY` | sct.ftqq.com 用 GitHub 登录后复制 SendKey | 通过微信公众号收 |
| `PUSHPLUS_TOKEN` | pushplus.plus 登录后复制 token | 通过微信公众号收 |

至少配一个。钥匙只存在 GitHub 的加密保险箱里，代码里看不到。

### 4. 打开手机网页（GitHub Pages）

仓库 Settings → Pages → Source 选 **GitHub Actions** → Save。
网页地址：`https://你的用户名.github.io/仓库名/`

### 5. 手动跑一次

仓库 Actions → 左侧"每日量化" → Run workflow → 首次运行约 20~40 分钟
（要下载 4 年多的行情数据；之后每天增量，约 10~20 分钟）。

运行完成后：
- 微信收到今日选股（如果配了钥匙）
- 手机浏览器打开上面的网页看到完整报告

## 日常使用

- 每天 20:00 自动跑，GitHub 定时偶尔延迟 1~2 小时属正常，次日开盘前收到即可
- 想手动触发：GitHub 手机 App → Actions → Run workflow
- 想改推送时间：改 `.github/workflows/daily.yml` 里的 cron（UTC 时间 = 北京时间 - 8）

## 常见问题

**网页打不开**：GitHub Pages 在国内偶尔不稳定，微信推送才是主通道；网页打不开不影响收消息。

**某天没收到**：先看仓库 Actions 里那次运行的日志；数据源从美国机房访问偶尔失败，第二天会自动重试。

**想不花钱也不依赖电脑**：本方案 0 元；如果哪天想更稳，可以平滑升级到国内云服务器（一年一两百元），代码不用改。

## 免责声明

本系统为量化研究工具，输出不构成投资建议；股市有风险，入市需谨慎。
