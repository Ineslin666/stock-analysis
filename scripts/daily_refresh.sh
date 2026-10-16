#!/bin/bash
# 每日自动刷新：调用现有的 scripts/daily_run.py，把输出追加到 logs/。
# 不启动网站。Mac mini 上由 launchd 在每天本地时间 08:00 调用。
# 手动试跑：./scripts/daily_refresh.sh
cd "$(dirname "$0")/.."

if [ ! -x ".venv/bin/python" ]; then
  echo "尚未完成安装。请先在项目目录运行 ./setup.sh"
  exit 1
fi

mkdir -p logs
log="logs/daily_refresh-$(date +%Y%m%d).log"
{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') daily_refresh start ====="
  .venv/bin/python scripts/daily_run.py
  status=$?
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') daily_refresh exit ${status} ====="
  exit "${status}"
} >> "${log}" 2>&1
