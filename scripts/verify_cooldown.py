#!/usr/bin/env python3
"""阶段 5.2 验收：冷却期与"连续多日不重复"验证（05 文档 §8.2）。

不写入真实推荐数据：select_top 用注入的候选列表跑逻辑，冷却名单通过
monkeypatch 模拟"前几日已推荐"，真实 SQL（get_recent_recommended_codes）
单独用只读查询验证。

运行：.venv/bin/python scripts/verify_cooldown.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db
import screener

FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAIL
    print(f"{'✅' if ok else '❌'} {name}" + (f"  —— {detail}" if detail else ""))
    if not ok:
        FAIL += 1


def make_candidates(n: int = 30):
    """n 只互不同行业的合成候选，分数依次递减（C001 最高）。"""
    return [{"code": f"C{i:03d}", "name": f"股{i}", "industry": f"行业{i:02d}",
             "score": 100.0 - i} for i in range(1, n + 1)]


# ---------- 1. 多日模拟：连续 5 天每天选 3 只，全程无重复 ----------
picked_history: list[str] = []
all_picked: set[str] = set()
candidates = make_candidates()

for day in range(1, 6):
    trade_date = f"2026-08-{day:02d}"
    # 模拟真实冷却查询：过去 60 天内推荐过的（= 此前所有天所选；当日尚无记录，
    # 所以 exclude_date 不影响结果）
    real_fn = db.get_recent_recommended_codes
    db.get_recent_recommended_codes = lambda days=60, exclude_date=None: set(all_picked)
    try:
        picked = screener.select_top([dict(c) for c in candidates], trade_date, limit=3)
    finally:
        db.get_recent_recommended_codes = real_fn

    codes = [p["code"] for p in picked]
    picked_history.append((trade_date, codes))
    # 断言 1：每天选出的都不是之前推荐过的
    check(f"第 {day} 天不与历史重复", not (set(codes) & all_picked), str(codes))
    # 断言 2：选出的是冷却后分数最高的 3 只
    expected = [c["code"] for c in candidates if c["code"] not in all_picked][:3]
    check(f"第 {day} 天选的是冷却后 Top3", codes == expected)
    all_picked.update(codes)

# ---------- 2. 同日幂等重跑：当日已有推荐不算冷却 ----------
candidates2 = make_candidates(10)
real_fn = db.get_recent_recommended_codes
# 模拟：昨日已推荐 C001/C002/C003，且当日已有 C004/C005/C006（重跑前写入的）
db.get_recent_recommended_codes = lambda days=60, exclude_date=None: \
    {"C001", "C002", "C003"} if exclude_date == "2026-08-13" \
    else {"C001", "C002", "C003", "C004", "C005", "C006"}
try:
    first = screener.select_top([dict(c) for c in candidates2], "2026-08-13", limit=3)
    again = screener.select_top([dict(c) for c in candidates2], "2026-08-13", limit=3)
finally:
    db.get_recent_recommended_codes = real_fn
check("同日重跑选出真正的 Top3（跳过昨日冷却）",
      [p["code"] for p in first] == ["C004", "C005", "C006"], str([p["code"] for p in first]))
check("同日重跑结果稳定（两次一致）", [p["code"] for p in first] == [p["code"] for p in again])

# ---------- 3. 行业分散：同行业每天最多 1 只 ----------
same_industry = [
    {"code": "A01", "name": "甲", "industry": "饮料", "score": 100.0},
    {"code": "A02", "name": "乙", "industry": "饮料", "score": 99.0},
    {"code": "A03", "name": "丙", "industry": "软件", "score": 98.0},
    {"code": "A04", "name": "丁", "industry": "银行", "score": 97.0},
]
real_fn = db.get_recent_recommended_codes
db.get_recent_recommended_codes = lambda days=60, exclude_date=None: set()
try:
    picked = screener.select_top([dict(c) for c in same_industry], "2026-08-13", limit=3)
finally:
    db.get_recent_recommended_codes = real_fn
check("同行业每天最多 1 只（乙被跳过，丙递补）",
      [p["code"] for p in picked] == ["A01", "A03", "A04"], str([p["code"] for p in picked]))

# ---------- 4. 真实 SQL 验证：get_recent_recommended_codes 的 exclude_date ----------
real_recent = db.get_recent_recommended_codes(60)
today_codes = {c for c in real_recent
               if db.get_latest_recommendation(c) is not None
               and db.get_latest_recommendation(c)["rec_date"] == "2026-08-13"}
if today_codes:
    check("真实库：exclude_date 后当日推荐不在冷却名单",
          real_recent - db.get_recent_recommended_codes(60, exclude_date="2026-08-13") == today_codes,
          f"当日 {sorted(today_codes)}")
else:
    check("真实库：当日无推荐记录（跳过本项）", True)

print()
print("❌ 存在失败项" if FAIL else "全部通过 ✅")
sys.exit(1 if FAIL else 0)
