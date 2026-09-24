"""score_quality 打分单测（04 规范 §5 v1.3：质量 40 = ROE12 + 成长10 + 现金流8 + 股东回报10）。

股东回报 10 = 股息率(3) + 分红率(4) + 回购率(3)。
"""
import pytest
import screener


def _fin(roe=25, rev=25, pro=25, ocf=1.2, payout=75, buyback=25):
    return {"roe_latest": roe, "revenue_cagr3": rev, "profit_cagr3": pro,
            "ocf_to_profit": ocf, "payout_ratio": payout, "buyback_ratio": buyback}


# ---------- 总分与子项 ----------

def test_all_max_scores_40():
    score, parts = screener.score_quality(_fin(), 3.0, "家电")
    assert score == 40
    assert "ROE 12/12" in parts
    assert "成长 10/10" in parts
    assert "现金流 8/8" in parts
    assert "股东回报 10/10" in parts


def test_no_buyback_no_payout_shareholder_return_3():
    """分红率/回购率缺失 → 该子项 0 分不剔除；股息率仍计分。"""
    score, parts = screener.score_quality(_fin(payout=None, buyback=None), 3.0, "家电")
    # 12 + 10 + 8 + (3 + 0 + 0) = 33
    assert score == 33
    assert "股东回报 3/10" in parts


def test_zero_dividend_shareholder_return_0_from_yield():
    """股息率 0 → 股息子项 0。"""
    score, parts = screener.score_quality(_fin(payout=None, buyback=None), 0.0, "家电")
    assert score == 30  # 12 + 10 + 8 + 0


# ---------- ROE 档位（12 分制）----------

@pytest.mark.parametrize("roe,expected", [(12, 6), (14, 6), (15, 9), (20, 9), (21, 12), (25, 12)])
def test_roe_breakpoints(roe, expected):
    score, _ = screener.score_quality(_fin(roe=roe), 3.0, "家电")
    # 其他子项全满：成长 10 + 现金流 8 + 股东回报 10 = 28
    assert score == expected + 28


# ---------- 现金流档位（8 分制）----------

@pytest.mark.parametrize("ocf,expected", [(0.7, 5), (0.8, 5), (1.0, 8), (1.5, 8)])
def test_ocf_breakpoints(ocf, expected):
    score, _ = screener.score_quality(_fin(ocf=ocf), 3.0, "家电")
    # ROE 12 + 成长 10 + 股东回报 10 = 32
    assert score == expected + 32


# ---------- 股息率子项（满分 3）----------

@pytest.mark.parametrize("div,expected_sub", [(0, 0), (0.5, 1), (1, 2), (1.9, 2), (2, 2), (2.1, 3), (3, 3)])
def test_dividend_subscore(div, expected_sub):
    score, _ = screener.score_quality(_fin(payout=None, buyback=None), div, "家电")
    # ROE 12 + 成长 10 + 现金流 8 = 30；股东回报只剩股息子项
    assert score == 30 + expected_sub


# ---------- 分红率子项（满分 4）----------

@pytest.mark.parametrize("payout,expected_sub", [(20, 1), (29, 1), (30, 2), (49, 2), (50, 3), (70, 3), (71, 4)])
def test_payout_subscore(payout, expected_sub):
    score, _ = screener.score_quality(_fin(payout=payout, buyback=None), 3.0, "家电")
    # ROE 12 + 成长 10 + 现金流 8 + 股息 3 = 33；股东回报只剩分红率子项
    assert score == 33 + expected_sub


# ---------- 回购率子项（满分 3）----------

@pytest.mark.parametrize("buyback,expected_sub", [(0, 0), (5, 1), (10, 1), (11, 2), (20, 2), (21, 3), (25, 3)])
def test_buyback_subscore(buyback, expected_sub):
    score, _ = screener.score_quality(_fin(payout=None, buyback=buyback), 3.0, "家电")
    # ROE 12 + 成长 10 + 现金流 8 + 股息 3 = 33；股东回报只剩回购率子项
    assert score == 33 + expected_sub
