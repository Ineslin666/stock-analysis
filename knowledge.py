"""公司介绍知识库读取层（01 规范 F8 / 05 规范 §9 6.2）

知识库为人工维护的 JSON 文件（git 跟踪）：
- knowledge/industries/<行业>.json  行业科普卡
- knowledge/stocks/<code>.json      个股条目
每次调用直接读文件：内容小、更新即时生效——补写后刷新页面即见，无需重启。
JSON 字段定义见 01 规范 F8 与 03 规范 §4.5。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

BASE = Path(__file__).resolve().parent / "knowledge"
INDUSTRY_DIR = BASE / "industries"
STOCK_DIR = BASE / "stocks"


def _safe_name(name: str) -> str:
    """文件名安全化：/ 和 \\ 在 macOS 文件名中非法，换成全角。"""
    return name.replace("/", "／").replace("\\", "＼")


def load_industry(industry: str) -> Optional[dict]:
    """读取行业科普卡；不存在或损坏返回 None。"""
    return _load(INDUSTRY_DIR / f"{_safe_name(industry)}.json")


def load_stock(code: str) -> Optional[dict]:
    """读取个股条目；不存在或损坏返回 None。"""
    return _load(STOCK_DIR / f"{code}.json")


def _load(path: Path) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def missing_coverage(codes: list, industries: list) -> dict:
    """覆盖检查（daily_run 用）：返回缺条目清单。

    返回 {"stocks": [code...], "industries": [行业...]}，去重保序。
    """
    stocks, inds = [], []
    for c in dict.fromkeys(codes):
        if load_stock(c) is None:
            stocks.append(c)
    for i in dict.fromkeys(industries):
        if i and load_industry(i) is None:
            inds.append(i)
    return {"stocks": stocks, "industries": inds}
