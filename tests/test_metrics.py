import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from metrics import (adr_premium, confirm_verdict, pct, session_metrics, signal,  # noqa: E402
                     thursday_index, week_start_index)

RULES = {"strong_rs_pp": 1.0, "lean_rs_pp": 0.3}


def series(vals, start="2026-10-01"):
    idx = pd.bdate_range(start, periods=len(vals))
    return pd.Series(vals, index=idx, dtype=float)


def test_pct():
    assert pct(110, 100) == pytest.approx(10)
    assert pct(1, 0) is None


def test_week_start_is_prior_friday():
    s = series(range(1, 31))          # 2026-10-01 (Thu) 起
    i = list(s.index).index(pd.Timestamp("2026-11-05"))  # 週四
    ws = week_start_index(s.index, i)
    assert s.index[ws] == pd.Timestamp("2026-10-30")      # 上週五


def test_session_metrics_wtd_and_volume():
    close = series([100.0] * 25 + [101, 102, 103, 104, 105])
    vol = series([1000.0] * 29 + [3000])
    i = len(close) - 1
    m = session_metrics(close, vol, i)
    assert m["day_pct"] == pytest.approx(0.96, abs=0.01)
    assert m["vol_ratio"] == pytest.approx(3.0)
    assert m["flow"] == pytest.approx(0.96 * 3.0, abs=0.05)


def test_thursday_index_on_friday():
    s = series(range(30))
    i = list(s.index).index(pd.Timestamp("2026-11-06"))  # 週五
    assert s.index[thursday_index(s.index, i)] == pd.Timestamp("2026-11-05")


@pytest.mark.parametrize("thu,fri,exp", [
    (1.0, 1.5, "確認"), (1.0, 0.5, "減弱"), (1.0, -0.8, "反轉"),
    (-1.0, -2.0, "確認"), (0.05, -0.1, "持平"), (None, 1, None)])
def test_verdict(thu, fri, exp):
    assert confirm_verdict(thu, fri) == exp


@pytest.mark.parametrize("rs,flow,exp", [
    (1.2, 0.5, "強勢"), (1.2, -0.5, "偏強"), (-1.2, -0.1, "弱勢"),
    (-1.2, 0.3, "偏弱"), (0.1, 5, "中性"), (None, 1, "保留")])
def test_signal(rs, flow, exp):
    assert signal(rs, flow, RULES) == exp


def test_adr_premium():
    # 台股 1000 元 ×5 ÷ 32 = 156.25 美元；ADR 171.875 → 溢價 10%
    assert adr_premium(171.875, 1000, 32, 5) == pytest.approx(10.0)


def test_expected_session_date():
    from datetime import date, datetime
    from metrics import expected_session_date
    hol = {date(2026, 11, 26)}
    # 週四 21:20 ET（收盤後）→ 當天
    assert expected_session_date(datetime(2026, 11, 5, 21, 20), hol) == date(2026, 11, 5)
    # 週四 15:00 ET（盤中）→ 前一交易日
    assert expected_session_date(datetime(2026, 11, 5, 15, 0), hol) == date(2026, 11, 4)
    # 週六 → 週五
    assert expected_session_date(datetime(2026, 11, 7, 10, 0), hol) == date(2026, 11, 6)
    # 感恩節週四晚上 → 週三
    assert expected_session_date(datetime(2026, 11, 26, 20, 0), hol) == date(2026, 11, 25)
    # 週一早上 → 上週五
    assert expected_session_date(datetime(2026, 11, 9, 8, 0), hol) == date(2026, 11, 6)
