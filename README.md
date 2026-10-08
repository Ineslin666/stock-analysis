# 每日 3 只优质股（学习用）

一个在本地运行的 A 股学习网站。它按固定、透明的规则筛选最多 3 只股票，并用通俗语言解释财务指标、估值和参考价位。

> 本项目仅供学习参考，不构成投资建议。股市有风险，投资需谨慎。

## 适合谁

- 想学习如何看 ROE、PE、PB、现金流等指标的新手
- 使用 Mac，希望数据保存在自己电脑上的用户
- 愿意把筛选结果当作学习素材，而不是盲目跟单的用户

## 小白安装（macOS）

### 1. 下载项目

打开 Mac 的“终端”，逐行复制以下命令：

```bash
git clone https://github.com/Ineslin666/stock-analysis.git
cd stock-analysis
./setup.sh
```

`setup.sh` 会自动创建运行环境、安装依赖并初始化数据库。首次安装需要联网，可能需要几分钟。

如果提示没有 Python，请先从 [Python 官网](https://www.python.org/downloads/macos/) 安装 Python 3.9 或更高版本，然后再运行 `./setup.sh`。

### 2. 启动

安装完成后运行：

```bash
./start.sh
```

程序会先更新数据和生成当日结果，然后自动打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。第一次准备全市场数据可能比较久，请保持网络连接并不要关闭终端。

关闭网站：回到终端按 `Control + C`。

## DeepSeek API（可选）

DeepSeek 只用来为缺失的股票自动生成公司和行业介绍。**不配置 API 也能正常选股和浏览网站。**

安装向导询问时，选择 `y` 并粘贴 API Key 即可。如果安装时跳过了，之后可在项目目录手动运行：

```bash
printf '%s\n' '把你的_API_Key_粘贴在这里' > .deepseek_key
chmod 600 .deepseek_key
```

也可在启动前设置环境变量：

```bash
export DEEPSEEK_API_KEY='把你的_API_Key_粘贴在这里'
./start.sh
```

`.deepseek_key` 已在 `.gitignore` 中，不会上传到 GitHub。不要把真实 API Key 写进 README、代码或截图。

## 日常使用注意

- 建议在交易日 `09:15` 之前或 `09:25` 之后运行。当前版本应避开 `09:15–09:25` 集合竞价时段。
- 数据来自 AkShare 封装的公开接口，数据源暂时不可用时，网站会尽量显示上次缓存结果。
- 非交易日会显示最近一个交易日的结果。
- 同一只股票 60 天内不会被再次推荐，当日结果会尽量分散到不同行业。

## 常见问题

### 提示 `Permission denied: ./setup.sh`

运行：

```bash
chmod +x setup.sh start.sh
./setup.sh
```

### 页面没有当日 3 只股票

先查看终端最后的提示。常见原因是网络或免费数据源暂时不可用。如果在 `09:15–09:25` 运行，请等待集合竞价结束后重试。

### 安装依赖失败

确认网络正常，然后重新运行 `./setup.sh`。脚本可重复执行，不会删除已有数据。

## 技术说明

- Python 3.9+
- FastAPI + Jinja2
- SQLite
- pandas + AkShare
- 可选 DeepSeek API

更详细的需求、数据结构和筛选规则见 [`文档/`](文档/)。
