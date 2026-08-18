#!/usr/bin/env python3
"""公司介绍手动补写入口（05 §10 7.3）。

用法：
    .venv/bin/python scripts/gen_intro.py              # 补写最近一次推荐的知识库缺条目
    .venv/bin/python scripts/gen_intro.py 600519       # 指定股票代码，单独补写个股条目
已有条目一律跳过（不覆盖）；生成失败返回非零退出码。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db
import intro_gen
import knowledge


def _gen_one(code: str) -> int:
    if knowledge.load_stock(code) is not None:
        print(f"· {code} 已有条目，跳过（不覆盖）")
        return 0
    stock = intro_gen._with_snapshot({"code": code})
    entry = intro_gen.gen_stock(stock)
    if entry is None:
        print(f"✗ {code} 生成失败（检查 .deepseek_key 与网络，可稍后重试）")
        return 1
    if not knowledge.save_stock(entry):
        print(f"✗ {code} 入库失败")
        return 1
    print(f"✓ {entry['name']} {entry['code']} 条目已由 AI 生成并入库：")
    intro_gen.print_entry(entry)
    return 0


def main() -> int:
    db.init_db()
    codes = sys.argv[1:]
    if codes:
        return max(_gen_one(c) for c in codes)
    recs = db.get_recommendations()
    if recs.empty:
        print("暂无推荐记录。用法：scripts/gen_intro.py <股票代码> [<代码> …]")
        return 1
    date = recs["rec_date"].max()
    picked = [{"code": r["code"], "name": r["name"], "industry": r["industry"]}
              for _, r in db.get_recommendations(date).iterrows()]
    intro_gen.print_report(intro_gen.ensure_coverage(picked), picked)
    return 0


if __name__ == "__main__":
    sys.exit(main())
