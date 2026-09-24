"""选股引擎（阶段 2）。逐关实现 文档/04-选股逻辑规范.md，唯一标准以该文档为准。

用法：
    .venv/bin/python screener.py            # 运行当日筛选，写入 recommendations
    .venv/bin/python screener.py --dry-run  # 只计算与打印，不写库（试跑/验收）

流程：① 基础过滤 → ② 质量关 → ③ 估值关 → ④ 打分 → ⑤ 排序与选择（行业分散 + 60 天冷却期）。
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd

import data_fetcher as fetcher
import db

# ---------- 阈值与常量（引自 04 规范，改动需先改文档） ----------

MIN_TURNOVER_TODAY = 2e7        # 初筛：当日成交额 ≥ 2000 万
MIN_TURNOVER_AVG20 = 5e7        # 精确：20 日均成交额 ≥ 5000 万
MIN_LIST_YEARS = 3              # 上市满 3 年
ROE_MIN = 12.0                  # 最新年报 ROE ≥ 12%
ROE_3Y_MIN = 10.0               # 近 3 年每年 ROE ≥ 10%
DEBT_MAX = 60.0                 # 资产负债率 < 60%（高杠杆行业 < 85%）
DEBT_MAX_HIGH_LEVERAGE = 85.0
OCF_MIN = 0.7                   # 经营现金流/净利润 ≥ 0.7
PE_MAX = 50.0                   # 0 < PE-TTM < 50
PE_PCT_MAX = 50.0               # PE 分位 < 50%
PB_PCT_MAX = 70.0               # PB 分位 < 70%
COOLDOWN_DAYS = 60              # 冷却期

# 高杠杆/金融行业（行业名包含即命中）：负债率放宽 + 现金流指标豁免
HIGH_LEVERAGE_KEYWORDS = ("银行", "保险", "证券", "房地产")
FINANCIAL_KEYWORDS = ("银行", "保险", "证券")


def is_financial(industry: Optional[str]) -> bool:
    return bool(industry) and any(k in industry for k in FINANCIAL_KEYWORDS)


def is_high_leverage(industry: Optional[str]) -> bool:
    return bool(industry) and any(k in industry for k in HIGH_LEVERAGE_KEYWORDS)


# ---------- ① 基础过滤 ----------

def _market_in_session() -> bool:
    """粗略判断是否盘中（9:15~15:05）。盘中当日成交额尚未累积完，不可作流动性初筛。"""
    minutes = datetime.now().hour * 60 + datetime.now().minute
    return 9 * 60 + 15 <= minutes <= 15 * 60 + 5


def base_pool(trade_date: str) -> pd.DataFrame:
    """基础过滤：剔除 ST/次新/停牌/低流动性（初筛）。返回候选池 DataFrame。"""
    cutoff = (date.fromisoformat(trade_date) - timedelta(days=365 * MIN_LIST_YEARS)).isoformat()
    snap = db.get_snapshot()
    if snap.empty:
        return snap
    df = snap[snap["list_date"].notna()].copy()
    df = df[df["list_date"] <= cutoff]                                # 次新股
    df = df[df["name"].notna() & ~df["name"].str.contains("ST|退", na=False)]  # ST/退市
    df = df[df["price"].notna() & (df["price"] > 0)]                  # 停牌/异常
    if _market_in_session():
        # 盘中：当日成交额还在累积（开盘前后快照该字段甚至全为 0，2026-08-14 实测会误杀全市场），
        # 初筛跳过成交额门槛，流动性由打分前的"20 日均成交额 ≥ 5000 万"精确核查兜底（04 规范 §2 盘中例外）
        df = df[df["turnover_today"].notna()]
    else:
        df = df[df["turnover_today"].notna() & (df["turnover_today"] >= MIN_TURNOVER_TODAY)]
    return df


# ---------- ② 质量关 ----------

def quality_check(fin: Optional[Any], industry: Optional[str]) -> tuple[bool, str]:
    """质量关硬门槛。返回 (是否通过, 未通过原因；通过时为空串)。

    按 04 规范 §7：ROE/营收/净利缺失 → 剔除；现金流、股息率缺失 → 计 0 分不剔除
    （此处只判硬门槛，计分在 score_quality 中处理）。
    """
    if fin is None:
        return False, "财务数据缺失"
    fin = dict(fin)

    roe = fin.get("roe_latest")
    if roe is None or roe < ROE_MIN:
        return False, f"最新ROE {_f(roe)} < {ROE_MIN}%"
    try:
        roe3 = json.loads(fin.get("roe_3y_json") or "[]")
    except ValueError:
        roe3 = []
    if len(roe3) < 3 or any((v is None or v < ROE_3Y_MIN) for v in roe3):
        return False, f"近3年ROE不达标 {roe3}"

    financial = is_financial(industry)
    rev = fin.get("revenue_cagr3")
    if rev is None and financial:   # 注 2：金融业无营收增速时以净利增速替代
        rev = fin.get("profit_cagr3")
    if rev is None or rev <= 0:
        return False, f"营收复合增速 {_f(rev)} 不达标"
    pro = fin.get("profit_cagr3")
    if pro is None or pro <= 0:
        return False, f"净利复合增速 {_f(pro)} 不达标"

    debt = fin.get("debt_ratio")
    debt_max = DEBT_MAX_HIGH_LEVERAGE if is_high_leverage(industry) else DEBT_MAX
    if debt is None or debt >= debt_max:
        return False, f"资产负债率 {_f(debt)} ≥ {debt_max}%"

    ocf = fin.get("ocf_to_profit")
    if not financial and ocf is not None and ocf < OCF_MIN:   # 注 3：金融业豁免；缺失计 0 分不剔除
        return False, f"现金流/净利 {_f(ocf)} < {OCF_MIN}"
    return True, ""


# ---------- ③ 估值关 ----------

def pe_percentile(series: pd.Series, current: float) -> Optional[float]:
    """PE 分位（%）= 序列中小于当前值的个数 / 总数 × 100。无效值不参与。"""
    s = series.dropna()
    s = s[s > 0]
    if s.empty:
        return None
    return float((s < current).sum() / len(s) * 100)


def valuation_check(code: str, trade_date: str) -> tuple[bool, str, dict]:
    """估值关：拉取估值历史序列，检查 PE 范围、PE/PB 分位。返回 (通过, 原因, 结果数据)。

    结果数据含 pe_ttm/pb/pe_pct/pb_pct/rows；序列不足 1 年时视为分位不可算
    （04 规范 §7：估值子项计 10 分中性，页面标注历史数据不足）。
    """
    hist = fetcher.fetch_pe_pb_history(code)
    if hist is None or hist.empty:
        return False, "估值历史获取失败", {}

    # 当前 PE/PB：取序列最后一个有效值（跳过占位值 ≤0；序列已增量到最近交易日）
    pe_valid = hist["pe"].dropna()
    pe_valid = pe_valid[pe_valid > 0]
    pb_valid = hist["pb"].dropna()
    pb_valid = pb_valid[pb_valid > 0]
    last_pe = pe_valid.iloc[-1] if not pe_valid.empty else None
    last_pb = pb_valid.iloc[-1] if not pb_valid.empty else None
    if last_pe is None or pd.isna(last_pe) or not (0 < last_pe < PE_MAX):
        return False, f"PE-TTM {_f(last_pe)} 不在 (0, {PE_MAX})", {"pe_ttm": last_pe}
    if last_pb is None or pd.isna(last_pb):
        return False, "PB 缺失", {"pe_ttm": last_pe}

    # 近 5 年序列（不足 5 年按实际，04 规范 §4）
    start5 = (date.fromisoformat(trade_date) - timedelta(days=365 * 5)).isoformat()
    recent = hist[hist["trade_date"] >= start5]
    pct_ok = len(recent) >= 250   # 不足 1 年序列分位不可靠，按不可算处理
    pe_pct = pe_percentile(recent["pe"], last_pe) if pct_ok else None
    pb_pct = pe_percentile(recent["pb"], last_pb) if pct_ok else None

    if pe_pct is not None and pe_pct >= PE_PCT_MAX:
        return False, f"PE分位 {pe_pct:.0f}% ≥ {PE_PCT_MAX}%", {"pe_ttm": last_pe, "pe_pct": pe_pct}
    if pb_pct is not None and pb_pct >= PB_PCT_MAX:
        return False, f"PB分位 {pb_pct:.0f}% ≥ {PB_PCT_MAX}%", {"pe_ttm": last_pe, "pe_pct": pe_pct, "pb_pct": pb_pct}
    return True, "", {"pe_ttm": last_pe, "pb": last_pb, "pe_pct": pe_pct, "pb_pct": pb_pct,
                      "rows": len(recent)}


# ---------- ④ 打分 ----------

def score_quality(fin: dict, dividend: Optional[float], industry: Optional[str]) -> tuple[int, list[str]]:
    """质量分（满分 40）。返回 (得分, 亮点说明)。04 规范 §5 v1.3：
    ROE 12 + 成长 10 + 现金流 8 + 股东回报 10（股息率 3 + 分红率 4 + 回购率 3）。"""
    parts = []  # (名称, 得分, 满分)

    roe = fin.get("roe_latest") or 0
    roe_score = 12 if roe > 20 else 9 if roe >= 15 else 6 if roe >= 12 else 0
    parts.append(("ROE", roe_score, 12))

    rev = fin.get("revenue_cagr3")
    pro = fin.get("profit_cagr3")
    if rev is None and is_financial(industry):
        rev = pro  # 注 2：金融业以净利增速替代
    rev_score = 5 if rev is not None and rev > 20 else 4 if rev is not None and rev >= 10 \
        else 2 if rev is not None and rev > 0 else 0
    pro_score = 5 if pro is not None and pro > 20 else 4 if pro is not None and pro >= 10 \
        else 2 if pro is not None and pro > 0 else 0
    parts.append(("成长", rev_score + pro_score, 10))

    ocf = fin.get("ocf_to_profit")
    if is_financial(industry) and ocf is None:
        ocf_score = 0
    else:
        ocf_score = 8 if ocf is not None and ocf >= 1.0 else 5 if ocf is not None and ocf >= OCF_MIN else 0
    parts.append(("现金流", ocf_score, 8))

    # 股东回报 10 = 股息率(3) + 分红率(4) + 回购率(3)；分红率/回购率缺失计 0 分不剔除（04 §7）
    div_sub = 3 if dividend is not None and dividend > 2 else 2 if dividend is not None and dividend >= 1 \
        else 1 if dividend is not None and dividend > 0 else 0
    payout = fin.get("payout_ratio")
    pay_sub = 4 if payout is not None and payout > 70 else 3 if payout is not None and payout >= 50 \
        else 2 if payout is not None and payout >= 30 else 1 if payout is not None else 0
    buyback = fin.get("buyback_ratio")
    bb_sub = 3 if buyback is not None and buyback > 20 else 2 if buyback is not None and buyback > 10 \
        else 1 if buyback is not None and buyback > 0 else 0
    parts.append(("股东回报", div_sub + pay_sub + bb_sub, 10))

    highlights = [f"{n} {s}/{m}" for n, s, m in parts]
    return sum(s for _, s, _ in parts), highlights


def score_valuation(pe_pct: Optional[float]) -> int:
    """估值分（满分 40）：PE 分位越低分越高；分位不可算计 10 分中性（04 规范 §7）。"""
    if pe_pct is None:
        return 10
    if pe_pct < 20:
        return 40
    if pe_pct < 35:
        return 30
    if pe_pct < 50:
        return 20
    if pe_pct < 70:
        return 10
    return 0


def score_technical(daily: pd.DataFrame) -> tuple[int, str]:
    """技术分（满分 20）：MA60 +8 / MA20 +6 / 距 52 周高点回撤 <20% +6。"""
    if daily is None or daily.empty or daily["close"].dropna().empty:
        return 0, "日线缺失"
    close = daily["close"].dropna()
    last = close.iloc[-1]
    notes = []
    s = 0
    if len(close) >= 60 and last > close.tail(60).mean():
        s += 8
        notes.append("站上60日线")
    if len(close) >= 20 and last > close.tail(20).mean():
        s += 6
        notes.append("站上20日线")
    hi52 = close.tail(252).max() if len(close) >= 60 else close.max()
    if hi52 > 0 and (hi52 - last) / hi52 < 0.2:
        s += 6
        notes.append("距52周高点回撤<20%")
    return s, ("、".join(notes) if notes else "技术面偏弱")


# 技术面术语 → 大白话（筛选理由用，04 规范 §8）
TECH_NOTE_PLAIN = {
    "站上60日线": "现价高于近 60 天平均价（中期趋势向上）",
    "站上20日线": "现价高于近 20 天平均价（短期趋势向上）",
    "距52周高点回撤<20%": "距一年内最高价回撤不到 20%（走势强）",
    "技术面偏弱": "走势偏弱",
    "日线缺失": "日线数据缺失",
}


# ---------- ⑤ 排序与选择 ----------

def select_top(candidates: list[dict], trade_date: str, limit: int = 3) -> list[dict]:
    """按总分降序 + 行业分散（同行业每天最多 1 只）+ 60 天冷却期，取前 limit 名。"""
    candidates.sort(key=lambda c: c["score"], reverse=True)
    # 同日幂等重跑：当日已有推荐不计入冷却名单，否则重跑会排除真 Top3 选到次优
    cooled = db.get_recent_recommended_codes(COOLDOWN_DAYS, exclude_date=trade_date)
    picked, used_industries = [], set()
    for c in candidates:
        if len(picked) >= limit:
            break
        if c["code"] in cooled:
            continue
        ind = c["industry"] or "未分类"
        if ind in used_industries:
            continue
        picked.append(c)
        used_industries.add(ind)
    return picked


# ---------- 主流程 ----------

def run(trade_date: Optional[str] = None, dry_run: bool = False) -> dict:
    """执行当日筛选，返回结果摘要。dry_run=True 时不写库。"""
    trade_date = trade_date or fetcher.latest_trade_date()
    db.init_db()
    run_time = datetime.now().isoformat(timespec="seconds")

    pool = base_pool(trade_date)
    pool_size = len(pool)
    if pool.empty:
        return _log(trade_date, run_time, pool_size, 0, 0, [], "error", "基础过滤后无候选",
                    dry_run)

    # 逐只过质量关 + 拉取股息率（04 规范注 4：只对通过其余质量指标的候选拉取）
    passed_q: list[dict] = []
    for _, row in pool.iterrows():
        code, industry = row["code"], row["industry"]
        fin = db.get_finance(code)
        ok, why = quality_check(fin, industry)
        if not ok:
            continue
        dividend = fetcher.fetch_dividend_yield(code)   # 失败返回 None，计 0 分不剔除
        passed_q.append({"code": code, "name": row["name"], "industry": industry,
                         "fin": dict(fin), "dividend": dividend})

    # 估值关 + 日线（20 日成交额精确核查 + 技术分）
    candidates: list[dict] = []
    for c in passed_q:
        ok, why, val = valuation_check(c["code"], trade_date)
        if not ok:
            continue
        daily = fetcher.fetch_daily(c["code"])
        avg20 = daily["turnover"].tail(20).mean() if daily is not None and not daily.empty \
            and daily["turnover"].notna().any() else None
        if avg20 is None or avg20 < MIN_TURNOVER_AVG20:
            continue   # 流动性是安全底线：20 日成交额无法核查不进入最终推荐（04 规范 §7）
        if not dry_run:
            db.set_snapshot_field(c["code"], "turnover_avg20", round(float(avg20), 2))

        q_score, q_high = score_quality(c["fin"], c["dividend"], c["industry"])
        v_score = score_valuation(val.get("pe_pct"))
        t_score, t_note = score_technical(daily)
        c.update({
            "pe_ttm": val.get("pe_ttm"), "pb": val.get("pb"),
            "pe_pct": val.get("pe_pct"), "pb_pct": val.get("pb_pct"),
            "avg20": avg20, "score": q_score + v_score + t_score,
            "q_score": q_score, "v_score": v_score, "t_score": t_score,
            "t_note": t_note, "q_high": q_high, "close": daily["close"].dropna().iloc[-1],
        })
        candidates.append(c)

    picked = select_top(candidates, trade_date)

    if not dry_run:
        db.clear_recommendations(trade_date)   # 幂等：同日先删后插（06 规范）

    # 筛选理由文本（04 规范 §8：面向金融小白，每条 = 指标是什么 + 本公司数值 + 为什么好）+ 写库
    for rank, c in enumerate(picked, 1):
        f = c["fin"]
        roe = f["roe_latest"]
        lines = [
            f"赚钱能力：ROE {roe:.1f}%（股东每投 100 元，公司一年能赚 {roe:.1f} 元），"
            f"连续 3 年都高于 10% 的及格线",
        ]
        if f.get("revenue_cagr3") is not None:
            lines.append(f"成长性：近 3 年收入平均每年增长 {f['revenue_cagr3']:.1f}%、"
                         f"利润平均每年增长 {f['profit_cagr3']:.1f}%——生意越做越大")
        else:
            lines.append(f"成长性：近 3 年利润平均每年增长 {f['profit_cagr3']:.1f}%——生意越做越大")
        lines.append(f"财务安全：资产负债率 {f['debt_ratio']:.1f}%（欠的债只占总资产的 "
                     f"{f['debt_ratio']:.1f}%，低于 60% 的安全线）"
                     + ("（该行业属高杠杆行业，安全线放宽到 85%）" if is_high_leverage(c["industry"]) else ""))
        if f.get("ocf_to_profit") is not None:
            lines.append(f"利润含金量：经营现金流是净利润的 {f['ocf_to_profit']:.2f} 倍"
                         f"（0.7 以上说明赚到的是真金白银，不是纸面利润）")
        else:
            lines.append("利润含金量：现金流数据缺失，该项计 0 分")
        if c["dividend"] is not None:
            lines.append(f"分红回报：股息率 {c['dividend']:.2f}%"
                         f"（持有 1 年，每 100 元投资大约能拿到 {c['dividend']:.2f} 元分红）")
        else:
            lines.append("分红回报：近 12 个月没有派息记录，该项计 0 分")
        if c["pe_pct"] is not None:
            lines.append(f"估值便宜：PE-TTM {c['pe_ttm']:.1f} 倍（按当前盈利大约 {c['pe_ttm']:.0f} 年回本），"
                         f"处于近 5 年最便宜的 {c['pe_pct']:.0f}% 区间"
                         f"（近 5 年有 {100 - c['pe_pct']:.0f}% 的时间比现在贵）")
        else:
            lines.append(f"估值：PE-TTM {c['pe_ttm']:.1f} 倍，历史数据不足无法比较贵贱")
        lines.append(f"买卖方便：平均每天成交 {c['avg20'] / 1e8:.1f} 亿元，想买想卖都容易")
        t_plain = "、".join(TECH_NOTE_PLAIN.get(n, n) for n in c["t_note"].split("、"))
        lines.append(f"综合得分 {c['score']:.0f} 分（满分 100）= 赚钱能力 {c['q_score']}/40"
                     f" + 估值便宜 {c['v_score']}/40 + 走势健康 {c['t_score']}/20（{t_plain}）")
        c["reasons"] = "\n".join(f"· {x}" for x in lines)
        c["rank"] = rank

        if not dry_run:
            db.insert_recommendation({
                "rec_date": trade_date, "code": c["code"], "name": c["name"],
                "industry": c["industry"], "rank": rank, "score": c["score"],
                "reasons": c["reasons"], "close_price": c["close"], "pe_ttm": c["pe_ttm"],
                "pe_percentile": c["pe_pct"], "roe": c["fin"].get("roe_latest"),
                "dividend_yield": c["dividend"], "created_at": run_time,
                # verdict / 参考价位由阶段 3 analyzer.py 生成
            })

    status = "ok" if len(picked) == 3 else "partial"
    result = _log(trade_date, run_time, pool_size, len(passed_q), len(candidates),
                  [{"rank": c["rank"], "code": c["code"], "name": c["name"],
                    "industry": c["industry"], "score": c["score"]} for c in picked],
                  status, "", dry_run, picked)
    if dry_run:
        result["details"] = picked   # 验收核对用：完整指标与理由
    return result


def _log(trade_date, run_time, pool_size, passed_q, passed_v, picked_summary,
         status, error_msg, dry_run, picked=None) -> dict:
    result = {
        "trade_date": trade_date, "pool_size": pool_size, "passed_quality": passed_q,
        "passed_valuation": passed_v, "picked": picked_summary, "status": status,
        "error_msg": error_msg,
    }
    if not dry_run:
        db.insert_screening_log({
            "run_date": trade_date, "run_time": run_time, "pool_size": pool_size,
            "passed_quality": passed_q, "passed_valuation": passed_v,
            "candidates_json": json.dumps(picked_summary, ensure_ascii=False),
            "status": status, "error_msg": error_msg,
        })
    return result


def _f(v: Any) -> str:
    return "-" if v is None else f"{v:.2f}"


def main() -> int:
    ap = argparse.ArgumentParser(description="按 04 规范执行当日选股")
    ap.add_argument("--dry-run", action="store_true", help="只计算不写库")
    args = ap.parse_args()
    r = run(dry_run=args.dry_run)
    print(f"筛选日期 {r['trade_date']} ｜ 股票池 {r['pool_size']} ｜ "
          f"质量关通过 {r['passed_quality']} ｜ 估值关通过 {r['passed_valuation']} ｜ "
          f"状态 {r['status']}")
    if r["error_msg"]:
        print(f"提示：{r['error_msg']}")
    for c in r["picked"]:
        print(f"\n#{c['rank']} {c['code']} {c['name']}（{c['industry']}）总分 {c['score']:.0f}")
    if not r["picked"]:
        print("今日无合格候选（或数据尚未就绪）")
    return 0


if __name__ == "__main__":
    main()
