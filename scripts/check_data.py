#!/usr/bin/env python3
"""数据层验收脚本（阶段 1.4）

对指定股票全量拉取数据，检查字段完整性与数值合理性。
用法：.venv/bin/python scripts/check_data.py [code1 code2 ...]
默认检查 600519 / 300750 / 600036。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根目录

import db
import data_fetcher as fetcher

# (代码, 名称, 合理区间参考): 用于数值合理性粗检
EXPECT = {
    "600519": {"roe": (20, 40), "debt": (10, 45), "pe": (10, 45), "pb": (3, 15), "dv": (0.5, 6)},
    "300750": {"roe": (10, 35), "debt": (40, 80), "pe": (10, 60), "pb": (2, 12), "dv": (0, 4)},
    "600036": {"roe": (8, 25), "debt": (80, 95), "pe": (3, 15), "pb": (0.4, 2), "dv": (2, 8)},
}


def check_range(code: str, field: str, value, lo: float, hi: float) -> str:
    if value is None:
        return f"⚠️  {field}: 缺失"
    if lo <= value <= hi:
        return f"✅ {field}: {value:.2f}"
    return f"❌ {field}: {value:.2f} 超出合理区间 [{lo}, {hi}]"


def fmt(value, div: float = 1.0, nd: int = 1) -> str:
    """安全格式化：None → '-'；否则除以 div 保留 nd 位。"""
    return "-" if value is None else f"{value / div:.{nd}f}"


def main() -> int:
    codes = sys.argv[1:] or list(EXPECT)
    db.init_db()
    print("== 初始化基础数据（交易日历 + 股票列表）==")
    cal = fetcher.fetch_trade_calendar()
    print(f"交易日历 {len(cal)} 条，今天是否交易日: {db.is_trade_day(fetcher._today())}，"
          f"最近交易日: {fetcher.latest_trade_date()}")
    lst = fetcher.fetch_stock_list()
    print(f"股票列表 {len(lst)} 只（沪主板+科创板+深市）")

    print("\n== 全市场快照（新浪行业板块成分，49 板块）==")
    snap = fetcher.fetch_snapshot()
    print(f"快照 {len(snap)} 只，行业数 {snap['industry'].nunique()}，"
          f"更新时间 {db.get_snapshot_last_update()}")

    ok = True
    for code in codes:
        print(f"\n{'='*60}\n检查 {code}\n{'='*60}")
        s = snap[snap["code"] == code]
        if s.empty:
            print("❌ 快照中不存在")
            ok = False
            continue
        s = s.iloc[0]
        print(f"名称 {s['name']} ｜ 行业 {s['industry']} ｜ 上市 {s['list_date']} ｜ "
              f"价格 {s['price']} ｜ 当日成交额 {fmt(s['turnover_today'], 1e8)} 亿")
        print(f"（总市值/PE/PB 由估值历史回填，稍后展示）")

        fin = fetcher.fetch_finance(code)
        if fin:
            e = EXPECT[code]
            print("-- 财务 --")
            print(check_range(code, "ROE(最新年报%)", fin.get("roe_latest"), *e["roe"]))
            print(f"   近3年ROE: {fin.get('roe_3y_json')} ｜ 报告期: {fin.get('report_date')}")
            print(check_range(code, "资产负债率%", fin.get("debt_ratio"), *e["debt"]))
            print(f"   营收复合增速%: {fin.get('revenue_cagr3') and round(fin['revenue_cagr3'],1)} ｜ "
                  f"净利复合增速%: {fin.get('profit_cagr3') and round(fin['profit_cagr3'],1)} ｜ "
                  f"现金流/净利: {fin.get('ocf_to_profit') and round(fin['ocf_to_profit'],2)}")
        else:
            print("❌ 财务数据拉取失败")
            ok = False

        hist = fetcher.fetch_pe_pb_history(code)
        last_pe = hist["pe"].dropna().iloc[-1] if hist["pe"].notna().any() else None
        last_pb = hist["pb"].dropna().iloc[-1] if hist["pb"].notna().any() else None
        print(f"-- 估值历史: {len(hist)} 行（{hist['trade_date'].min()} ~ {hist['trade_date'].max()}）--")
        print(check_range(code, "PE(TTM)最新", last_pe, *EXPECT[code]["pe"]))
        print(check_range(code, "PB最新", last_pb, *EXPECT[code]["pb"]))
        s2 = db._query_df("SELECT total_mv, pe_ttm, pb FROM stock_snapshot WHERE code = ?", (code,))
        if not s2.empty:
            print(f"快照回填: 总市值 {fmt(s2['total_mv'].iloc[0], 1e8, 0)} 亿 ｜ "
                  f"PE {fmt(s2['pe_ttm'].iloc[0], 1, 2)} ｜ PB {fmt(s2['pb'].iloc[0], 1, 2)}")

        daily = fetcher.fetch_daily(code)
        print(f"-- 日线: {len(daily)} 行，最新 {daily['trade_date'].max()}，"
              f"近20日成交额均值 {daily['turnover'].tail(20).mean()/1e8:.1f} 亿 --")

        dv = fetcher.fetch_dividend_yield(code)
        print(check_range(code, "股息率%", dv, *EXPECT[code]["dv"]))

        gw = fetcher.fetch_goodwill_ratio(code)
        print(f"{'✅' if gw is not None else '⚠️ '} 商誉/净资产%: {gw if gw is None else round(gw, 2)}")

        # 缓存生效性：再次调用应直接命中缓存（对比关键字段而非整行）
        fin2 = fetcher.fetch_finance(code)
        same = (fin2 is not None and fin is not None
                and fin2["roe_latest"] == fin["roe_latest"]
                and fin2["report_date"] == fin["report_date"])
        print(f"财务缓存命中: {'✅' if same else '❌ 缓存不一致'}")

    # 行业补源测试：宁德时代不在新浪行业板块，应能通过巨潮个股概况补全
    print(f"\n== 行业补源（巨潮个股概况，缺行业股票）==")
    missing = db._query_df("SELECT code FROM stock_snapshot WHERE code = '300750' "
                           "AND (industry IS NULL OR industry = '')")
    if missing.empty:
        print("300750 已有行业")
    else:
        n = fetcher.fetch_industry_fill(codes=["300750"])
        ind = db._query_df("SELECT industry FROM stock_snapshot WHERE code = '300750'")
        print(f"回填 {n} 只，300750 行业 → {ind['industry'].iloc[0] if not ind.empty else '仍缺失'}")

    print(f"\n== 数据库概览 ==")
    for t in ("stock_snapshot", "stock_finance", "stock_daily", "trade_calendar"):
        df = db._query_df(f"SELECT COUNT(*) AS n FROM {t}")
        print(f"{t}: {df['n'].iloc[0]} 行")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
