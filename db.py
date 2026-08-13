"""SQLite 数据访问层（表结构见 文档/06-数据结构与数据字典.md）

- 数据库文件：data/stock.db（git 忽略，可删除重建）
- 页面层和业务层只通过本模块读写数据库
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "stock.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_snapshot (
    code          TEXT PRIMARY KEY,   -- 股票代码（纯数字字符串）
    name          TEXT,
    industry      TEXT,               -- 新浪行业（49 类）
    list_date     TEXT,               -- 上市日期 YYYY-MM-DD
    price         REAL,               -- 最新价
    pe_ttm        REAL,               -- 市盈率（新浪快照口径，仅初筛用；精确值以 stock_value_em 为准）
    pb            REAL,               -- 市净率
    total_mv      REAL,               -- 总市值（元）
    turnover_today REAL,              -- 当日成交额（元）
    turnover_avg20 REAL,              -- 近 20 日日均成交额（元，打分阶段回填）
    dividend_yield REAL,              -- 股息率（%）= 近12月派息合计/现价*100
    div_updated_at TEXT,              -- 股息率数据更新时间（缓存 TTL 依据）
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS stock_finance (
    code          TEXT PRIMARY KEY,
    roe_latest    REAL,               -- 最新年报加权 ROE（%）
    roe_3y_json   TEXT,               -- 近 3 年各年报 ROE（%），JSON 数组（旧→新）
    revenue_cagr3 REAL,               -- 近 3 年营收复合增速（%，同比增速几何平均近似）
    profit_cagr3  REAL,               -- 近 3 年净利润复合增速（%，同上）
    debt_ratio    REAL,               -- 资产负债率（%）
    ocf_to_profit REAL,               -- 经营现金流净额/净利润
    gross_margin  REAL,               -- 销售毛利率（%）
    net_margin    REAL,               -- 销售净利率（%）
    goodwill_ratio REAL,              -- 商誉/净资产（%）
    goodwill_updated_at TEXT,         -- 商誉数据更新时间（缓存 TTL 依据）
    report_date   TEXT,               -- 数据所属年报日期 YYYY-MM-DD
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS stock_daily (
    code      TEXT NOT NULL,
    trade_date TEXT NOT NULL,         -- YYYY-MM-DD
    close     REAL,
    pe        REAL,                   -- PE(TTM)，来自 stock_value_em
    pb        REAL,                   -- 来自 stock_value_em
    turnover  REAL,                   -- 成交额（元），来自新浪 stock_zh_a_daily
    PRIMARY KEY (code, trade_date)
);

CREATE TABLE IF NOT EXISTS recommendations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    rec_date      TEXT NOT NULL,      -- 推荐日期（交易日）
    code          TEXT NOT NULL,
    name          TEXT,
    industry      TEXT,
    rank          INTEGER,            -- 当日名次 1/2/3
    score         REAL,               -- 综合得分（满分 100）
    reasons       TEXT,               -- 筛选理由（多行文本）
    verdict       TEXT,               -- buy / buy_batch / hold
    verdict_reason TEXT,              -- 结论全文（标签+理由+价位+免责声明，04 规范 §9）
    ref_price_low REAL,               -- 参考价位下限
    ref_price_high REAL,              -- 参考价位上限
    close_price   REAL,               -- 推荐日收盘价
    pe_ttm        REAL,
    pe_percentile REAL,               -- 推荐日 PE 近 5 年分位（%）
    roe           REAL,
    dividend_yield REAL,
    created_at    TEXT,
    UNIQUE (rec_date, code)
);
CREATE INDEX IF NOT EXISTS idx_rec_date ON recommendations (rec_date);
CREATE INDEX IF NOT EXISTS idx_rec_code ON recommendations (code);

CREATE TABLE IF NOT EXISTS screening_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date         TEXT,
    run_time         TEXT,
    pool_size        INTEGER,
    passed_quality   INTEGER,
    passed_valuation INTEGER,
    candidates_json  TEXT,
    status           TEXT,            -- ok / error / partial
    error_msg        TEXT
);

CREATE TABLE IF NOT EXISTS trade_calendar (
    cal_date TEXT PRIMARY KEY,
    is_open  INTEGER                  -- 1=交易日 0=非交易日
);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """建表（幂等，可重复调用）+ 老库列迁移。"""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        # 迁移：老库 recommendations 缺 verdict_reason 列则补上
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(recommendations)")}
        if "verdict_reason" not in cols:
            conn.execute("ALTER TABLE recommendations ADD COLUMN verdict_reason TEXT")


def _exec(sql: str, params: Iterable[Any] = ()) -> None:
    with _connect() as conn:
        conn.execute(sql, list(params))


def _exec_many(sql: str, rows: Iterable[Iterable[Any]]) -> None:
    with _connect() as conn:
        conn.executemany(sql, [list(r) for r in rows])


def _query_df(sql: str, params: Iterable[Any] = ()) -> pd.DataFrame:
    with _connect() as conn:
        return pd.read_sql_query(sql, conn, params=list(params))


# ---------- stock_snapshot ----------

_SNAPSHOT_COLS = ("code", "name", "industry", "list_date", "price", "pe_ttm", "pb",
                  "total_mv", "turnover_today", "turnover_avg20", "dividend_yield",
                  "div_updated_at", "updated_at")


def upsert_snapshot(rows: Iterable[dict]) -> None:
    """插入或按列合并更新快照行。dict 键为 _SNAPSHOT_COLS 的子集。

    列级合并（COALESCE）：传入值为 NULL 时保留原值，避免不同数据源
    （列表/快照/行业）相互覆盖对方的字段；updated_at 以传入为准。
    """
    data = [tuple(r.get(c) for c in _SNAPSHOT_COLS) for r in rows]
    sets = ", ".join(
        f"{c} = COALESCE(excluded.{c}, stock_snapshot.{c})"
        for c in _SNAPSHOT_COLS if c not in ("code", "updated_at")
    )
    _exec_many(
        f"INSERT INTO stock_snapshot ({', '.join(_SNAPSHOT_COLS)}) "
        f"VALUES ({', '.join('?' * len(_SNAPSHOT_COLS))}) "
        f"ON CONFLICT(code) DO UPDATE SET {sets}, updated_at = excluded.updated_at",
        data,
    )


def get_snapshot() -> pd.DataFrame:
    return _query_df("SELECT * FROM stock_snapshot")


def get_snapshot_row(code: str) -> Optional[sqlite3.Row]:
    """单只股票的快照行（页面用）。"""
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM stock_snapshot WHERE code = ?", (code,)).fetchone()


def get_snapshot_codes() -> set[str]:
    df = _query_df("SELECT code FROM stock_snapshot")
    return set(df["code"]) if not df.empty else set()


def get_snapshot_last_update() -> Optional[str]:
    df = _query_df("SELECT MAX(updated_at) AS t FROM stock_snapshot")
    return None if df.empty else df["t"].iloc[0]


# ---------- stock_finance ----------

def upsert_finance(row: dict) -> None:
    """写入财务指标。商誉字段（由 fetch_goodwill_ratio 单独维护）缺省时保留原值。"""
    cols = ("code", "roe_latest", "roe_3y_json", "revenue_cagr3", "profit_cagr3",
            "debt_ratio", "ocf_to_profit", "gross_margin", "net_margin", "report_date",
            "updated_at")
    values = []
    for c in cols:
        v = row.get(c)
        values.append(json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v)
    _exec(
        f"INSERT INTO stock_finance ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
        "ON CONFLICT(code) DO UPDATE SET "
        + ", ".join(f"{c} = excluded.{c}" for c in cols if c != "code"),
        values,
    )


def get_finance(code: str) -> Optional[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute("SELECT * FROM stock_finance WHERE code = ?", (code,)).fetchone()


def get_finance_all() -> pd.DataFrame:
    return _query_df("SELECT * FROM stock_finance")


# ---------- stock_daily ----------

def upsert_daily_hist(code: str, df: pd.DataFrame) -> None:
    """写入日线行情（stock_zh_a_hist 来源）。df 需含 trade_date, close, turnover。

    按列合并（ON CONFLICT DO UPDATE），不会覆盖 stock_value_em 写入的 pe/pb。
    """
    if df.empty:
        return
    rows = [(code, r.get("trade_date"), r.get("close"), r.get("turnover"))
            for r in df.to_dict("records")]
    _exec_many(
        "INSERT INTO stock_daily (code, trade_date, close, turnover) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(code, trade_date) DO UPDATE SET "
        "close = excluded.close, turnover = excluded.turnover",
        rows,
    )


def upsert_daily_value(code: str, df: pd.DataFrame) -> None:
    """写入估值序列（stock_value_em 来源）。df 需含 trade_date, pe, pb。

    按列合并，不会覆盖 stock_zh_a_hist 写入的 close/turnover。
    """
    if df.empty:
        return
    rows = [(code, r.get("trade_date"), r.get("pe"), r.get("pb"))
            for r in df.to_dict("records")]
    _exec_many(
        "INSERT INTO stock_daily (code, trade_date, pe, pb) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(code, trade_date) DO UPDATE SET "
        "pe = excluded.pe, pb = excluded.pb",
        rows,
    )


def get_daily(code: str) -> pd.DataFrame:
    return _query_df(
        "SELECT trade_date, close, pe, pb, turnover FROM stock_daily "
        "WHERE code = ? ORDER BY trade_date",
        (code,),
    )


def get_daily_last_date(code: str, col: Optional[str] = None) -> Optional[str]:
    """该股日线最新日期。col 给定时只看该列非空的日期——不同数据源（新浪
    日线写 close/turnover，东财写 pe/pb）的新鲜度要分开判断。"""
    if col is None:
        df = _query_df("SELECT MAX(trade_date) AS d FROM stock_daily WHERE code = ?", (code,))
    else:
        assert col in ("close", "turnover", "pe", "pb"), f"非法列: {col}"
        df = _query_df(
            f"SELECT MAX(trade_date) AS d FROM stock_daily WHERE code = ? AND {col} IS NOT NULL",
            (code,))
    return None if df.empty else df["d"].iloc[0]


# ---------- 字段回填 ----------

def set_snapshot_field(code: str, field: str, value: Any) -> None:
    """回填 stock_snapshot 的单个字段（股息率、20日成交额等）。字段名白名单防注入。"""
    if field not in _SNAPSHOT_COLS:
        raise ValueError(f"非法字段: {field}")
    _exec(f"UPDATE stock_snapshot SET {field} = ? WHERE code = ?", (value, code))


def set_finance_field(code: str, field: str, value: Any) -> None:
    if field not in ("goodwill_ratio", "goodwill_updated_at"):
        raise ValueError(f"非法字段: {field}")
    _exec(f"UPDATE stock_finance SET {field} = ? WHERE code = ?", (value, code))


# ---------- trade_calendar ----------

def upsert_trade_calendar(df: pd.DataFrame) -> None:
    """df 需含列 trade_date（YYYY-MM-DD 或 datetime）。"""
    rows = [(str(d)[:10], 1) for d in df["trade_date"]]
    _exec_many("INSERT OR REPLACE INTO trade_calendar (cal_date, is_open) VALUES (?, ?)", rows)


def is_trade_day(day: str) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT is_open FROM trade_calendar WHERE cal_date = ?", (day,)).fetchone()
    return bool(row and row["is_open"])


def get_trade_dates(start: Optional[str] = None, end: Optional[str] = None) -> list[str]:
    sql = "SELECT cal_date FROM trade_calendar WHERE is_open = 1"
    params: list[Any] = []
    if start:
        sql += " AND cal_date >= ?"
        params.append(start)
    if end:
        sql += " AND cal_date <= ?"
        params.append(end)
    sql += " ORDER BY cal_date"
    df = _query_df(sql, params)
    return df["cal_date"].tolist() if not df.empty else []


# ---------- screening_log ----------

def insert_screening_log(entry: dict) -> None:
    cols = ("run_date", "run_time", "pool_size", "passed_quality", "passed_valuation",
            "candidates_json", "status", "error_msg")
    _exec(f"INSERT INTO screening_log ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
          [entry.get(c) for c in cols])


def get_last_screening_log() -> Optional[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute("SELECT * FROM screening_log ORDER BY id DESC LIMIT 1").fetchone()


# ---------- recommendations ----------

def clear_recommendations(date_str: str) -> None:
    _exec("DELETE FROM recommendations WHERE rec_date = ?", (date_str,))


def insert_recommendation(row: dict) -> None:
    cols = ("rec_date", "code", "name", "industry", "rank", "score", "reasons",
            "verdict", "ref_price_low", "ref_price_high", "close_price", "pe_ttm",
            "pe_percentile", "roe", "dividend_yield", "created_at")
    _exec(f"INSERT OR REPLACE INTO recommendations ({', '.join(cols)}) "
          f"VALUES ({', '.join('?' * len(cols))})", [row.get(c) for c in cols])


def get_recommendations(date_str: Optional[str] = None) -> pd.DataFrame:
    if date_str:
        return _query_df("SELECT * FROM recommendations WHERE rec_date = ? ORDER BY rank", (date_str,))
    return _query_df("SELECT * FROM recommendations ORDER BY rec_date DESC, rank")


def set_verdict(date_str: str, code: str, verdict: str, verdict_reason: str,
                ref_price_low: float, ref_price_high: float) -> None:
    """回填推荐记录的买入结论（analyzer.py 用）。"""
    _exec("UPDATE recommendations SET verdict = ?, verdict_reason = ?, "
          "ref_price_low = ?, ref_price_high = ? WHERE rec_date = ? AND code = ?",
          (verdict, verdict_reason, ref_price_low, ref_price_high, date_str, code))


def get_latest_recommendation(code: str) -> Optional[sqlite3.Row]:
    """该股最近一次推荐记录（详情页用）。"""
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM recommendations WHERE code = ? ORDER BY rec_date DESC LIMIT 1",
            (code,)).fetchone()


def get_recent_recommended_codes(days: int = 60) -> set[str]:
    df = _query_df(
        "SELECT DISTINCT code FROM recommendations WHERE rec_date >= date('now', ?)",
        (f"-{days} days",),
    )
    return set(df["code"]) if not df.empty else set()
