#!/usr/bin/env python3
"""阶段 2.0 数据准备：行业补源 + 全市场财务指标首次全量拉取。

用法：.venv/bin/python -u scripts/prepare_data.py
- ① 行业补源：巨潮个股概况，约 3200 只 × 0.5s ≈ 30 分钟（一次性，入库长期有效）
- ② 财务全量：新浪财务指标，上市满 3 年约 4500 只 × 1.2s ≈ 1.5~2 小时
  财务只拉"上市满 3 年"的股票（次新股被基础过滤剔除，见 文档/04 §2）
两个步骤均有缓存兜底，中断后重跑自动断点续跑。
"""
from __future__ import annotations

import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db
import data_fetcher as fetcher


def main() -> int:
    db.init_db()
    print("== 交易日历 ==", flush=True)
    fetcher.fetch_trade_calendar()
    print("== 股票列表 ==", flush=True)
    lst = fetcher.fetch_stock_list()
    print(f"全市场 {len(lst)} 只", flush=True)

    print("\n== ① 行业补源（巨潮个股概况）==", flush=True)
    t0 = time.time()
    filled = fetcher.fetch_industry_fill()
    missing = db._query_df(
        "SELECT COUNT(*) AS n FROM stock_snapshot "
        "WHERE list_date IS NOT NULL AND (industry IS NULL OR industry = '')")
    print(f"行业补源完成：回填 {filled}，仍缺 {missing['n'].iloc[0]}，"
          f"耗时 {time.time() - t0:.0f}s", flush=True)

    print("\n== ② 财务指标全量拉取（新浪，上市满 3 年）==", flush=True)
    cutoff = (date.today() - timedelta(days=365 * 3)).isoformat()
    codes = lst[lst["list_date"] <= cutoff]["code"].tolist()
    print(f"候选池（剔除次新后）{len(codes)} 只，预计 {len(codes) * 1.2 / 60:.0f} 分钟", flush=True)

    ok = fail = 0
    t0 = time.time()
    for i, code in enumerate(codes, 1):
        try:
            ok += 1 if fetcher.fetch_finance(code) else 0
        except Exception:  # noqa: BLE001 单只失败不中断
            fail += 1
        if i % 100 == 0:
            el = max(time.time() - t0, 1e-9)
            print(f"  进度 {i}/{len(codes)} 成功 {ok} 失败 {fail} "
                  f"已用 {el / 60:.0f} 分钟 预计剩余 {(len(codes) - i) * el / i / 60:.0f} 分钟",
                  flush=True)
    print(f"财务拉取完成：成功 {ok}，失败 {fail}，总耗时 {(time.time() - t0) / 60:.0f} 分钟", flush=True)

    total = db._query_df("SELECT COUNT(*) AS n FROM stock_finance")
    print(f"stock_finance 现有 {total['n'].iloc[0]} 行", flush=True)
    return 0 if fail < len(codes) * 0.05 else 1


if __name__ == "__main__":
    sys.exit(main())
