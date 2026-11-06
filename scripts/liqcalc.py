"""流動性模組的純計算函式（不碰網路，方便測試）。

單位一律：十億美元（B）、百分比（%）、基點（bp）。
"""
from __future__ import annotations

import math
from typing import Iterable, Optional

import pandas as pd

LEVELS = ["正常", "注意", "警告"]          # ● ▲ ■
ICON = {"正常": "●", "注意": "▲", "警告": "■", "方向": "○", "解讀": "○"}


def r(x, n: int = 2):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return round(x, n)


def last_on_or_before(s: pd.Series, d) -> Optional[float]:
    if s is None or not len(s):
        return None
    s = s.dropna()
    sub = s[s.index <= pd.Timestamp(d)]
    return float(sub.iloc[-1]) if len(sub) else None


def pct_rank(hist: Iterable[float], v: float) -> Optional[float]:
    """一年位置＝歷史值中「不高於目前值」的比例（0–100）。"""
    h = [float(x) for x in hist if x is not None and not pd.isna(x)]
    if not h or v is None or pd.isna(v):
        return None
    return round(100.0 * sum(1 for x in h if x <= v) / len(h), 0)


def quantile(hist: Iterable[float], q: float) -> Optional[float]:
    h = pd.Series([x for x in hist if x is not None and not pd.isna(x)], dtype=float)
    return float(h.quantile(q)) if len(h) else None


def worse(*levels: Optional[str]) -> Optional[str]:
    lv = [x for x in levels if x in LEVELS]
    return max(lv, key=LEVELS.index) if lv else None


def pct_signal(p: Optional[float], bad: str) -> Optional[str]:
    """★ 一年分布判定：較差方向第 80 百分位▲、第 95 百分位■（低為差則用 20／5）。邊界歸較差側。"""
    if p is None or bad not in ("high", "low"):
        return None
    if bad == "high":
        return "警告" if p >= 95 else "注意" if p >= 80 else "正常"
    return "警告" if p <= 5 else "注意" if p <= 20 else "正常"


def fixed_signal(v: Optional[float], warn_at=None, alert_at=None, bad: str = "high") -> Optional[str]:
    """☆ 固定門檻判定。bad=high：v≥warn_at 注意、v≥alert_at 警告；bad=low 反向。"""
    if v is None:
        return None
    if bad == "high":
        if alert_at is not None and v >= alert_at:
            return "警告"
        if warn_at is not None and v >= warn_at:
            return "注意"
        return "正常"
    if alert_at is not None and v <= alert_at:
        return "警告"
    if warn_at is not None and v <= warn_at:
        return "注意"
    return "正常"


def waterfall(items, d_reserves=None):
    """準備金變化分解（週平均變化）。

    items：[(名稱, 對準備金的影響)]，正值＝使準備金增加（吸收項請先取負號）。
    若給 d_reserves，差額另列「其他（四捨五入差）」，並附合計列，保證加總＝準備金變化。
    """
    out = [{"name": n, "impact": r(v, 1)} for n, v in items]
    known = sum(v for _, v in items if v is not None)
    if d_reserves is not None:
        gap = d_reserves - known
        if abs(gap) >= 0.05:
            out.append({"name": "其他（差額）", "impact": r(gap, 1)})
        out.append({"name": "合計 準備金", "impact": r(d_reserves, 1), "total": True})
    return out


def tga_scenarios(tga_now, reserves_now, reserves_hist, qra: dict | None):
    """TGA 情境 A／B／C：假設其他因素不變，TGA 增減一對一反映到準備金。"""
    if tga_now is None or reserves_now is None:
        return []
    t = (qra or {}).get("tga", {})
    end = t.get("end_dec_assumption_b") or 850
    peak = (t.get("peak_b") or 1025) + (t.get("peak_band_b") or 50)
    sc = [("A 過峰後下降", f"降至財政部年底假設 {end:,.0f}", end),
          ("B 繼續累積", f"升至財政部高峰估計上緣 {peak:,.0f}", peak),
          ("C 橫盤", "維持目前水準", tga_now)]
    out = []
    for name, path, target in sc:
        dt = target - tga_now
        res = reserves_now - dt
        p = pct_rank(reserves_hist, res)
        out.append({"name": name, "path": path, "tga_change": r(dt, 1), "reserves_end": r(res, 1),
                    "pct": p, "signal": pct_signal(p, "low")})
    return out


def direction_check(wed_change, avg_change):
    if wed_change is None or avg_change is None:
        return None
    same = (wed_change >= 0) == (avg_change >= 0)
    return "方向一致" if same else "方向不同，趨勢以週平均判讀"


def bid_to_cover_band(btc):
    """☆ 自訂顏色：>3 綠、2.5–3 黃、<2.5 橘。"""
    if btc is None:
        return None
    return "強" if btc > 3 else "普通" if btc >= 2.5 else "偏弱"
