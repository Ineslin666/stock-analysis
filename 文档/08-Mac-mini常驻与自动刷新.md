# 08-Mac mini 常驻与自动刷新

> 版本：v1.0 ｜ 2026-10-16 ｜ 状态：已定稿
> 给一台经常开着的 Mac mini 用。笔记本不用改，继续在项目目录运行 `./start.sh`。

网站上的股票结论仅供学习参考，不构成投资建议。

## 1. 以前为什么要每次手动开

现在笔记本上的用法是：早上打开终端，运行 `./start.sh`。脚本会先执行 `scripts/daily_run.py`（刷新行情、选出最多 3 只、写出结论，缺的公司介绍再补写），然后在**这个终端窗口里**启动网站，并打开浏览器。

这样设计，是因为 2026-08-14 按当时的作息改过一次运行方式：电脑大约早上 8:30 开、晚上 18:30 关，不适合在后台挂一整套定时任务。所以：

- 网站只监听本机 `127.0.0.1:8000`。关掉终端，或在终端里按 `Control + C`，网站就停了。
- 数据也不会自己更新。哪天忘了跑 `./start.sh`，数据库里就还是上一次的结果。

`文档/02-技术方案.md` 的技术栈表里写过 APScheduler，那是更早的方案：交易日 18:30 由网站进程自己跑筛选。这套调度后来从 `app.py` 里拿掉了。现在 `app.py` 里只剩启动时的兜底函数 `_maybe_backfill`：不经过 `start.sh`、直接启动网站时，如果今天是交易日、库里还没有今天的推荐，它会在后台补跑一次。它**不是**每天到点自动跑。

`requirements.txt` 里仍列着 APScheduler，是当时装下的包。这次没有再把它接回网站进程。Mac mini 常开，用 macOS 自带的 launchd 更合适：网站挂了由系统拉起来，每天到点再单独跑一次已有的 `daily_run.py`。

## 2. 现在这两件事怎么分开

| | 做什么 | 不做什么 |
|---|---|---|
| `scripts/serve_always.sh` | 用项目里的 `.venv` 启动 uvicorn，监听 `0.0.0.0:8000` | 不跑筛选，不打开浏览器 |
| `scripts/daily_refresh.sh` | 调用原来的 `scripts/daily_run.py`，把当天输出追加到 `logs/` | 不启动网站 |

网站只是读取 SQLite（`data/stock.db`）。每天早上的刷新把新结果写进这个库，浏览器用刷新即可看到，不用为了更新去重启网站。筛选大约要几分钟，跑完之前页面仍是上一次的结果。

两份配置在 `deploy/macos/`，安装到当前用户的 `~/Library/LaunchAgents/` 后由 launchd 接管：

- **网站**：`KeepAlive` + 登录后就启动。进程退出后，系统会再把它拉起来。
- **每日刷新**：`StartCalendarInterval`，每天本地时间 **08:00** 跑一次。周末和节假日也会跑；用的是最近一个完整交易日的数据，同一天重复写入只会覆盖，不会堆出重复推荐。

选在 08:00，是为了避开 **09:15–09:25** 集合竞价。这段时间里价格可能暂时是 0，有机会把上一交易日的收盘价盖掉，筛选会跑空。08:00 在竞价开始之前。

早上跑的时候，当天 K 线通常还没发布（新浪日线大约 17:00–18:00 才齐）。所以这次刷新和笔记本上的 `./start.sh` 一样：用最近一个完整收盘日的数据，推荐日期记成当天。

launchd 的“每天 08:00”用的是 **Mac 的系统时区**。plist 里不能单独写一个时区。请把 Mac mini 设为 **Asia/Shanghai**（北京时间，中国标准时间）。设好之后，08:00 就是北京时间早上 8 点。

同一台 Tailscale 网络里的手机或电脑，浏览器打开 `http://<Mac mini 的 IP>:8000` 即可。

网站没有登录。`0.0.0.0` 表示这台 Mac 的 8000 端口对能访问到它的网络开放，请只在自己的家里网络和 Tailscale 里使用。

笔记本继续用 `./start.sh`：仍然只监听 `127.0.0.1`，仍然会打开浏览器。不要在同一台电脑上同时跑 `./start.sh` 和 `serve_always.sh`，它们都要占用 8000 端口。

## 3. 在 Mac mini 上安装（按顺序做）

下面的命令都在 macOS 自带的「终端」里执行。

### 3.1 让电脑到点还醒着，并且时区是上海

1. 时区设为上海。打开「系统设置 → 通用 → 日期与时间 → 时区」，选择上海。也可以在终端执行：

   ```bash
   sudo systemsetup -settimezone Asia/Shanghai
   date
   ```

   `date` 的输出里应能看到 `CST`。

2. 接通电源时不要自动睡觉，否则 8 点的任务可能要等电脑醒来才跑。打开「系统设置 → 锁定屏幕」（有的版本在「节能」或「电池」里），找到接通电源时类似「显示器关闭时防止自动进入睡眠」的开关，把它打开。

3. LaunchAgent 要等**你的用户登录之后**才会运行。这台 Mac mini 如果希望重启后自己把网站拉起来，请打开「系统设置 → 用户与群组 → 自动登录」，选中平时使用的那个用户。这只建议用在家里这台常开的电脑上。

### 3.2 安装项目

如果还没有 Python 3.9 或更高版本，先到 [Python 官网的 macOS 下载页](https://www.python.org/downloads/macos/) 安装，然后再做下面这几步。

```bash
git clone https://github.com/Ineslin666/stock-analysis.git
cd stock-analysis
chmod +x setup.sh start.sh scripts/serve_always.sh scripts/daily_refresh.sh
./setup.sh
```

`./setup.sh` 会创建 `.venv`、安装依赖并初始化数据库。可以重复运行，不会删掉已有数据。

公司介绍的自动补写需要 DeepSeek 密钥，不配置也能选股和打开网站。要配置的话，按仓库 `README.md` 把密钥写进项目目录的 `.deepseek_key`。这个文件已经在 `.gitignore` 里。不要把密钥写进 plist、文档或截图，也不要提交到 git。

先手动刷新一次，确认网络和数据源可用（第一次准备数据会比平时久）：

```bash
./scripts/daily_refresh.sh
```

完成后打开 `logs/daily_refresh-` 加当天日期的那个 `.log`，里面应有本次运行的开始、结束和退出码。

### 3.3 安装两个 LaunchAgent

仓库里的 plist 使用占位符 `REPLACE_WITH_PROJECT_PATH`。请**复制到用户目录后再替换**，不要改仓库里的原文件，这样以后 `git pull` 不会和你的本机路径打架。

先确认自己在项目目录里。`pwd` 打印出来的必须是以 `/` 开头的绝对路径，例如 `/Users/你的用户名/stock-analysis`，不能是 `~`。

```bash
cd /换成你的项目路径/stock-analysis
pwd
mkdir -p logs "$HOME/Library/LaunchAgents"
cp deploy/macos/com.stock-analysis.serve.plist "$HOME/Library/LaunchAgents/"
cp deploy/macos/com.stock-analysis.daily-refresh.plist "$HOME/Library/LaunchAgents/"
sed -i '' "s|REPLACE_WITH_PROJECT_PATH|$(pwd)|g" \
  "$HOME/Library/LaunchAgents/com.stock-analysis.serve.plist" \
  "$HOME/Library/LaunchAgents/com.stock-analysis.daily-refresh.plist"
grep REPLACE_WITH_PROJECT_PATH "$HOME/Library/LaunchAgents"/com.stock-analysis.*.plist || echo "路径已替换"
```

最后一行如果打印 `路径已替换`，说明两份已安装的 plist 里不再有占位符。`sed -i ''` 是 macOS 自带 sed 的写法。

加载，并立刻把网站拉起来：

```bash
UID_NUM="$(id -u)"
launchctl bootstrap "gui/${UID_NUM}" "$HOME/Library/LaunchAgents/com.stock-analysis.serve.plist"
launchctl bootstrap "gui/${UID_NUM}" "$HOME/Library/LaunchAgents/com.stock-analysis.daily-refresh.plist"
launchctl enable "gui/${UID_NUM}/com.stock-analysis.serve"
launchctl enable "gui/${UID_NUM}/com.stock-analysis.daily-refresh"
launchctl kickstart -k "gui/${UID_NUM}/com.stock-analysis.serve"
```

每天 08:00 的任务不用现在 kickstart，到点会自己跑。如果这份 plist 之前已经 load 过，`bootstrap` 会提示已经加载；先做一次第 3.5 节的 `bootout`，再重新 `bootstrap`。

想马上试一次每日刷新（会再跑几分钟筛选）：

```bash
launchctl kickstart -k "gui/$(id -u)/com.stock-analysis.daily-refresh"
```

### 3.4 确认网站已经开着

在 Mac mini 上：

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/
```

输出 `200` 后，浏览器用 `http://127.0.0.1:8000` 打开即可。

同一 Tailscale 网络里的其他设备，打开 `http://<Mac mini 的 IP>:8000`。macOS 第一次允许外部访问时，可能弹出防火墙询问，请选择允许传入连接。

网站进程启动时，如果今天是交易日并且库里还没有今天的推荐，`app.py` 的 `_maybe_backfill` 仍可能在后台补跑一次。这是原来就有的启动兜底。平常的更新以每天 08:00 的 `daily_refresh` 为准，不要靠反复重启网站来刷新数据。

### 3.5 看日志、停掉、搬目录之后

日志都在项目的 `logs/` 目录（已加入 `.gitignore`，不会进 git）：

| 文件 | 内容 |
|---|---|
| `logs/serve_always.out.log`、`logs/serve_always.err.log` | 网站进程的输出 |
| `logs/daily_refresh-YYYYMMDD.log` | 某一天刷新的完整输出 |
| `logs/daily_refresh.launchd.out.log`、`logs/daily_refresh.launchd.err.log` | 刷新脚本还没写上上面那个日期文件就失败时的输出 |

停掉常驻（数据库还在）：

```bash
launchctl bootout "gui/$(id -u)/com.stock-analysis.serve"
launchctl bootout "gui/$(id -u)/com.stock-analysis.daily-refresh"
```

拉过新代码后，重新启动网站：

```bash
launchctl kickstart -k "gui/$(id -u)/com.stock-analysis.serve"
```

项目换了目录之后，先 `bootout`，再按第 3.3 节重新复制 plist 并替换路径。

## 4. 笔记本和 Mac mini 各用哪一套

| | 笔记本 | Mac mini |
|---|---|---|
| 怎么开 | 项目目录里 `./start.sh` | 登录后由 launchd 启动，不用开着终端 |
| 网站地址 | 只本机 `127.0.0.1:8000` | `0.0.0.0:8000`，本机和 Tailscale 都能访问 |
| 数据何时写入 | 每次运行 `./start.sh` 时当场跑 | 每天本地 08:00 跑 `daily_refresh.sh` |
| 关掉终端 | 网站一起停 | 网站继续跑 |
