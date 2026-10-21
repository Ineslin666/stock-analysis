#!/bin/bash
# 笔记本一键启动：先跑当日筛选（约 3~5 分钟），再在本机打开网站和浏览器。
# 用法：进入项目目录后运行 ./start.sh
# 这个终端要保持开着，网站才在；关掉窗口，网站会一起停。
# Mac mini 上若要一直开着、每天自动写入数据库，见 文档/08-Mac-mini常驻与自动刷新.md。
cd "$(dirname "$0")"

# 首次使用时给出可操作的提示，避免直接报“文件不存在”。
if [ ! -x ".venv/bin/python" ]; then
  echo "尚未完成安装。请先运行："
  echo "  ./setup.sh"
  exit 1
fi

# 网站已在运行则直接打开浏览器，不重复启动
if lsof -i :8000 -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "网站已经在运行，直接打开浏览器即可。"
  open http://127.0.0.1:8000
  exit 0
fi

# 第一步：跑当日筛选（终端可见进度与结果）
.venv/bin/python scripts/daily_run.py || {
  echo "筛选未完成（可能是网络问题），网站将照常启动并显示最近一次结果。"
}

# 第二步：启动网站，3 秒后自动打开浏览器（Ctrl+C 可随时关闭网站）
echo "正在启动网站…"
(sleep 3 && open http://127.0.0.1:8000) &
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
