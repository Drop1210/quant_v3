# 手机版部署说明（Drop1210 专属版）

## 原理

代码放到 GitHub 私库，GitHub 的免费定时任务每天 17:00（北京时间）自动：
更新行情 → 因子检验 → 选股 → 推送到微信 → 更新手机网页。
手机完全独立，电脑不用开。

## 仓库信息（已为你配好）

- 用户名：Drop1210
- 邮箱：360950551@qq.com
- 建议仓库名：quant_v3（私库）
- 手机网页地址（启用后）：https://drop1210.github.io/quant_v3/

## 一次性准备（约 20 分钟）

### 1. 安装 GitHub Desktop（图形界面，免命令）

官网 https://desktop.github.com 下载安装，用 Drop1210 账号登录。

### 2. 发布仓库（代码已在 E:\quant_v3 准备好，只差发布）

1. 打开 GitHub Desktop → File → Add local repository → 选择 `E:\quant_v3` 文件夹
2. 仓库名填 `quant_v3`，点 **Publish repository**
3. 勾选 **Keep this code private**（私库，推荐）→ Publish
4. 等上传完成（大数据文件已被自动排除，只有几 MB）

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
网页地址：`https://drop1210.github.io/quant_v3/`

### 5. 手动跑一次

仓库 Actions → 左侧"daily-quant" → Run workflow → 首次运行约 20~40 分钟
（要下载 4 年多的行情数据；之后每天增量，约 10~20 分钟）。

运行完成后：
- 微信收到今日选股（如果配了钥匙）
- 手机浏览器打开上面的网页看到完整报告

## 日常使用

- 每天 17:00 自动跑（约 10~15 分钟后收到推送），GitHub 定时偶尔延迟属正常，次日开盘前收到即可
- 想手动触发：GitHub 手机 App → Actions → Run workflow
- 想改推送时间：改 `.github/workflows/daily.yml` 里的 cron（UTC 时间 = 北京时间 - 8）

### 企业微信群机器人怎么建（推荐通道，5 分钟）

1. 手机装"企业微信"App，用微信登录（免费注册个人企业，选"企业"身份）
2. 创建一个群（哪怕只有自己），群名随意，比如"量化提醒"
3. 群里点右上角"..." → 群机器人 → 添加机器人 → 复制 Webhook 地址
4. 把完整的 `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...` 地址贴到 GitHub 的
   `WECHAT_WEBHOOK` 密钥里（见第 3 步）
5. 以后每天收到的选股消息就在这个群里

不会建也没关系，用 Server酱（sct.ftqq.com 用 GitHub 登录拿 SendKey）或 PushPlus 也一样，
都是通过微信公众号收消息。

## 常见问题

**网页打不开**：GitHub Pages 在国内偶尔不稳定，微信推送才是主通道；网页打不开不影响收消息。

**某天没收到**：先看仓库 Actions 里那次运行的日志；数据源从美国机房访问偶尔失败，第二天会自动重试。

**想不花钱也不依赖电脑**：本方案 0 元；如果哪天想更稳，可以平滑升级到国内云服务器（一年一两百元），代码不用改。

## 免责声明

本系统为量化研究工具，输出不构成投资建议；股市有风险，入市需谨慎。
