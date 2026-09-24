"""探测：分红率 / 分红金额 / 回购金额 三项数据源可用性（一次性，用完即删）"""
import akshare as ak
import pandas as pd

CODE = "000333"  # 美的集团
print(f"akshare {ak.__version__} | 探测股票 {CODE}\n" + "=" * 60)

# ---------- 1) 分红率（派息率）: stock_financial_analysis_indicator 的"股息发放率"列 ----------
print("\n[1] stock_financial_analysis_indicator — 股息发放率")
try:
    raw = ak.stock_financial_analysis_indicator(symbol=CODE, start_year="2023")
    print(f"  shape={raw.shape}")
    print(f"  全部列含'股息'的: {[c for c in raw.columns if '股息' in c or '派息' in c or '分红' in c]}")
    raw["日期"] = raw["日期"].astype(str)
    annual = raw[raw["日期"].str.endswith("12-31")]
    for col in ("股息发放率", "股息发放率(%)"):
        if col in annual.columns:
            s = pd.to_numeric(annual[col], errors="coerce").dropna()
            print(f"  列 '{col}' 年报值: {s.tail(3).tolist()}")
except Exception as e:
    print(f"  失败: {type(e).__name__}: {e}")

# ---------- 2) 分红明细: 派息(每10股) + 是否有总额列 ----------
print("\n[2] stock_history_dividend_detail — 分红明细列与金额口径")
try:
    raw = ak.stock_history_dividend_detail(symbol=CODE, indicator="分红")
    print(f"  shape={raw.shape}, 列: {list(raw.columns)}")
    print(raw.tail(3).to_string())
except Exception as e:
    print(f"  失败: {type(e).__name__}: {e}")

# ---------- 3) 回购: stock_repurchase_em（东财 datacenter，本机 push2 已断连，实测此接口）----------
print("\n[3] stock_repurchase_em — 回购（东财 datacenter）")
try:
    raw = ak.stock_repurchase_em()
    print(f"  shape={raw.shape}, 列: {list(raw.columns)}")
    # 找代码列
    code_col = next((c for c in raw.columns if "代码" in str(c)), None)
    if code_col:
        sub = raw[raw[code_col].astype(str).str.zfill(6) == CODE]
        print(f"  {CODE} 回购记录数: {len(sub)}")
        if not sub.empty:
            print(sub.tail(3).to_string())
except Exception as e:
    print(f"  失败: {type(e).__name__}: {e}")

# ---------- 4) 备选回购接口: stock_repurchase_data_cninfo（巨潮，东财失败时的 fallback）----------
print("\n[4] 备选: stock_repurchase_data_cninfo — 巨潮回购")
try:
    raw = ak.stock_repurchase_data_cninfo(symbol=CODE)
    print(f"  shape={raw.shape}, 列: {list(raw.columns)}")
    if not raw.empty:
        print(raw.tail(2).to_string())
except Exception as e:
    print(f"  失败: {type(e).__name__}: {e}")

print("\n" + "=" * 60 + "探测结束")
