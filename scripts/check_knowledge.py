#!/usr/bin/env python3
"""知识库读取器验收脚本（阶段 6.2）

用法：.venv/bin/python scripts/check_knowledge.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import knowledge as kb


def main() -> int:
    ok = True

    def check(desc: str, cond: bool) -> None:
        nonlocal ok
        print(f"{'✅' if cond else '❌'} {desc}")
        ok = ok and cond

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "000001.json").write_text(
            json.dumps({"code": "000001", "what": "测试"}, ensure_ascii=False), encoding="utf-8")
        (d / "bad.json").write_text("{这不是合法JSON", encoding="utf-8")
        (d / "empty.json").write_text("", encoding="utf-8")
        kb.STOCK_DIR = d  # 临时替换数据目录，隔离测试不污染 knowledge/
        kb.INDUSTRY_DIR = d

        check("正常条目读取", (kb.load_stock("000001") or {}).get("what") == "测试")
        check("不存在的条目返回 None", kb.load_stock("999999") is None)
        check("损坏 JSON 返回 None", kb.load_stock("bad") is None)
        check("空文件返回 None", kb.load_stock("empty") is None)
        check("文件名安全化（/ \\ 换全角）", kb._safe_name("a/b\\c") == "a／b＼c")
        check("覆盖检查返回缺失清单",
              kb.missing_coverage(["000001", "999999", "999999"], ["测试"]) ==
              {"stocks": ["999999"], "industries": ["测试"]})

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
