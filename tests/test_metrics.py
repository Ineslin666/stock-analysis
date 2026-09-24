"""股东回报派生计算单测（data_fetcher 纯函数）：
分红金额 = Σ派息(每10股) / 10 × 总股本；分红率 = 分红额/净利×100；回购率 = 回购额/净利×100。
"""
import pytest

import data_fetcher as fetcher


# ---------- 分红金额 ----------

def test_dividend_amount_basic():
    # 派息合计每10股 43 元，总股本 70 亿股 → 43/10 * 70e8 = 3.01e10 元（约 301 亿）
    amount = fetcher.dividend_amount_from_per10(43.0, 70e8)
    assert amount == pytest.approx(3.01e10)


def test_dividend_amount_none_inputs():
    assert fetcher.dividend_amount_from_per10(None, 70e8) is None
    assert fetcher.dividend_amount_from_per10(43.0, None) is None
    assert fetcher.dividend_amount_from_per10(0.0, 70e8) == 0.0


# ---------- 总股本 ----------

def test_shares_outstanding_basic():
    # 总市值 7000 亿，股价 70 元 → 100 亿股
    assert fetcher.shares_outstanding(7000e8, 70.0) == pytest.approx(100e8)


def test_shares_outstanding_invalid():
    assert fetcher.shares_outstanding(None, 70.0) is None
    assert fetcher.shares_outstanding(7000e8, None) is None
    assert fetcher.shares_outstanding(7000e8, 0.0) is None


# ---------- 分红率 / 回购率 ----------

def test_payout_ratio_basic():
    # 分红 324 亿 / 净利 439 亿 = 73.8%
    assert fetcher.ratio_pct(324e8, 439e8) == pytest.approx(73.804, abs=0.01)


def test_buyback_ratio_basic():
    # 回购 116 亿 / 净利 439 亿 = 26.4%
    assert fetcher.ratio_pct(116e8, 439e8) == pytest.approx(26.424, abs=0.01)


def test_ratio_pct_zero_base():
    assert fetcher.ratio_pct(324e8, 0) is None
    assert fetcher.ratio_pct(324e8, None) is None
    assert fetcher.ratio_pct(None, 439e8) is None
    assert fetcher.ratio_pct(0.0, 439e8) == 0.0
