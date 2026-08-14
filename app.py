#!/usr/bin/env python3
"""阶段 4：FastAPI 网站入口。四页面：/ /stock/{code} /history /methodology。

启动：.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import analyzer
import db
import data_fetcher as fetcher
import screener

BASE = Path(__file__).resolve().parent

app = FastAPI(title="每日 3 只优质股（学习用）")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))

BADGE_LABELS = {"buy": "值得买入", "buy_batch": "建议分批买入", "hold": "暂不建议买入"}


# ---------- 展示格式化 ----------

def fmt1(v: Optional[float]) -> str:
    return "-" if v is None else f"{v:.1f}"


def fmt2(v: Optional[float]) -> str:
    return "-" if v is None else f"{v:.2f}"


def fmt_pct(v: Optional[float]) -> str:
    return "-" if v is None else f"{v:.0f}%"


def fmt_amount(v: Optional[float]) -> str:
    """元 → 亿/万。"""
    if v is None:
        return "-"
    if v >= 1e8:
        return f"{v / 1e8:.0f} 亿"
    if v >= 1e4:
        return f"{v / 1e4:.0f} 万"
    return f"{v:.0f} 元"


templates.env.globals.update(badge_labels=BADGE_LABELS, fmt1=fmt1, fmt2=fmt2,
                             fmt_pct=fmt_pct, fmt_amount=fmt_amount)


# ---------- 每日筛选：晨间一键运行（start.sh）+ 启动自检兜底（02 技术方案 §4） ----------

_run_lock = threading.Lock()


def _run_today(reason: str) -> None:
    """完整跑一遍当日筛选（force 刷新快照 + 选股 + 结论），幂等覆盖当日结果。"""
    if not _run_lock.acquire(blocking=False):
        print(f"[run] 已有筛选任务进行中，跳过（{reason}）", flush=True)
        return
    try:
        fetcher.fetch_snapshot(force=True)   # force：刷新最新价，避免快照 TTL=当天 停留旧值
        screener.run()
        analyzer.run()
        print(f"[run] 当日筛选完成（{reason}）", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[run] 筛选失败（{reason}）: {e}", flush=True)
    finally:
        _run_lock.release()


def _maybe_backfill() -> None:
    """启动自检（后台线程，不阻塞启动）：今天交易日且尚无当日推荐 → 补跑。

    日常主路径是 ./start.sh（先跑 scripts/daily_run.py 再开网站）；本函数只是
    用户直接以 uvicorn 启动网站时的兜底。
    """
    try:
        td = fetcher.latest_trade_date()
        if td != date.today().isoformat():
            return
        if not db.get_recommendations(td).empty:
            return
    except Exception:  # noqa: BLE001
        return
    threading.Thread(target=_run_today, args=("启动自动运行",), daemon=True).start()


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    _maybe_backfill()


# ---------- 页面数据组装 ----------

def _stock_basis(code: str) -> dict:
    """详情页共用的行情与指标数据（快照 + 日线）。"""
    snap = db.get_snapshot_row(code)
    daily = db.get_daily(code)
    close_s = daily["close"].dropna() if daily is not None and not daily.empty else None
    price = snap["price"] if snap and snap["price"] else None
    if price is None and close_s is not None and len(close_s):
        price = float(close_s.iloc[-1])
    chg = None
    if price and close_s is not None and len(close_s) >= 2:
        prev = float(close_s.iloc[-2])
        if prev > 0:
            chg = (price - prev) / prev * 100
    ma20 = float(close_s.tail(20).mean()) if close_s is not None and len(close_s) >= 20 else None
    ma60 = float(close_s.tail(60).mean()) if close_s is not None and len(close_s) >= 60 else None
    hi52 = float(close_s.tail(252).max()) if close_s is not None and len(close_s) >= 60 else None
    drawdown = (hi52 - price) / hi52 * 100 if hi52 and price else None
    return {"price": price, "chg": chg, "ma20": ma20, "ma60": ma60, "drawdown": drawdown}


def _indicator_groups(rec, snap, fin, basis, pb_pct) -> list[dict]:
    """五组指标（03 规范 §4.3），每个指标带通俗解释。"""
    roe3 = json.loads(fin["roe_3y_json"] or "[]") if fin and fin["roe_3y_json"] else []
    roe3_txt = " · ".join(f"{v:.1f}%" for v in roe3) if len(roe3) == 3 else "-"
    avg20 = snap["turnover_avg20"] if snap else None
    return [
        {"title": "估值", "items": [
            {"v": fmt1(rec["pe_ttm"]), "k": "PE-TTM（市盈率）", "d": "按当前盈利水平多少年回本"},
            {"v": fmt_pct(rec["pe_percentile"]), "k": "PE 5 年分位", "d": "越低代表越比自己过去便宜"},
            {"v": fmt2(snap["pb"] if snap else None), "k": "PB（市净率）", "d": "股价相对每股净资产的倍数"},
            {"v": fmt_pct(pb_pct), "k": "PB 5 年分位", "d": "越低代表越比自己过去便宜"},
        ]},
        {"title": "盈利", "items": [
            {"v": f"{fmt1(fin['roe_latest'])}%" if fin and fin["roe_latest"] is not None else "-",
             "k": "ROE（最新年报）", "d": "股东的钱一年赚多少"},
            {"v": roe3_txt, "k": "近 3 年 ROE", "d": "盈利能力的持续性"},
            {"v": f"{fmt1(fin['gross_margin'])}%" if fin and fin["gross_margin"] is not None else "-",
             "k": "毛利率", "d": "每 100 元收入扣成本剩多少"},
            {"v": f"{fmt1(fin['net_margin'])}%" if fin and fin["net_margin"] is not None else "-",
             "k": "净利率", "d": "每 100 元收入净赚多少"},
        ]},
        {"title": "成长", "items": [
            {"v": f"{fmt1(fin['revenue_cagr3'])}%" if fin and fin["revenue_cagr3"] is not None else "-",
             "k": "营收复合增速", "d": "近 3 年收入每年平均增长"},
            {"v": f"{fmt1(fin['profit_cagr3'])}%" if fin and fin["profit_cagr3"] is not None else "-",
             "k": "净利复合增速", "d": "近 3 年利润每年平均增长"},
        ]},
        {"title": "健康", "items": [
            {"v": f"{fmt1(fin['debt_ratio'])}%" if fin and fin["debt_ratio"] is not None else "-",
             "k": "资产负债率", "d": "欠债占总资产比例，越低越稳健"},
            {"v": fmt2(fin["ocf_to_profit"]) if fin else "-", "k": "现金流 / 净利", "d": "利润含金量，≥1 赚的是真钱"},
            {"v": f"{fmt1(fin['goodwill_ratio'])}%" if fin and fin["goodwill_ratio"] is not None else "-",
             "k": "商誉 / 净资产", "d": "并购遗留虚资产，过高有减值风险"},
            {"v": f"{fmt2(snap['dividend_yield'])}%" if snap and snap["dividend_yield"] is not None else "-",
             "k": "股息率", "d": "一年分红 ÷ 股价"},
        ]},
        {"title": "技术", "items": [
            {"v": fmt2(basis["ma20"]), "k": "MA20（20 日均价）", "d": "现价在其上说明短期趋势向上"},
            {"v": fmt2(basis["ma60"]), "k": "MA60（60 日均价）", "d": "现价在其上说明中期趋势向上"},
            {"v": f"{fmt1(basis['drawdown'])}%" if basis["drawdown"] is not None else "-",
             "k": "52 周回撤", "d": "距一年内最高点跌了多少，小则走势强"},
            {"v": fmt_amount(avg20), "k": "20 日均成交额", "d": "平均每天成交多少，衡量流动性"},
        ]},
    ]


# ---------- 路由 ----------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    recs = db.get_recommendations()
    if recs.empty:
        return templates.TemplateResponse(request, "index.html",
                                          {"active": "index", "recs": [], "rec_date": "-",
                                           "banner": "还没有推荐数据。请在终端运行 ./start.sh 生成"
                                                     "（约 3~5 分钟），完成后刷新本页。",
                                           "update_note": None})
    rec_date = recs["rec_date"].max()
    rows = db.get_recommendations(rec_date)
    out = []
    for _, r in rows.iterrows():
        note = (f"PE 处于近 5 年 {r['pe_percentile']:.0f}% 分位"
                if r["pe_percentile"] is not None else "估值历史数据不足")
        out.append({**r.to_dict(), "verdict_note": note})
    # 数据状态（阶段 5.3 降级提示）：推荐落后于最新交易日 → 提示；当日筛选成功 → 显示更新时间
    banner, update_note = None, None
    try:
        td = fetcher.latest_trade_date()
        log = db.get_last_screening_log()
        if td and rec_date != td:
            banner = (f"今日（{td}）的推荐还没有生成，以下显示的是 {rec_date} 的结果。"
                      "请在终端运行 ./start.sh 更新，完成后刷新本页。")
            if log and log["run_date"] == td and log["status"] == "error" and log["error_msg"]:
                banner += f"（最近一次筛选失败：{log['error_msg']}）"
        elif log and log["run_date"] == td and log["status"] == "ok" and log["run_time"]:
            update_note = f"已于 {log['run_time'][11:16]} 更新"
    except Exception:  # noqa: BLE001 日历/日志不可用则静默降级
        pass
    return templates.TemplateResponse(request, "index.html",
                                      {"active": "index", "recs": out, "rec_date": rec_date,
                                       "banner": banner, "update_note": update_note})


@app.get("/stock/{code}", response_class=HTMLResponse)
def stock_page(request: Request, code: str):
    rec = db.get_latest_recommendation(code)
    snap = db.get_snapshot_row(code)
    if rec is None and snap is None:
        return templates.TemplateResponse(request, "stock.html",
                                          {"active": "", "stock": None, "rec": None}, 404)
    stock = dict(snap) if snap else {"code": code, "name": rec["name"] if rec else code,
                                     "industry": rec["industry"] if rec else None,
                                     "price": None, "pe_ttm": None, "pb": None,
                                     "total_mv": None, "turnover_avg20": None,
                                     "dividend_yield": None}
    fin = db.get_finance(code)
    basis = _stock_basis(code)
    daily = db.get_daily(code)
    pb_pct = None
    if daily is not None and not daily.empty and basis["price"]:
        pb_s = daily["pb"].dropna()
        pb_s = pb_s[pb_s > 0]
        last_pb = snap["pb"] if snap and snap["pb"] else (pb_s.iloc[-1] if not pb_s.empty else None)
        if not pb_s.empty and last_pb:
            pb_pct = screener.pe_percentile(pb_s, float(last_pb))
    groups = _indicator_groups(rec, snap, fin, basis, pb_pct) if rec is not None else []
    return templates.TemplateResponse(request, "stock.html", {
        "active": "", "stock": stock, "rec": rec, "price": basis["price"], "chg": basis["chg"],
        "groups": groups,
    })


@app.get("/history", response_class=HTMLResponse)
def history(request: Request):
    recs = db.get_recommendations()
    groups = []
    if not recs.empty:
        for rec_date, df in recs.groupby("rec_date", sort=False):
            rows = []
            for _, r in df.iterrows():
                basis = _stock_basis(r["code"])
                cur = basis["price"]
                gain = None
                if cur and r["close_price"]:
                    gain = (cur - r["close_price"]) / r["close_price"] * 100
                rows.append({**r.to_dict(), "current_price": cur, "gain": gain})
            groups.append({"date": rec_date, "rows": rows})
    return templates.TemplateResponse(request, "history.html",
                                      {"active": "history", "groups": groups})


@app.get("/methodology", response_class=HTMLResponse)
def methodology(request: Request):
    return templates.TemplateResponse(request, "methodology.html", {"active": "methodology"})
