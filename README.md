# 恒生科技投资工作台

恒生科技指数交互式复盘工作台。使用带来源和时间戳的真实市场快照，并在香港交易日按 08:30、12:30、17:00 生成早报、午报和晚报。

## 分享给朋友（推荐）

这个项目可以放在 GitHub，朋友下载后在自己的电脑上运行。每一位使用者都会有一套独立的工作台、独立的数据更新和独立的本机网址；不需要把数据或密钥交给项目作者。

### 使用者只需要做一次的事

1. 安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)，打开并确认它正在运行。
2. 在 GitHub 项目页点击 **Code → Download ZIP**，解压；或用 `git clone` 下载项目。
3. 在项目文件夹中执行：

   ```bash
   docker compose up -d --build
   ```

4. 打开 <http://localhost:3000>。

首次启动需要下载运行环境，通常会比以后启动久。完成后网页服务和数据更新服务会随 Docker 自动恢复；电脑必须开机且联网，才能按时采集新报告。

新下载的项目不会附带过期市场报告。若希望首次启动立刻生成最近交易日的三份报告，可额外执行一次：

```bash
docker compose run --rm scheduler python -m pipeline.collect
```

### 常用操作

```bash
# 查看两个服务是否正常运行
docker compose ps

# 查看采集服务日志
docker compose logs -f scheduler

# 停止工作台（保留已采集的数据）
docker compose down

# 更新到 GitHub 的新版本后重新构建并启动
docker compose up -d --build
```

浏览器显示的是本机地址，默认只有这台电脑能访问。项目不会上传或共享任何使用者产生的报告。运行数据保存在 Docker 的本机数据卷中；请不要执行 `docker compose down -v`，除非确定要清空本机已采集的报告。

> 数据源均为公开来源，但请自行确认其使用条款及所在地区的适用规则。本工作台仅用于研究与复盘，不构成投资建议。

## 当前功能

- 恒科真实分钟走势与分钟成交额；Event Engine 动态识别快速涨跌、反转、突破、破位、量能异常和失败突破/破位。
- Event 悬停或点击后锁定，并联动同窗口成分股、跨市场、新闻证据与谨慎归因。
- 30 只官方成分股、官方月度权重、时点涨跌、市场宽度和明确标为 estimated 的贡献估算。
- HSI、A 股、日韩、美股、USD/CNH、美债 10Y 与 Brent 的延迟跨市场快照。
- 南向资金、原始新闻 Event Feed、可执行 Watchlist 及自动验证记录。
- 每条外部数据展示来源、原始时点、抓取时间和实时/延迟/最近可用状态。

## 开发者本地运行

使用项目配置的 Node.js 环境运行：

```bash
pnpm dev
```

然后访问 `http://127.0.0.1:3000`。

首次设置或更新 Python 依赖：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

手动采集最近交易日三份报告：

```bash
pnpm data:collect
```

质量检查：

```bash
pnpm test
pnpm lint
pnpm build
```

## 数据原则

`reference/reports/` 只保留产品分析样本。运行时报告保存在 `data/runtime/reports/YYYY-MM-DD/`，页面通过 `/api/dashboard` 读取。正式页面不会回退到 Mock Data；字段缺失时显示 `Data unavailable`、来源错误或最后可用时间。

当前已知的数据边界记录在 `docs/source-evaluation.md`。港股沽空比率和恒科期货基差因公开数据稳定性不足，不进入正式报告；指数 PB/历史估值分位和官方精确贡献尚未达到接入标准，因此不会伪装成可用数据。

## 自动更新

本机使用 `pipeline.scheduler` 作为独立数据看门狗。它不依赖 Codex 对话或使用额度，会在香港交易日 08:30 早报、12:30 午报、17:00 晚报生成报告；电脑休眠或错过时点后会在唤醒时补齐。完整报告不会重复采集，缺失、损坏或因临时网络错误导致不完整的报告会按间隔重试。

调度健康状态保存在 `data/runtime/scheduler-status.json`，详细运行日志由本机 LaunchAgent 写入 `data/runtime/logs/`。

Docker 分享版会以同样的五分钟检查频率运行该看门狗，状态和日志保存在 Docker 数据卷中。

## 发布到 GitHub

上传前请确认没有把 `.env`、`.env.local`、账号 Cookie、访问令牌或任何私密报告加入提交。项目的 `.gitignore` 已排除这些本机文件和运行时报告；每位使用者的数据仅保存在自己的 Docker 数据卷中。

创建 GitHub 仓库后，在项目根目录依次执行：

```bash
git init
git add .
git commit -m "feat: shareable local dashboard"
git branch -M main
git remote add origin <你的 GitHub 仓库地址>
git push -u origin main
```

若只打算发给受信任的朋友，请在 GitHub 创建**私有仓库**并邀请协作者。公开仓库会让任何人都能下载项目源码。
