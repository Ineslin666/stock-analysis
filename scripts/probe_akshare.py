#!/usr/bin/env python3
"""akshare 接口实测脚本（阶段 1.1）

逐个实测选股系统所需的 akshare 接口，输出：函数名、行数、列名、前 2 行样例。
每个接口独立容错（getattr 在 try 内），失败自动重试。实测结果归档到 docs_notes/。

用法：.venv/bin/python scripts/probe_akshare.py
"""
import time
import akshare as ak
import pandas as pd

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)


def retry(fn, *args, times=3, **kwargs):
    for i in range(times):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if i == times - 1:
                raise
            time.sleep(3 * (i + 1))


def probe(label: str, fn_name: str, *args, **kwargs):
    print(f"\n{'='*60}\n[{label}]\n{'='*60}")
    try:
        fn = getattr(ak, fn_name)
    except AttributeError:
        print(f"  ❌ akshare 无此函数: {fn_name}")
        return
    try:
        df = retry(fn, *args, **kwargs)
        if df is None:
            print("  返回 None")
            return
        print(f"  行数: {len(df)}")
        print(f"  列名: {list(df.columns)}")
        print("  样例:")
        print(df.head(2).to_string())
    except AttributeError:
        print(f"  ❌ akshare 无此函数: {fn_name}")
    except Exception as e:
        print(f"  ❌ 失败: {type(e).__name__}: {e}")


if __name__ == "__main__":
    # 1. 全市场实时快照（东财）+ 分市场备选
    probe("1 全市场快照 stock_zh_a_spot_em", "stock_zh_a_spot_em")
    probe("1b 沪市快照 stock_sh_a_spot_em", "stock_sh_a_spot_em")
    probe("1c 深市快照 stock_sz_a_spot_em", "stock_sz_a_spot_em")

    # 2. 单股历史日线
    probe("2 历史日线 stock_zh_a_hist", "stock_zh_a_hist",
          symbol="600519", period="daily", start_date="20240101",
          end_date="20240801", adjust="qfq")

    # 3. 财务指标（新浪）— 主选
    probe("3 财务指标(新浪) stock_financial_analysis_indicator", "stock_financial_analysis_indicator",
          symbol="600519", start_year="2022")

    # 4. 财务摘要候选（东财改名后探测可用名）
    for fn in ["stock_financial_abstract_em", "stock_financial_abstract", "stock_financial_abstract_ths"]:
        probe(f"4 财务摘要候选 {fn}", fn, symbol="600519")

    # 5. 历史 PE/PB/股息率（乐咕）
    probe("5 PE/PB/股息率历史(乐咕) stock_a_indicator_lg", "stock_a_indicator_lg",
          symbol="600519")

    # 6. 全部 A 股代码+名称
    probe("6 代码名称 stock_info_a_code_name", "stock_info_a_code_name")

    # 7. 沪市列表（含上市日期）— 主板与科创板
    probe("7 沪市主板列表 stock_info_sh_name_code", "stock_info_sh_name_code", symbol="主板A股")
    probe("7b 沪市科创板列表 stock_info_sh_name_code", "stock_info_sh_name_code", symbol="科创板")

    # 8. 深市列表（含上市日期/行业）
    probe("8 深市列表 stock_info_sz_name_code", "stock_info_sz_name_code", symbol="A股列表")

    # 9. 行业板块列表（东财）
    probe("9 行业板块列表 stock_board_industry_name_em", "stock_board_industry_name_em")

    # 10. 行业成分股（东财）
    probe("10 行业成分股 stock_board_industry_cons_em", "stock_board_industry_cons_em",
          symbol="酿酒行业")

    # 11. 交易日历（新浪）
    probe("11 交易日历 tool_trade_date_hist_sina", "tool_trade_date_hist_sina")
