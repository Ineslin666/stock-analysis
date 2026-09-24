"""探测二：利润表取归母净利 + 股息发放率全行复查（一次性，用完即删）"""
import akshare as ak
import pandas as pd

CODE = "000333"
print(f"akshare {ak.__version__} | 探测二 {CODE}\n" + "=" * 60)

# ---------- A) 股息发放率 全行复查（不只年报）----------
print("\n[A] 股息发放率(%) 全行复查")
try:
    raw = ak.stock_financial_analysis_indicator(symbol=CODE, start_year="2022")
    if "股息发放率(%)" in raw.columns:
        s = pd.to_numeric(raw["股息发放率(%)"], errors="coerce")
        print(f"  非空行数: {s.notna().sum()} / {len(s)}")
        print(raw[raw["日期"].astype(str).str.contains("12-31")][["日期", "股息发放率(%)"]].to_string())
except Exception as e:
    print(f"  失败: {e}")

# ---------- B) 利润表：归母净利润绝对值 ----------
print("\n[B] stock_financial_report_sina 利润表")
try:
    raw = ak.stock_financial_report_sina(stock=f"sz{CODE}", symbol="利润表")
    print(f"  shape={raw.shape}")
    np_col = next((c for c in raw.columns if "归属于母公司" in str(c) and "净利润" in str(c)), None)
    print(f"  归母净利列名: {np_col}")
    if np_col:
        s = pd.to_numeric(raw[np_col], errors="coerce")
        # 取最近年报
        raw2 = raw.copy()
        if "报告日" in raw2.columns:
            raw2["报告日"] = raw2["报告日"].astype(str)
            annual = raw2[raw2["报告日"].str.endswith("12-31")]
            print(f"  最近 3 年报归母净利:")
            print(annual[["报告日", np_col]].tail(3).to_string())
except Exception as e:
    print(f"  失败: {type(e).__name__}: {e}")

print("\n" + "=" * 60 + "结束")
