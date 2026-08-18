#!/usr/bin/env python3
"""阶段 3：买入结论引擎。按 文档/04-选股逻辑规范.md §9 生成结论与参考价位。

用法：.venv/bin/python analyzer.py [--date YYYY-MM-DD] [--dry-run]
- 默认处理最近一次筛选日期的推荐记录
- 回填 recommendations 的 verdict / verdict_reason / ref_price_low / ref_price_high
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

import db
import screener
from data_fetcher import latest_trade_date

DISCLAIMER = "仅供学习参考，不构成投资建议。股市有风险，投资需谨慎。"
LABELS = {"buy": "值得买入", "buy_batch": "建议分批买入", "hold": "暂不建议买入"}


def _pe30_price(code: str, pe_ttm: Optional[float], close: float,
                years: int = 5) -> Optional[float]:
    """PE 分位 30% 对应价 = 近 N 年 PE 序列第 30 百分位值 ÷ 当前 PE × 收盘价（04 规范 §9.2）。"""
    if not pe_ttm or pe_ttm <= 0 or not close or close <= 0:
        return None
    d = db.get_daily(code)
    if d is None or d.empty:
        return None
    s = d["pe"].dropna()
    s = s[s > 0]
    if len(s) < 250:
        return None
    pe30 = s.quantile(0.30)
    if pe30 <= 0:
        return None
    return round(float(pe30 / pe_ttm * close), 2)


def analyze(code: str, close: float, pe_ttm: Optional[float],
            pe_pct: Optional[float]) -> dict:
    """对单只推荐生成结论。返回 dict(verdict, verdict_reason, ref_low, ref_high)。"""
    daily = db.get_daily(code)
    t_score, t_note = screener.score_technical(daily)

    # 参考价位：MA20~MA60 区间（前复权口径，0.01 元精度）
    close_s = daily["close"].dropna() if daily is not None and not daily.empty else pd.Series(dtype=float)
    ma20 = float(close_s.tail(20).mean()) if len(close_s) >= 20 else float(close)
    ma60 = float(close_s.tail(60).mean()) if len(close_s) >= 60 else ma20
    ref_low, ref_high = round(min(ma20, ma60), 2), round(max(ma20, ma60), 2)

    # 结论判定（04 规范 §9.1）
    if pe_pct is None:
        verdict = "buy_batch" if t_score >= 14 else "hold"
        est_note = "（估值历史数据不足，按保守规则判定）"
    elif pe_pct >= 50 or t_score < 8:
        verdict = "hold"
        est_note = ""
    elif pe_pct < 30 and t_score >= 14:
        verdict = "buy"
        est_note = ""
    else:
        verdict = "buy_batch"
        est_note = ""

    # 理由文本（04 规范 §9.3）
    if verdict == "buy":
        why = (f"PE-TTM {pe_ttm:.1f} 处于近 5 年 {pe_pct:.0f}% 分位，估值处于历史低位；"
               f"技术走势健康（{t_note}）。")
    elif verdict == "buy_batch":
        why = (f"PE 分位 {pe_pct:.0f}%、技术分 {t_score} 分（{t_note}），"
               f"估值与技术未同时处于最佳状态，分批买入更稳妥。")
        if pe_pct is None:
            why = f"估值历史数据不足，技术走势（{t_note}）良好，可小仓分批尝试。"
    else:
        if pe_pct is not None and pe_pct >= 50:
            why = f"PE 处于近 5 年 {pe_pct:.0f}% 分位，高于历史中位数，等待更好价格。"
        else:
            why = f"技术分 {t_score} 分（{t_note}），走势偏弱，不接下跌趋势。"
    if pe_pct is None and verdict != "hold":
        why += est_note

    # 现价与参考区间的关系（§9.2）
    if ref_high - ref_low < close * 0.01:   # 20/60 日线粘合，区间退化为单点
        pos = "当前价已接近均线，可参考均线附近分批"
        price_line = f"参考价位约 {ref_low:.2f} 元附近（20/60 日均线已粘合），{pos}。"
    elif close <= ref_high:
        price_line = (f"参考价位 {ref_low:.2f} ~ {ref_high:.2f} 元（20/60 日均线区间），"
                      f"当前价已处于参考区间内。")
    else:
        price_line = (f"参考价位 {ref_low:.2f} ~ {ref_high:.2f} 元（20/60 日均线区间），"
                      f"现价 {close:.2f} 元高于区间上沿，建议等待回调至区间内。")

    pe30 = _pe30_price(code, pe_ttm, close)
    if pe30:
        if pe30 > close:
            pe30_line = f"估值修复至历史 PE 30% 分位水平，对应约 {pe30:.2f} 元（上行参考）。"
        else:
            pe30_line = f"回到历史 PE 30% 分位水平，对应约 {pe30:.2f} 元（下行参考）。"
    else:
        pe30_line = ""

    reason = f"{LABELS[verdict]}：{why}\n{price_line}"
    if pe30_line:
        reason += f"\n{pe30_line}"
    reason += f"\n{DISCLAIMER}"

    return {"verdict": verdict, "verdict_reason": reason,
            "ref_low": ref_low, "ref_high": ref_high}


def run(date_str: Optional[str] = None, dry_run: bool = False) -> list[dict]:
    """对指定日期（默认最近一次筛选）的全部推荐生成结论并回填。"""
    db.init_db()
    if date_str is None:
        recs = db.get_recommendations()
        date_str = recs["rec_date"].max() if not recs.empty else latest_trade_date()
    recs = db.get_recommendations(date_str)
    if recs.empty:
        print(f"{date_str} 无推荐记录，请先运行 screener.py")
        return []

    results = []
    for _, r in recs.iterrows():
        out = analyze(r["code"], float(r["close_price"] or 0), r["pe_ttm"], r["pe_percentile"])
        out.update({"code": r["code"], "name": r["name"], "rank": int(r["rank"]),
                    "industry": r["industry"]})
        if not dry_run:
            db.set_verdict(date_str, r["code"], out["verdict"], out["verdict_reason"],
                           out["ref_low"], out["ref_high"])
        results.append(out)
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="买入结论引擎（04 规范 §9）")
    ap.add_argument("--date", help="推荐日期 YYYY-MM-DD，默认最近一次筛选日期")
    ap.add_argument("--dry-run", action="store_true", help="只计算不回写数据库")
    args = ap.parse_args()

    results = run(args.date, args.dry_run)
    for r in results:
        print(f"#{r['rank']} {r['code']} {r['name']} → {LABELS[r['verdict']]}"
              f"（参考 {r['ref_low']}~{r['ref_high']}）")
        print(r["verdict_reason"])
        print()
    if not args.dry_run and results:
        print("已回写数据库 recommendations 表")
    return 0


if __name__ == "__main__":
    sys.exit(main())
