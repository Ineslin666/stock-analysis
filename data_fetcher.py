"""数据获取层：akshare 接口封装 + SQLite 缓存（接口实测见 docs_notes/01-接口实测记录.md）

约定：
- 每个 fetch_* 先查缓存，未过期则直接返回缓存
- 所有网络调用统一走 _retry（3 次重试）与 _throttle（限流）
- 单只股票接口失败不抛出中断整体流程，返回 None/空，由调用方按 04 规范处理
"""
from __future__ import annotations

import math
import time
from datetime import date, datetime, timedelta
from typing import Callable, Optional

import akshare as ak
import pandas as pd

import db

# ---------- 缓存有效期 ----------
TTL_FINANCE_DAYS = 30      # 财务数据按季度更新，30 天足够
TTL_DIVIDEND_DAYS = 30     # 分红按年更新
TTL_GOODWILL_DAYS = 90     # 商誉按季度更新
TTL_CALENDAR_DAYS = 30
TTL_LIST_DAYS = 30

THROTTLE_SECONDS = 0.15    # 每只股票请求之间的间隔（避免被源站限流）


def _retry(fn: Callable, *args, times: int = 3, **kwargs):
    """网络调用重试：间隔 2/4/6 秒。"""
    last = None
    for i in range(times):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 数据源异常统一兜底
            last = e
            if i < times - 1:
                time.sleep(2 * (i + 1))
    raise last


def _throttle() -> None:
    time.sleep(THROTTLE_SECONDS)


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _today() -> str:
    return date.today().isoformat()


# ---------- 交易日历 ----------

def fetch_trade_calendar(force: bool = False) -> pd.DataFrame:
    """交易日历（新浪，1990 至今）。缓存 30 天。"""
    df = db._query_df("SELECT cal_date FROM trade_calendar")
    if not force and not df.empty:
        return df
    raw = _retry(ak.tool_trade_date_hist_sina)
    db.upsert_trade_calendar(raw)
    return db._query_df("SELECT cal_date FROM trade_calendar")


def latest_trade_date(day: Optional[str] = None) -> Optional[str]:
    """≤ 指定日期（默认今天）的最近一个交易日。"""
    day = day or _today()
    dates = db.get_trade_dates(end=day)
    return dates[-1] if dates else None


# ---------- 股票列表（含上市日期） ----------

def _code6(value) -> str:
    return str(int(value)).zfill(6)


def fetch_stock_list(force: bool = False) -> pd.DataFrame:
    """沪主板 + 科创板 + 深市（主板/创业板）股票列表，含上市日期。缓存 30 天。"""
    if not force:
        cached = db._query_df("SELECT code, name, list_date FROM stock_snapshot WHERE list_date IS NOT NULL")
        if len(cached) >= 4000:
            return cached

    frames = []
    for market, fn, kwargs in (
        ("sh", ak.stock_info_sh_name_code, {"symbol": "主板A股"}),
        ("sh", ak.stock_info_sh_name_code, {"symbol": "科创板"}),
        ("sz", ak.stock_info_sz_name_code, {"symbol": "A股列表"}),
    ):
        raw = _retry(fn, **kwargs)
        if market == "sh":
            sub = pd.DataFrame({
                "code": raw["证券代码"].map(_code6),
                "name": raw["证券简称"].astype(str).str.strip(),
                "list_date": raw["上市日期"].astype(str).str[:10],
            })
        else:
            sub = pd.DataFrame({
                "code": raw["A股代码"].map(_code6),
                "name": raw["A股简称"].astype(str).str.strip(),
                "list_date": raw["A股上市日期"].astype(str).str[:10],
            })
        frames.append(sub)
        _throttle()
    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset="code", keep="first")
    db.upsert_snapshot(df[["code", "name", "list_date"]].to_dict("records"))
    return df


# ---------- 全市场快照（新浪全市场 + 新浪行业板块 + 东财个股信息补源） ----------

def _normalize_sina_code(value) -> str:
    """新浪代码格式 sh600519 / sz000001 / bj430047 → 6 位纯数字。"""
    s = str(value).lower().strip()
    for p in ("sh", "sz", "bj"):
        if s.startswith(p):
            s = s[len(p):]
    return s.zfill(6)


def fetch_snapshot(force: bool = False) -> pd.DataFrame:
    """全市场快照：价格 / 当日成交额（新浪全市场）+ 行业（新浪行业板块 + 巨潮补源）。

    行业与 PE/PB 的口径说明：新浪行业板块只覆盖约 3000 只，其余股票行业由
    fetch_industry_fill 用巨潮个股概况（证监会 2012 大类）补全；PE/PB 精确值对
    候选股用 fetch_pe_pb_history（stock_value_em）回填，快照不保证全市场 PE 覆盖。
    缓存 TTL = 当天（updated_at 早于今天则重拉）。
    """
    last = db.get_snapshot_last_update()
    if not force and last and str(last)[:10] == _today():
        return db.get_snapshot()

    now = datetime.now().isoformat(timespec="seconds")

    # 1) 新浪全市场：价格 + 当日成交额（覆盖约 5500 只）
    spot = _retry(ak.stock_zh_a_spot, times=4)
    spot["code"] = spot["代码"].map(_normalize_sina_code)
    spot = spot[spot["code"].str.match(r"^[036]\d{5}$")]  # 只留沪深 A 股
    db.upsert_snapshot([{
        "code": r["code"],
        "name": str(r["名称"]).replace(" ", ""),
        "price": r.get("最新价"),
        "turnover_today": r.get("成交额"),
        "updated_at": now,
    } for _, r in spot.iterrows()])

    # 2) 新浪行业板块成分 → 行业（覆盖约 3000 只）
    spots = _retry(ak.stock_sector_spot, indicator="新浪行业")
    label2industry = dict(zip(spots["label"], spots["板块"]))
    for label in spots["label"]:
        try:
            det = _retry(ak.stock_sector_detail, sector=label, times=4)
        except Exception:  # noqa: BLE001 单个板块失败不中断
            continue
        det = det.copy()
        det["code"] = det["code"].astype(str).str.zfill(6)
        det["industry"] = label2industry.get(label, "其他")
        db.upsert_snapshot([{
            "code": r["code"], "industry": r["industry"], "updated_at": now,
        } for _, r in det.iterrows()])
        _throttle()

    return db.get_snapshot()


def fetch_industry_fill(codes: Optional[list[str]] = None, force: bool = False) -> int:
    """行业补源：对快照中缺行业的股票，用巨潮个股概况（stock_profile_cninfo）的
    "所属行业"（证监会 2012 大类，如"酒、饮料和精制茶制造业"）回填。

    codes=None 时处理全部缺失者（约 3200 只，首次运行约 30 分钟，缓存在库长期有效）。
    返回本次回填数量。
    """
    if codes is None:
        df = db._query_df("SELECT code FROM stock_snapshot "
                          "WHERE list_date IS NOT NULL AND (industry IS NULL OR industry = '')")
        codes = df["code"].tolist()
    filled = 0
    for i, code in enumerate(codes, 1):
        if not force:
            snap = db._query_df("SELECT industry FROM stock_snapshot WHERE code = ?", (code,))
            if not snap.empty and snap["industry"].iloc[0]:
                continue
        _throttle()
        try:
            p = _retry(ak.stock_profile_cninfo, symbol=code, times=3)
        except Exception:  # noqa: BLE001
            continue
        if p is None or p.empty:
            continue
        industry = str(p.iloc[0].get("所属行业") or "").strip()
        if industry:
            db.upsert_snapshot([{"code": code, "industry": industry,
                                 "updated_at": datetime.now().isoformat(timespec="seconds")}])
            filled += 1
        if i % 200 == 0:
            print(f"  行业补源进度 {i}/{len(codes)}，已回填 {filled}")
    return filled


# ---------- 财务指标（新浪，全市场最重的一步） ----------

def fetch_finance(code: str, force: bool = False) -> Optional[dict]:
    """单股财务指标：最新年报 ROE/负债率/现金流比率 + 近 3 年 ROE 与复合增速。

    缓存 30 天（财务报告按季度更新）。提取字段见 文档/06 stock_finance 表。
    """
    if not force:
        cached = db.get_finance(code)
        if cached and cached["updated_at"] and (
            datetime.now() - datetime.fromisoformat(cached["updated_at"])
        ).days < TTL_FINANCE_DAYS:
            return dict(cached)

    _throttle()
    try:
        raw = _retry(ak.stock_financial_analysis_indicator, symbol=code,
                     start_year=str(date.today().year - 3))
    except Exception:  # noqa: BLE001 新股/退市股等无数据
        return None
    if raw is None or raw.empty:
        return None

    raw["日期"] = raw["日期"].astype(str)
    annual = raw[raw["日期"].str.endswith("12-31")].copy()
    if annual.empty:
        return None

    def col(name: str) -> Optional[pd.Series]:
        return _num(annual[name]) if name in annual.columns else None

    roe = col("加权净资产收益率(%)")
    row: dict = {"code": code, "report_date": annual["日期"].iloc[-1],
                 "updated_at": datetime.now().isoformat(timespec="seconds")}
    if roe is not None and roe.notna().any():
        row["roe_latest"] = roe.iloc[-1]
        row["roe_3y_json"] = roe.dropna().tail(3).tolist()
    for key, name in (("debt_ratio", "资产负债率(%)"), ("gross_margin", "销售毛利率(%)"),
                      ("net_margin", "销售净利率(%)")):
        s = col(name)
        if s is not None and s.notna().any():
            row[key] = s.iloc[-1]
    ocf = col("经营现金净流量与净利润的比率(%)")
    if ocf is not None and ocf.notna().any():
        row["ocf_to_profit"] = ocf.iloc[-1]  # 列名虽带 %，实测值已是比率（如 0.72 = 72%）

    # 近 3 年复合增速：用最近 3 个年报的同比增速几何平均近似（04 规范 §3 注）
    def cagr3(name: str) -> Optional[float]:
        s = col(name)
        if s is None:
            return None
        g = s.dropna().tail(3)
        if len(g) < 1 or (g <= -100).any():
            return None
        return ((1 + g / 100).prod() ** (1 / len(g)) - 1) * 100

    row["revenue_cagr3"] = cagr3("主营业务收入增长率(%)")
    row["profit_cagr3"] = cagr3("净利润增长率(%)")

    db.upsert_finance(row)
    return row


# ---------- 估值历史（东财 datacenter，分位计算用） ----------

def fetch_pe_pb_history(code: str, force: bool = False) -> pd.DataFrame:
    """单股每日 PE(TTM)/市净率序列（stock_value_em，上市以来）。

    增量更新：已缓存到最近交易日则跳过。写入 stock_daily.pe/pb。
    """
    last_td = latest_trade_date()
    if not force and last_td and db.get_daily_last_date(code, "pe") and \
            str(db.get_daily_last_date(code, "pe")) >= last_td:
        return db.get_daily(code)

    _throttle()
    try:
        raw = _retry(ak.stock_value_em, symbol=code, times=5)
    except Exception:  # noqa: BLE001
        return db.get_daily(code)
    if raw is None or raw.empty:
        return db.get_daily(code)

    df = pd.DataFrame({
        "trade_date": raw["数据日期"].astype(str).str[:10],
        "pe": _num(raw["PE(TTM)"]),
        "pb": _num(raw["市净率"]),
    })
    df = df[df["trade_date"] >= "2019-01-01"]  # 只留近 5 年+，控制体积
    df = df[~((df["pe"] <= 0) & (df["pb"] <= 0))]  # 剔除纯占位行（当日估值未公布）
    db.upsert_daily_value(code, df)
    # 回填快照的权威 PE/PB/总市值（最新一行）
    last_row = raw.iloc[-1]
    for field, val in (("pe_ttm", last_row.get("PE(TTM)")),
                       ("pb", last_row.get("市净率")),
                       ("total_mv", last_row.get("总市值"))):
        if pd.notna(val):
            db.set_snapshot_field(code, field, float(val))
    return db.get_daily(code)


# ---------- 日线行情（均线/回撤/20日成交额用） ----------

def fetch_daily(code: str, force: bool = False) -> pd.DataFrame:
    """单股前复权日线（新浪 stock_zh_a_daily）。写入 stock_daily.close/turnover。

    新浪日线列名 date/close/amount（amount 为成交额元、turnover 为换手率），
    symbol 需带 sh/sz 前缀；剔除 volume=0 的停牌日。
    """
    last_td = latest_trade_date()
    if not force and last_td and db.get_daily_last_date(code, "close") and \
            str(db.get_daily_last_date(code, "close")) >= last_td:
        return db.get_daily(code)

    prefix = "sh" if code.startswith("6") else "sz"
    _throttle()
    try:
        raw = _retry(ak.stock_zh_a_daily, symbol=f"{prefix}{code}", start_date="20190101",
                     end_date=_today().replace("-", ""), adjust="qfq", times=5)
    except Exception:  # noqa: BLE001
        return db.get_daily(code)
    if raw is None or raw.empty:
        return db.get_daily(code)

    raw = raw[raw["volume"] > 0].copy()  # 剔除停牌日
    df = pd.DataFrame({
        "trade_date": raw["date"].astype(str).str[:10],
        "close": _num(raw["close"]),
        "turnover": _num(raw["amount"]),
    })
    db.upsert_daily_hist(code, df)
    return db.get_daily(code)


# ---------- 股息率（新浪分红明细，近 12 个月派息 ÷ 现价） ----------

def fetch_dividend_yield(code: str, force: bool = False) -> Optional[float]:
    """股息率（%）。缓存 30 天（分红按年更新，股价漂移带来的误差对档位判断影响很小）。

    写入 stock_snapshot.dividend_yield 与 div_updated_at。
    """
    snap = db._query_df(
        "SELECT price, dividend_yield, div_updated_at FROM stock_snapshot WHERE code = ?", (code,))
    if not force and not snap.empty and snap["div_updated_at"].iloc[0] and pd.notna(snap["dividend_yield"].iloc[0]):
        try:
            age = (datetime.now() - datetime.fromisoformat(snap["div_updated_at"].iloc[0])).days
        except ValueError:
            age = 999
        if age < TTL_DIVIDEND_DAYS:
            return snap["dividend_yield"].iloc[0]

    _throttle()
    try:
        raw = _retry(ak.stock_history_dividend_detail, symbol=code, indicator="分红")
    except Exception:  # noqa: BLE001
        return None
    if raw is None or raw.empty:
        return None

    raw["公告日期"] = pd.to_datetime(raw["公告日期"], errors="coerce")
    recent = raw[(raw["公告日期"] >= pd.Timestamp(date.today() - timedelta(days=365)))
                 & (raw["进度"] == "实施")]           # 只算已实施的，避免预案重复计入
    pay = _num(recent["派息"]).dropna()
    price = snap["price"].iloc[0] if not snap.empty else None
    if pay.empty or price is None or pd.isna(price) or price <= 0:
        return None
    dv = float(pay.sum() / 10 / price * 100)          # 派息单位：每 10 股（元）
    db.set_snapshot_field(code, "dividend_yield", dv)
    db.set_snapshot_field(code, "div_updated_at", datetime.now().isoformat(timespec="seconds"))
    return dv


# ---------- 商誉占比（新浪资产负债表） ----------

def fetch_goodwill_ratio(code: str, force: bool = False) -> Optional[float]:
    """商誉/所有者权益（%）。缓存 90 天，写入 stock_finance.goodwill_ratio。"""
    if not force:
        cached = db.get_finance(code)
        if cached and cached["goodwill_updated_at"] and cached["goodwill_ratio"] is not None:
            try:
                age = (datetime.now() - datetime.fromisoformat(cached["goodwill_updated_at"])).days
            except ValueError:
                age = 999
            if age < TTL_GOODWILL_DAYS:
                return cached["goodwill_ratio"]

    prefix = "sh" if code.startswith("6") else "sz"
    _throttle()
    try:
        raw = _retry(ak.stock_financial_report_sina, stock=f"{prefix}{code}", symbol="资产负债表")
    except Exception:  # noqa: BLE001
        return None
    if raw is None or raw.empty:
        return None

    equity_col = next((c for c in raw.columns if c in ("归属于母公司股东权益合计",
                                                      "所有者权益(或股东权益)合计")), None)
    goodwill_col = next((c for c in raw.columns if c == "商誉"), None)
    if equity_col is None or goodwill_col is None:
        return None

    equity = _num(raw[equity_col]).dropna()
    goodwill = _num(raw[goodwill_col]).dropna()
    if equity.empty or goodwill.empty or equity.iloc[-1] <= 0:
        return None
    ratio = float(goodwill.iloc[-1] / equity.iloc[-1] * 100)
    db.set_finance_field(code, "goodwill_ratio", ratio)
    db.set_finance_field(code, "goodwill_updated_at", datetime.now().isoformat(timespec="seconds"))
    return ratio


# ---------- 汇总便捷函数 ----------

def init_data() -> None:
    """初始化基础数据（列表、日历）。全市场快照/财务按需单独调用。"""
    db.init_db()
    fetch_trade_calendar()
    fetch_stock_list()
