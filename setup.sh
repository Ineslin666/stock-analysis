#!/bin/bash
# macOS 首次安装向导。可重复运行，不会删除已有数据。
set -e

cd "$(dirname "$0")"

echo "========================================"
echo "  每日 3 只优质股（学习用）安装向导"
echo "========================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ 没有找到 Python 3。"
  echo "请先前往 https://www.python.org/downloads/macos/ 安装 Python 3.9 或更高版本，然后重新运行 ./setup.sh。"
  exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "❌ Python 版本过低，本项目需要 Python 3.9 或更高版本。"
  echo "当前版本：$(python3 --version 2>&1)"
  exit 1
fi

echo "✅ 已找到 $(python3 --version 2>&1)"

if [ ! -d ".venv" ]; then
  echo "→ 正在创建独立运行环境…"
  python3 -m venv .venv
else
  echo "✅ 运行环境已存在"
fi

echo "→ 正在安装项目依赖（首次可能需要几分钟）…"
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

echo "→ 正在初始化本地数据库…"
.venv/bin/python -c 'import db; db.init_db()'

if [ -n "${DEEPSEEK_API_KEY:-}" ] || [ -s ".deepseek_key" ]; then
  echo "✅ DeepSeek API 已配置"
elif [ -t 0 ]; then
  echo
  echo "DeepSeek API 是可选项：不配置也能选股和打开网站，只是不会自动生成公司介绍。"
  printf "现在配置 DeepSeek API Key 吗？[y/N] "
  read -r configure_api
  case "$configure_api" in
    y|Y|yes|YES)
      printf "请粘贴 API Key（输入时不会显示）："
      stty -echo
      read -r deepseek_key
      stty echo
      echo
      if [ -n "$deepseek_key" ]; then
        printf '%s\n' "$deepseek_key" > .deepseek_key
        chmod 600 .deepseek_key
        echo "✅ API Key 已保存在本机，不会被 Git 上传"
      else
        echo "未输入 API Key，已跳过。"
      fi
      ;;
    *) echo "已跳过 API 配置。" ;;
  esac
else
  echo "ℹ️  未配置 DeepSeek API，公司介绍自动生成将被跳过。"
fi

echo
echo "✅ 安装完成！"
echo "以后启动只需在项目目录运行："
echo "  ./start.sh"
echo
echo "注意：交易日 09:15–09:25 集合竞价期间请暂时不要启动筛选。"
