#!/bin/bash
# Mac mini 常驻网站：只用 .venv 启动 uvicorn，监听 0.0.0.0:8000。
# 不跑当日筛选，不打开浏览器。每天写入数据库由 scripts/daily_refresh.sh 负责。
# 笔记本请继续用项目根目录的 ./start.sh。说明见 文档/08-Mac-mini常驻与自动刷新.md。
cd "$(dirname "$0")/.."

if [ ! -x ".venv/bin/python" ]; then
  echo "尚未完成安装。请先在项目目录运行 ./setup.sh"
  exit 1
fi

exec .venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8000
