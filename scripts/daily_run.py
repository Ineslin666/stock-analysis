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
import knowledge
import screener

VERDICT_TXT = {"buy": "值得买入", "buy_batch": "建议分批买入", "hold": "暂不建议买入"}


def _print_coverage(picked: list) -> None:
    """检查今日推荐的知识库覆盖情况，缺条目时终端提醒（05 §9 6.4）。

    公司介绍模块依赖 knowledge/ 人工维护条目；缺条目时详情页会降级隐藏，
    这里在终端提醒补写，补写后刷新页面即生效（无需重启）。
    """
    codes = [x["code"] for x in picked]
    industries = [x["industry"] for x in picked if x.get("industry")]
    miss = knowledge.missing_coverage(codes, industries)
    if not (miss["stocks"] or miss["industries"]):
        print("知识库覆盖完整，公司介绍模块将完整展示。")
        return
    print("⚠️ 知识库缺条目（公司介绍模块将降级显示，补写后刷新页面即生效）：")
    if miss["stocks"]:
        names = {x["code"]: x["name"] for x in picked}
        items = [f"{c} {names.get(c, '')}".strip() for c in miss["stocks"]]
        print(f"  · 缺个股条目：{'、'.join(items)}")
    if miss["industries"]:
        print(f"  · 缺行业卡：{'、'.join(miss['industries'])}")


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
    if picked:
        _print_coverage(picked)
    return 0


if __name__ == "__main__":
    sys.exit(main())
