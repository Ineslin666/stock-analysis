#!/usr/bin/env python3
"""每日一键运行：刷新快照 → 筛选 3 只 → 生成结论（幂等，可重复运行）。

日常由 start.sh 调用；也可手动运行：
    .venv/bin/python scripts/daily_run.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analyzer
import data_fetcher as fetcher
import screener

VERDICT_TXT = {"buy": "值得买入", "buy_batch": "建议分批买入", "hold": "暂不建议买入"}


def main() -> int:
    print("=" * 46)
    print("每日 3 只优质股 · 晨间运行")
    print("=" * 46)
    print("1/3 刷新全市场行情快照（约 1 分钟）…", flush=True)
    fetcher.fetch_snapshot(force=True)
    print("2/3 按固定逻辑筛选全市场（约 2~4 分钟）…", flush=True)
    result = screener.run()
    if result["status"] == "error":
        print(f"筛选失败：{result['error_msg']}")
        return 1
    print("3/3 生成买入结论与参考价位…", flush=True)
    picked = analyzer.run()
    print("=" * 46)
    print("完成！今日 3 只（仅供学习参考，不构成投资建议）：")
    for x in picked:
        print(f"  {x['rank']}. {x['name']} {x['code']} — {VERDICT_TXT[x['verdict']]}")
    print("=" * 46)
    return 0


if __name__ == "__main__":
    sys.exit(main())
