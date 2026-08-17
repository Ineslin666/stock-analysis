#!/usr/bin/env python3
"""阶段 6.1 探测：寻找全市场总市值数据源（F8 行业龙头排名用）。

结果记录于开发日志，决策表见 05 规范 §9 6.1。
用法：.venv/bin/python scripts/probe_marketcap.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import akshare as ak

print("== 1) 新浪全市场快照 stock_zh_a_spot 列 ==")
spot = ak.stock_zh_a_spot()
print("列:", list(spot.columns))

print("\n== 2) 新浪行业板块成分 stock_sector_detail 列（取第一个板块）==")
sectors = ak.stock_sector_spot(indicator="新浪行业")
label = str(sectors["label"].iloc[0])
print(f"板块 label: {label}")
det = ak.stock_sector_detail(sector=label)
print("列:", list(det.columns))
print("样例:")
print(det.head(3).to_string())
