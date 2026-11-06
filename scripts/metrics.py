"""純計算函式：不碰網路，方便測試。
輸入皆為依日期排序的 pandas Series（index 為 DatetimeIndex）。
"""
from __future__ import annotations

import math
from typing import Optional

import pandas as pd


def _r(x: Optional[float], n: int = 2) -> Optional[float]:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), n)


def pct(a: float, b: float) -> Optional[float]:
    """b → a 的變化率（%）。"""
    if b is None or a is None or b == 0 or pd.isna(a) or pd.isna(b):
        return None
    return (a / b - 1.0) * 100.0


def week_start_index(dates: pd.DatetimeIndex, i: int) -> Optional[int]:
    """回傳「上一週最後一個交易日」的位置（週內報酬的基準）。"""
    d = dates[i]
    monday = (d - pd.Timedelta(days=d.weekday())).normalize()
    prev = [j for j in range(i) if dates[j].normalize() < monday]
    return prev[-1] if prev else None


def session_metrics(close: pd.Series, volume: Optional[pd.Series], i: int) -> dict:
    """第 i 個交易日的指標。"""
    dates = close.index
    out = {"date": dates[i].strftime("%Y-%m-%d")}
    out["close"] = _r(close.iloc[i], 4)
    out["day_pct"] = _r(pct(close.iloc[i], close.iloc[i - 1])) if i >= 1 else None
    ws = week_start_index(dates, i)
    out["wtd_pct"] = _r(pct(close.iloc[i], close.iloc[ws])) if ws is not None else None
    out["m1_pct"] = _r(pct(close.iloc[i], close.iloc[i - 21])) if i >= 21 else None
    vr = None
    if volume is not None and i >= 20:
        base = volume.iloc[i - 20:i].mean()
        if base and not pd.isna(base) and base > 0 and not pd.isna(volume.iloc[i]):
            vr = volume.iloc[i] / base
    out["vol_ratio"] = _r(vr)
    # 資金分數 = 當日漲跌% × 量比（Sharon 的每日資金流讀法）
    out["flow"] = _r(out["day_pct"] * vr) if (out["day_pct"] is not None and vr is not None) else None
    return out


def thursday_index(dates: pd.DatetimeIndex, i: int) -> Optional[int]:
    """同一週內最後一個 ≤ 週四的交易日（週四休市時退回週三）。"""
    d = dates[i]
    monday = (d - pd.Timedelta(days=d.weekday())).normalize()
    cands = [j for j in range(i + 1)
             if dates[j].normalize() >= monday and dates[j].weekday() <= 3]
    return cands[-1] if cands else None


def confirm_verdict(thu_wtd: Optional[float], fri_wtd: Optional[float], tol: float = 0.15) -> Optional[str]:
    """週四檢查點 → 週五結算 的關係。"""
    if thu_wtd is None or fri_wtd is None:
        return None
    if abs(thu_wtd) < tol and abs(fri_wtd) < tol:
        return "持平"
    if thu_wtd * fri_wtd < 0 and abs(fri_wtd) >= tol:
        return "反轉"
    if abs(fri_wtd) >= abs(thu_wtd):
        return "確認"
    return "減弱"


def signal(rs_pp: Optional[float], flow: Optional[float], rules: dict) -> str:
    """☆ 自訂信號燈，由上往下依序判定。"""
    if rs_pp is None:
        return "保留"
    f = flow or 0.0
    if rs_pp >= rules["strong_rs_pp"] and f > 0:
        return "強勢"
    if rs_pp <= -rules["strong_rs_pp"] and f < 0:
        return "弱勢"
    if rs_pp >= rules["lean_rs_pp"]:
        return "偏強"
    if rs_pp <= -rules["lean_rs_pp"]:
        return "偏弱"
    return "中性"


def adr_premium(us_px: float, tw_px: float, usdtwd: float, ratio: float) -> Optional[float]:
    """ADR 溢價（%）= ADR 價 ÷（台股價 × 換股比 ÷ 匯率）− 1。"""
    if not all(v and not pd.isna(v) for v in (us_px, tw_px, usdtwd)):
        return None
    return _r(pct(us_px, tw_px * ratio / usdtwd))


def mean_or_none(vals):
    v = [x for x in vals if x is not None]
    return _r(sum(v) / len(v)) if v else None


def expected_session_date(now_et, holidays_set, close_buffer_min: int = 30):
    """依美東現在時間，推算「應該已經有收盤資料」的最近一個美股交易日。

    收盤（16:00 ET）後 close_buffer_min 分鐘才算當天；週末與 holidays_set 內的日期跳過。
    """
    from datetime import time as _time, timedelta as _td
    d = now_et.date()
    cutoff = (datetime_combine(d, _time(16, 0)) + _td(minutes=close_buffer_min)).time()
    if now_et.time() < cutoff:
        d -= _td(days=1)
    while d.weekday() >= 5 or d in holidays_set:
        d -= _td(days=1)
    return d


def datetime_combine(d, t):
    from datetime import datetime as _dt
    return _dt.combine(d, t)
