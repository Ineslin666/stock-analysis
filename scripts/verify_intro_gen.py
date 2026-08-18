#!/usr/bin/env python3
"""阶段 7 离线验收脚本（不调真实 API，不产生费用）。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import knowledge

FAILED = []


def check(name: str, cond: bool) -> None:
    print(("  ✓ " if cond else "  ✗ ") + name)
    if not cond:
        FAILED.append(name)


def _test_knowledge_save() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="verify_intro_"))
    knowledge.STOCK_DIR = tmp / "stocks"
    knowledge.INDUSTRY_DIR = tmp / "industries"
    entry = {"code": "600000", "name": "测试银行", "what": "一家银行。", "life": "你可能在街边见过它。",
             "products": ["存款", "贷款"],
             "upstream": [{"name": "储户", "role": "提供资金"}],
             "downstream": [{"name": "借款人", "role": "使用贷款"}]}
    check("save_stock 新条目写入成功", knowledge.save_stock(entry) is True)
    check("save_stock 已存在跳过（不覆盖）", knowledge.save_stock(entry) is False)
    loaded = knowledge.load_stock("600000")
    check("load_stock 读回内容一致", loaded == entry)
    check("save_stock 不覆盖原内容", loaded["what"] == "一家银行。")
    card = {"industry": "测试行业", "what": "x", "money": "y", "products": "z",
            "upstream": ["甲"], "downstream": ["乙"]}
    check("save_industry 写入成功", knowledge.save_industry(card) is True)
    check("save_industry 已存在跳过", knowledge.save_industry(card) is False)
    check("save_industry 中文文件名可读回", knowledge.load_industry("测试行业") == card)
    check("save_stock 缺 code 拒绝", knowledge.save_stock({"name": "x"}) is False)
    check("save_industry 缺 industry 拒绝", knowledge.save_industry({"what": "x"}) is False)


def main() -> int:
    _test_knowledge_save()
    if FAILED:
        print(f"\n{len(FAILED)} 项失败：")
        for name in FAILED:
            print("  -", name)
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
