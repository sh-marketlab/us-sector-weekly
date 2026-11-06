"""美股板塊週四/週五分析 — 數據管線。

產出：
  docs/data/latest.json                 最新一期
  docs/data/history/<date>-<session>.json
  docs/data/index.json                  所有期別清單

用法：python scripts/fetch_data.py [--session thu|fri]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import (adr_premium, confirm_verdict, mean_or_none, pct, session_metrics,  # noqa: E402
                     expected_session_date, signal, thursday_index, _r)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "data"
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
ET = ZoneInfo("America/New_York")
TPE = ZoneInfo("Asia/Taipei")


# ---------------------------------------------------------------- 下載
def download(tickers: list[str]) -> dict[str, pd.DataFrame]:
    import yfinance as yf
    out: dict[str, pd.DataFrame] = {}
    raw = yf.download(sorted(set(tickers)), period="9mo", interval="1d", auto_adjust=True,
                      group_by="ticker", progress=False, threads=True)
    for t in set(tickers):
        try:
            df = raw[t][["Close", "Volume"]].dropna(subset=["Close"])
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
            if len(df):
                out[t] = df
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {t}: {e}")
    return out


def metrics_at(px: dict, t: str, date: pd.Timestamp) -> dict | None:
    """t 在 date（或之前最近一日）的指標。"""
    df = px.get(t)
    if df is None:
        return None
    idx = df.index[df.index <= date]
    if len(idx) < 2:
        return None
    i = df.index.get_loc(idx[-1])
    m = session_metrics(df["Close"], df["Volume"] if df["Volume"].sum() > 0 else None, i)
    m["stale"] = idx[-1] != date
    return m


# ---------------------------------------------------------------- 美股
def build_us(px: dict, session_date: pd.Timestamp, thu_date: pd.Timestamp | None) -> dict:
    rules = CFG["rules"]
    bench = CFG["benchmark"]
    b_now = metrics_at(px, bench, session_date)
    b_thu = metrics_at(px, bench, thu_date) if thu_date is not None else None

    def row(t: str, name: str) -> dict:
        now = metrics_at(px, t, session_date) or {}
        thu = metrics_at(px, t, thu_date) if thu_date is not None else None
        rs = (now.get("wtd_pct") - b_now["wtd_pct"]) if now.get("wtd_pct") is not None else None
        rs_thu = (thu["wtd_pct"] - b_thu["wtd_pct"]) if (thu and thu.get("wtd_pct") is not None and b_thu) else None
        r = {"ticker": t, "name": name, **now,
             "rs_pp": _r(rs), "signal": signal(rs, now.get("flow"), rules)}
        if thu is not None:
            r["thu"] = {k: thu.get(k) for k in ("date", "day_pct", "wtd_pct", "vol_ratio", "flow")}
            r["thu"]["rs_pp"] = _r(rs_thu)
            r["verdict"] = confirm_verdict(thu.get("wtd_pct"), now.get("wtd_pct"))
        return r

    indices = [row(t, n) for t, n in CFG["indices"].items()]
    sectors = [row(t, n) for t, n in CFG["sectors"].items()]

    groups = []
    for key, g in CFG["groups"].items():
        members = [row(t, t) for t in g["tickers"] if t in px]
        avg = {k: mean_or_none([m.get(k) for m in members]) for k in ("day_pct", "wtd_pct", "m1_pct", "vol_ratio", "flow", "rs_pp")}
        grp = {"key": key, "name": g["name"], **avg,
               "signal": signal(avg["rs_pp"], avg["flow"], rules), "members": members}
        if thu_date is not None:
            thu_avg = mean_or_none([m.get("thu", {}).get("wtd_pct") for m in members])
            grp["thu_wtd_pct"] = thu_avg
            grp["verdict"] = confirm_verdict(thu_avg, avg["wtd_pct"])
        groups.append(grp)

    # 本週每日累積路徑（相對上週最後交易日）
    path = {}
    spy = px[bench]
    week_dates = [d for d in spy.index if d <= session_date and d >= session_date - pd.Timedelta(days=session_date.weekday())]
    for t in [bench, *CFG["sectors"].keys()]:
        df = px.get(t)
        if df is None:
            continue
        base_idx = df.index[df.index < week_dates[0]] if week_dates else []
        if not len(base_idx):
            continue
        base = df.loc[base_idx[-1], "Close"]
        path[t] = [_r(pct(df.loc[d, "Close"], base)) if d in df.index else None for d in week_dates]

    macro = []
    for t, n in CFG["macro"].items():
        m = metrics_at(px, t, session_date)
        if not m:
            continue
        df = px[t]
        i = df.index.get_loc(df.index[df.index <= session_date][-1])
        chg = df["Close"].iloc[i] - df["Close"].iloc[i - 1]
        item = {"ticker": t, "name": n, "value": m["close"], "day_pct": m["day_pct"], "wtd_pct": m["wtd_pct"]}
        if t == "^TNX":  # 殖利率看 bp
            item["day_bp"] = _r(chg * 100 if df["Close"].iloc[i] < 20 else chg * 10, 1)
        macro.append(item)

    return {"benchmark": b_now, "indices": indices, "sectors": sectors, "groups": groups,
            "week_dates": [d.strftime("%Y-%m-%d") for d in week_dates], "week_path": path, "macro": macro}


# ---------------------------------------------------------------- 台股
def twse_foreign(date: pd.Timestamp) -> dict | None:
    """證交所三大法人買賣金額（億元）。"""
    url = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
    try:
        r = requests.get(url, params={"type": "day", "dayDate": date.strftime("%Y%m%d"), "response": "json"},
                         timeout=20, headers={"User-Agent": "us-sector-weekly/1.0"})
        j = r.json()
        if j.get("stat") != "OK":
            return None
        out = {}
        for row in j.get("data", []):
            name, net = row[0], float(str(row[3]).replace(",", ""))
            out[name] = round(net / 1e8, 2)
        foreign = sum(v for k, v in out.items() if k.startswith("外資"))
        return {"date": date.strftime("%Y-%m-%d"), "foreign_net_e8": round(foreign, 2), "detail": out}
    except Exception as e:  # noqa: BLE001
        print(f"[warn] TWSE {date.date()}: {e}")
        return None


def build_tw(px: dict, us_date: pd.Timestamp, us_groups: list[dict]) -> dict:
    tw = CFG["taiwan"]
    taiex = px.get("^TWII")
    if taiex is None:
        return {"error": "台股資料抓取失敗"}
    tw_date = taiex.index[-1]
    relation = "reaction" if tw_date > us_date else "before"
    # 台股這一盤反應的是哪一個美股交易日（台股收盤早於同日美股開盤）
    us_idx = px[CFG["benchmark"]].index
    prior_us = us_idx[us_idx < tw_date]
    reacts_to = prior_us[-1].strftime("%Y-%m-%d") if len(prior_us) else None

    indices = []
    for t, n in tw["indices"].items():
        m = metrics_at(px, t, tw_date)
        if m:
            indices.append({"ticker": t, "name": n, **m})

    fx = metrics_at(px, tw["fx"], tw_date)

    # ADR 溢價序列（同一日曆日：台股收盤早於美股）
    a = tw["adr"]
    prem = []
    us_s, tw_s, fx_s = px.get(a["us"]), px.get(a["tw"]), px.get(tw["fx"])
    if us_s is not None and tw_s is not None and fx_s is not None:
        for d in us_s.index[-40:]:
            if d in tw_s.index:
                fxd = fx_s["Close"][fx_s.index <= d]
                if len(fxd):
                    p = adr_premium(us_s.loc[d, "Close"], tw_s.loc[d, "Close"], fxd.iloc[-1], a["ratio"])
                    if p is not None:
                        prem.append({"date": d.strftime("%Y-%m-%d"), "premium_pct": p})

    gmap = {g["key"]: g for g in us_groups}
    mapping = []
    for key, m in tw["mapping"].items():
        members = []
        for t in m["tickers"]:
            mm = metrics_at(px, t, tw_date)
            if mm:
                members.append({"ticker": t, **{k: mm[k] for k in ("close", "day_pct", "wtd_pct", "vol_ratio", "stale")}})
        us = gmap.get(key, {})
        # 用台股這一盤「反應的那個美股交易日」做當日比較，時間才對得上
        ref = pd.Timestamp(reacts_to) if reacts_to else us_date
        us_ref = [metrics_at(px, t, ref) for t in CFG["groups"].get(key, {}).get("tickers", [])]
        us_ref_day = mean_or_none([x.get("day_pct") for x in us_ref if x])
        mapping.append({"key": key, "us_name": us.get("name"), "us_ref_date": ref.strftime("%Y-%m-%d"),
                        "us_day_pct": us_ref_day, "us_wtd_pct": us.get("wtd_pct"),
                        "tw_name": m["name"], "tw_day_pct": mean_or_none([x["day_pct"] for x in members]),
                        "tw_wtd_pct": mean_or_none([x["wtd_pct"] for x in members]), "members": members})

    flows = []
    d = tw_date
    for _ in range(10):
        if len(flows) >= 5:
            break
        if d.weekday() < 5:
            f = twse_foreign(d)
            if f:
                flows.append(f)
            time.sleep(1.2)
        d -= pd.Timedelta(days=1)

    return {"date": tw_date.strftime("%Y-%m-%d"), "relation": relation, "reacts_to_us": reacts_to, "indices": indices,
            "usdtwd": fx, "adr_premium": prem, "mapping": mapping, "foreign_flows": flows}


# ---------------------------------------------------------------- 主程式
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", choices=["thu", "fri", "auto"], default="auto")
    ap.add_argument("--allow-stale", action="store_true", help="資料過期也照寫（除錯用）")
    args = ap.parse_args()

    us_t = [*CFG["indices"], *CFG["macro"], *CFG["sectors"], CFG["taiwan"]["adr"]["us"]]
    for g in CFG["groups"].values():
        us_t += g["tickers"]
    tw_t = [*CFG["taiwan"]["indices"], CFG["taiwan"]["fx"], CFG["taiwan"]["adr"]["tw"]]
    for m in CFG["taiwan"]["mapping"].values():
        tw_t += m["tickers"]

    px = download(us_t + tw_t)
    spy = px[CFG["benchmark"]]
    session_date = spy.index[-1]
    now_et = datetime.now(ET)
    today_et = now_et.date()

    # 新鮮度檢查：Yahoo 還沒補上最近交易日的日K時，直接失敗、不寫檔（避免被誤判成休市）
    import holidays
    nyse = holidays.financial_holidays("NYSE", years=[today_et.year - 1, today_et.year])
    expected = expected_session_date(now_et.replace(tzinfo=None), set(nyse.keys()))
    if session_date.date() < expected and not args.allow_stale:
        print(f"::error::STALE_DATA: SPY 最後一根日K是 {session_date.date()}，預期 {expected}（Yahoo 尚未更新）。不寫檔。")
        sys.exit(2)

    session = args.session
    if session == "auto":
        session = {3: "thu", 4: "fri"}.get(session_date.weekday(), "other")
    thu_i = thursday_index(spy.index, len(spy) - 1)
    thu_date = spy.index[thu_i] if (session == "fri" and thu_i is not None and spy.index[thu_i] != session_date) else None

    us = build_us(px, session_date, thu_date)
    tw = build_tw(px, session_date, us["groups"])

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session": session,
        "session_date": session_date.strftime("%Y-%m-%d"),
        "thu_date": thu_date.strftime("%Y-%m-%d") if thu_date is not None else None,
        "market_closed_today": today_et.weekday() < 5 and today_et in nyse,
        "rules_note": CFG["rules"]["_note"],
        "us": us,
        "taiwan": tw,
    }
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "history").mkdir(exist_ok=True)
    txt = json.dumps(out, ensure_ascii=False, indent=1, allow_nan=False, default=str)
    (DATA / "latest.json").write_text(txt, encoding="utf-8")
    key = f"{out['session_date']}-{session}"
    (DATA / "history" / f"{key}.json").write_text(txt, encoding="utf-8")

    idx_path = DATA / "index.json"
    idx = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else []
    idx = [x for x in idx if x["key"] != key] + [{"key": key, "date": out["session_date"], "session": session}]
    idx_path.write_text(json.dumps(sorted(idx, key=lambda x: x["key"]), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ok {key}: {len(us['sectors'])} sectors, {len(us['groups'])} groups, TW {tw.get('date')}")


if __name__ == "__main__":
    main()
