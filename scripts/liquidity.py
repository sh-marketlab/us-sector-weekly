"""聯準會資產負債表（H.4.1）、資金市場、財政部與部位 — 數據管線。

每個來源獨立 try/except：任何一個失敗只會讓該區塊顯示「資料未取得」，不影響週報主體。
來源（皆不需 API key；FRED 為選用，需 GitHub secret FRED_API_KEY）：
  聯準會 H.4.1 網頁（含歷史期別）、紐約聯準銀行 Markets API、美國財政部殖利率 CSV、
  FiscalData（每日 TGA）、TreasuryDirect（標售結果）、芝加哥聯準銀行 NFCI、CFTC、Yahoo Finance。
"""
from __future__ import annotations

import io
import json
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from liqcalc import (bid_to_cover_band, direction_check, fixed_signal, last_on_or_before, pct_rank,
                     pct_signal, r, tga_scenarios, waterfall, worse)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "data"
CACHE = DATA / "liquidity" / "h41_weeks.json"
UA = {"User-Agent": "Mozilla/5.0 (us-sector-weekly; research; +https://github.com/sh-marketlab/us-sector-weekly)"}
S = requests.Session()
S.headers.update(UA)
LOG: list[str] = []


def log(msg: str) -> None:
    print(f"[liquidity] {msg}", flush=True)
    LOG.append(msg)


def get(url: str, timeout: int = 30, **kw):
    r_ = S.get(url, timeout=timeout, **kw)
    r_.raise_for_status()
    return r_


# ============================================================ H.4.1
T1_KEYS = [  # (標籤開頭, key, 上一層 key 或 None)
    ("Reserve Bank credit", "fed_credit"), ("Securities held outright", "sec_outright"),
    ("U.S. Treasury securities", "ust"), ("Bills", "bills"), ("Notes and bonds, nominal", "nb_nominal"),
    ("Notes and bonds, inflation-indexed", "tips"), ("Mortgage-backed securities", "mbs"),
    ("Repurchase agreements", "repo"), ("Foreign official", "repo_fima"), ("Others", "repo_others"),
    ("Loans", "loans"), ("Primary credit", "primary"), ("Secondary credit", "secondary"),
    ("Seasonal credit", "seasonal"), ("Central bank liquidity swaps", "swaps"),
    ("Total factors supplying reserve funds", "supply"),
]
T2_KEYS = [
    ("Currency in circulation", "currency"), ("Reverse repurchase agreements", "rrp"),
    ("Foreign official and international accounts", "rrp_foreign"), ("Others", "rrp_others"),
    ("Treasury cash holdings", "treas_cash"), ("Deposits with F.R. Banks, other than reserve balances", "dep_nonres"),
    ("Term deposits held by depository institutions", "term_dep"), ("U.S. Treasury, General Account", "tga"),
    ("Foreign official", "dep_foreign"), ("Other", "dep_other"), ("Other liabilities and capital", "other_liab"),
    ("Total factors, other than reserve balances", "absorb"), ("Reserve balances with Federal Reserve Banks", "reserves"),
]
T1A_KEYS = [
    ("Securities held in custody for foreign official", "custody"), ("Marketable U.S. Treasury securities", "custody_ust"),
    ("Federal agency debt and mortgage-backed securities", "custody_agency"), ("Other securities", "custody_other"),
    ("Securities lent to dealers", "sec_lent"),
]
MATURITY_BUCKETS = ["15 天內", "16–90 天", "91 天–1 年", "1–5 年", "5–10 年", "10 年以上", "合計"]


def _num(x):
    """'- 1,096' / '+ 165,201' / 6705765.0 / '...' → float（百萬美元）。"""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return None if pd.isna(x) else float(x)
    s = str(x).replace(",", "").replace(" ", "").replace("−", "-").replace("(0)", "")
    if s in ("", "...", "nan", "n.a.", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _label(x) -> str:
    return re.sub(r"\d+$", "", str(x)).strip()


def _seq_extract(df: pd.DataFrame, keys, cols=(1, 2, 3, 4)) -> dict:
    """依序比對標籤（處理重複的 Others / Foreign official）。值換算成十億美元。"""
    out, k = {}, 0
    for _, row in df.iterrows():
        if k >= len(keys):
            break
        lab = _label(row.iloc[0])
        if lab.lower().startswith(keys[k][0].lower()):
            vals = [_num(row.iloc[c]) if c < len(row) else None for c in cols]
            out[keys[k][1]] = {n: (None if v is None else v / 1000.0) for n, v in zip(("avg", "chg_wk", "chg_yr", "wed"), vals)}
            k += 1
    return out


def parse_h41(html: str) -> dict:
    tabs = pd.read_html(io.StringIO(html))
    first = lambda t: " ".join(map(str, t.iloc[:, 0].tolist()))  # noqa: E731
    t1 = next(t for t in tabs if "Reserve Bank credit" in first(t) and "Total factors supplying" in first(t))
    t2 = next(t for t in tabs if "Currency in circulation" in first(t) and "Reserve balances with" in first(t))
    head = " ".join(" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in t1.columns)
    m = re.search(r"Week ended\s+([A-Z][a-z]{2})\w*\.?\s+(\d{1,2}),\s+(\d{4})", head)
    if not m:
        raise ValueError("找不到 Week ended 日期")
    week = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%b %d %Y").date()
    out = {"week": week.isoformat()}
    out.update(_seq_extract(t1, T1_KEYS))
    out.update(_seq_extract(t2, T2_KEYS))
    try:
        t1a = next(t for t in tabs if "Securities held in custody" in first(t))
        out.update(_seq_extract(t1a, T1A_KEYS))
    except StopIteration:
        pass
    # Table 2 到期結構：U.S. Treasury securities 下一列 Holdings、再下一列 Weekly changes
    try:
        t6 = next(t for t in tabs if "Remaining Maturity" in " ".join(map(str, t.columns)))
        labs = [_label(x) for x in t6.iloc[:, 0]]
        i = next(j for j, x in enumerate(labs) if x.startswith("U.S. Treasury securities"))
        hold = [_num(v) for v in t6.iloc[i + 1, 1:8].tolist()]
        chg = [_num(v) for v in t6.iloc[i + 2, 1:8].tolist()]
        j = next(j for j, x in enumerate(labs) if x.startswith("Mortgage-backed"))
        mbs_hold = [_num(v) for v in t6.iloc[j + 1, 1:8].tolist()]
        out["maturity_ust"] = {"holdings": [None if v is None else v / 1000 for v in hold],
                               "weekly_change": [None if v is None else v / 1000 for v in chg]}
        out["maturity_mbs"] = {"holdings": [None if v is None else v / 1000 for v in mbs_hold]}
    except (StopIteration, IndexError):
        pass
    # Table 5 合併資產負債表：總資產（週三）、各項週三變化
    try:
        t5a = next(t for t in tabs if "Total assets" in first(t))
        row = t5a[t5a.iloc[:, 0].astype(str).str.startswith("Total assets")].iloc[0]
        out["total_assets"] = {"wed": _num(row.iloc[2]) / 1000, "chg_wed": _num(row.iloc[3]) / 1000}
        t5b = next(t for t in tabs if "Other deposits held by depository institutions" in first(t))
        for lab, key in [("Other deposits held by depository institutions", "reserves"), ("U.S. Treasury, General Account", "tga"),
                         ("Reverse repurchase agreements", "rrp")]:
            rr = t5b[t5b.iloc[:, 0].astype(str).str.startswith(lab)]
            if len(rr) and key in out:
                out[key]["chg_wed_t5"] = _num(rr.iloc[0, 3]) / 1000
        rr = t5a[t5a.iloc[:, 0].astype(str).str.startswith("Mortgage-backed")]
        if len(rr):
            out["mbs"]["chg_wed_t5"] = _num(rr.iloc[0, 3]) / 1000
    except (StopIteration, IndexError, TypeError):
        pass
    return out


def h41_history(max_weeks: int = 64) -> dict:
    """讀快取 + 抓目前期 + 補齊最近 max_weeks 週。回傳 {week_iso: parsed}。"""
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    cur = parse_h41(get("https://www.federalreserve.gov/releases/h41/current/h41.htm").text)
    cache[cur["week"]] = cur
    latest = date.fromisoformat(cur["week"])
    fetched = 0
    for k in range(1, max_weeks):
        wk = latest - timedelta(weeks=k)
        if wk.isoformat() in cache:
            continue
        for lag in (1, 2, 0, 3, 5, 6):  # 通常週四公布；遇假日順延
            rel = wk + timedelta(days=lag)
            try:
                html = S.get(f"https://www.federalreserve.gov/releases/h41/{rel:%Y%m%d}/", timeout=30)
                if html.status_code != 200:
                    continue
                p = parse_h41(html.text)
                cache[p["week"]] = p
                fetched += 1
                break
            except Exception:  # noqa: BLE001
                continue
        time.sleep(0.15)
    keep = sorted(cache)[-(max_weeks + 4):]
    cache = {k: cache[k] for k in keep}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"H.4.1 週別 {len(cache)}（本次補抓 {fetched}），最新週 {cur['week']}")
    return cache


def _ser(cache: dict, key: str, field: str = "avg") -> pd.Series:
    d = {pd.Timestamp(w): (v.get(key) or {}).get(field) for w, v in cache.items()}
    return pd.Series(d, dtype=float).sort_index().dropna()


def build_h41(cache: dict, qra: dict | None) -> dict:
    weeks = sorted(cache)
    cur, prev = cache[weeks[-1]], (cache[weeks[-2]] if len(weeks) > 1 else {})
    g = lambda k, f="avg", src=cur: (src.get(k) or {}).get(f)  # noqa: E731
    hist = lambda k, f="avg": _ser(cache, k, f).iloc[-61:].tolist()  # noqa: E731

    def item(key, name, bad=None, fixed=None, note=""):
        avg, wed = g(key), g(key, "wed")
        chg = g(key, "chg_wk")
        wed_prev = g(key, "wed", prev) if prev else None
        chg_wed = (wed - wed_prev) if (wed is not None and wed_prev is not None) else g(key, "chg_wed_t5")
        p = pct_rank(hist(key), avg) if bad else None
        sig = worse(pct_signal(p, bad) if bad else None, fixed(avg, wed) if fixed else None)
        return {"key": key, "name": name, "avg": r(avg, 1), "wed": r(wed, 1), "chg_wk": r(chg, 1), "chg_wed": r(chg_wed, 1),
                "chg_yr": r(g(key, "chg_yr"), 1), "pct": p, "signal": sig or "方向", "note": note}

    res_rule = lambda a, w: "注意" if (g("reserves", "chg_wk") or 0) <= -50 else None  # noqa: E731
    cards = [
        item("reserves", "銀行準備金", bad="low", fixed=res_rule, note="★ 一年分布：第 20 百分位以下▲、第 5 百分位以下■；單週減少 ≥500 億美元也列▲"),
        item("tga", "TGA 財政部帳戶", bad="high", note="★ 一年分布：第 80 百分位以上▲、第 95 百分位以上■"),
        item("rrp_others", "國內逆回購（Others）", fixed=lambda a, w: fixed_signal(w, 100, None, bad="low"), note="☆ 低於 1,000 億美元▲（緩衝幾乎耗盡）"),
        item("primary", "貼現窗口 Primary credit", fixed=lambda a, w: fixed_signal(a, 5, 15), note="☆ <50 億●、50–150 億▲、≥150 億■"),
        item("secondary", "Secondary credit", fixed=lambda a, w: "警告" if (a or 0) > 0 else "正常", note="☆ 只要不為 0 即■"),
        item("swaps", "央行美元交換", fixed=lambda a, w: fixed_signal(w, 1, 5), note="☆ <10 億●、10–50 億▲、≥50 億■"),
        item("repo_fima", "FIMA 回購", fixed=lambda a, w: "注意" if (a or 0) > 0 else "正常", note="☆ 0 正常，大於 0▲"),
        item("repo_others", "常備回購 SRF 等", fixed=lambda a, w: fixed_signal(a, 1, None), note="☆ 接近 0●，達 10 億美元以上▲"),
        item("bills", "聯準會持有 Bills", note="○ 只記方向"),
        item("custody_ust", "外國機構保管公債", note="○ 只記方向；持續減少▲"),
    ]
    rows = [item(k, n) for k, n in [
        ("fed_credit", "聯準會信用供給 Reserve Bank credit"), ("supply", "供給因素合計"), ("ust", "美國公債"), ("bills", "Bills 短期公債"),
        ("nb_nominal", "名目 Notes 與 Bonds"), ("tips", "TIPS"), ("mbs", "MBS"), ("repo_fima", "回購：FIMA"), ("repo_others", "回購：其他（SRF 等）"),
        ("primary", "Primary credit"), ("secondary", "Secondary credit"), ("seasonal", "Seasonal credit"), ("swaps", "央行美元交換"),
        ("currency", "流通現金"), ("rrp", "逆回購合計"), ("rrp_foreign", "逆回購：海外官方"), ("rrp_others", "逆回購：國內 Others"),
        ("term_dep", "定期存款"), ("tga", "TGA"), ("dep_foreign", "海外官方存款"), ("dep_other", "其他存款"),
        ("other_liab", "其他負債與資本"), ("reserves", "準備金")]]
    memo = [item(k, n) for k, n in [("custody", "外國機構保管證券合計"), ("custody_ust", "其中：可交易美國公債"),
                                     ("custody_agency", "其中：機構債與 MBS"), ("custody_other", "其中：其他"), ("sec_lent", "借出證券（隔夜）")]]

    other_dep = sum((g(k, "chg_wk") or 0) for k in ("dep_foreign", "dep_other", "treas_cash", "term_dep"))
    wf = waterfall([("聯準會供給", g("supply", "chg_wk")), ("TGA", -(g("tga", "chg_wk") or 0)),
                    ("其他存款等", -other_dep), ("現金", -(g("currency", "chg_wk") or 0)),
                    ("逆回購", -(g("rrp", "chg_wk") or 0)), ("其他負債與資本", -(g("other_liab", "chg_wk") or 0))],
                   g("reserves", "chg_wk"))

    ta = (cur.get("total_assets") or {}).get("wed")
    ta_prev = (prev.get("total_assets") or {}).get("wed") if prev else None
    nl = lambda c, dom: None if None in ((c.get("total_assets") or {}).get("wed"), g("tga", "wed", c), g("rrp_others" if dom else "rrp", "wed", c)) \
        else c["total_assets"]["wed"] - g("tga", "wed", c) - g("rrp_others" if dom else "rrp", "wed", c)  # noqa: E731
    simple = None
    if None not in (g("supply", "chg_wk"), g("tga", "chg_wk"), g("rrp_others", "chg_wk")):
        simple = g("supply", "chg_wk") - g("tga", "chg_wk") - g("rrp_others", "chg_wk")
    prev_simple = None
    if prev and None not in (g("supply", "chg_wk", prev), g("tga", "chg_wk", prev), g("rrp_others", "chg_wk", prev)):
        prev_simple = g("supply", "chg_wk", prev) - g("tga", "chg_wk", prev) - g("rrp_others", "chg_wk", prev)

    trend = []
    for w in weeks[-4:]:
        c = cache[w]
        trend.append({"week": w, "reserves": r(g("reserves", "avg", c), 1), "reserves_chg": r(g("reserves", "chg_wk", c), 1),
                      "tga": r(g("tga", "avg", c), 1), "tga_chg": r(g("tga", "chg_wk", c), 1),
                      "rrp": r(g("rrp", "avg", c), 1), "rrp_chg": r(g("rrp", "chg_wk", c), 1),
                      "total_assets": r((c.get("total_assets") or {}).get("wed"), 1),
                      "signal": pct_signal(pct_rank(hist("reserves"), g("reserves", "avg", c)), "low")})

    dirs = []
    for k, n in [("reserves", "銀行準備金"), ("tga", "TGA"), ("rrp", "逆回購總額"), ("supply", "聯準會供給"), ("mbs", "MBS")]:
        it = item(k, n)
        dirs.append({"name": n, "chg_wed": it["chg_wed"], "chg_avg": it["chg_wk"], "verdict": direction_check(it["chg_wed"], it["chg_wk"])})
    if ta is not None and ta_prev is not None:
        dirs[3]["chg_wed"] = r(ta - ta_prev, 1)

    mat = cur.get("maturity_ust") or {}
    hold = mat.get("holdings") or []
    total = hold[6] if len(hold) > 6 and hold[6] else (sum(x for x in hold[:6] if x) if hold else None)
    maturity = [{"bucket": MATURITY_BUCKETS[i], "holdings": r(hold[i], 1), "share": r(100 * hold[i] / total, 1) if total and hold[i] is not None else None,
                 "weekly_change": r((mat.get("weekly_change") or [None] * 7)[i], 1)} for i in range(min(6, len(hold)))]

    yr_res = hist("reserves")
    return {
        "week": cur["week"], "prev_week": weeks[-2] if len(weeks) > 1 else None, "weeks_in_history": len(weeks),
        "cards": cards, "rows": rows, "memo": memo, "waterfall": wf,
        "net_liquidity": {"total_assets_wed": r(ta, 1), "total_assets_chg": r((ta - ta_prev) if (ta and ta_prev) else (cur.get("total_assets") or {}).get("chg_wed"), 1),
                          "level": r(nl(cur, False), 1), "level_domestic": r(nl(cur, True), 1),
                          "chg": r(nl(cur, False) - nl(prev, False), 1) if prev and nl(prev, False) is not None and nl(cur, False) is not None else None,
                          "chg_domestic": r(nl(cur, True) - nl(prev, True), 1) if prev and nl(prev, True) is not None and nl(cur, True) is not None else None,
                          "simple_chg": r(simple, 1), "simple_chg_prev": r(prev_simple, 1),
                          "formula": "淨流動性＝總資產（週三）－TGA（週三）－逆回購（週三）；簡易流動性變化＝Δ供給－ΔTGA－Δ國內逆回購（週平均）"},
        "trend": trend, "direction": dirs, "maturity": maturity,
        "maturity_note": f"一年內到期 {r(sum(x['holdings'] or 0 for x in maturity[:3]), 1)}，占 {r(sum(x['share'] or 0 for x in maturity[:3]), 1)}%（計算）" if maturity else None,
        "tga_scenarios": tga_scenarios(g("tga", "wed"), g("reserves", "wed"), yr_res, qra),
        "reserves_range": {"min": r(min(yr_res), 1) if yr_res else None, "max": r(max(yr_res), 1) if yr_res else None,
                           "p5": r(pd.Series(yr_res).quantile(.05), 1) if yr_res else None, "p20": r(pd.Series(yr_res).quantile(.2), 1) if yr_res else None},
    }


# ============================================================ 利率與資金市場
def nyfed_rates(n: int = 300) -> dict:
    out = {}
    for typ, path in [("SOFR", "secured/sofr"), ("EFFR", "unsecured/effr")]:
        j = get(f"https://markets.newyorkfed.org/api/rates/{path}/last/{n}.json").json()["refRates"]
        out[typ] = pd.Series({pd.Timestamp(x["effectiveDate"]): float(x["percentRate"]) for x in j}).sort_index()
        if typ == "EFFR":
            j = sorted(j, key=lambda x: x["effectiveDate"])
            out["range"] = (j[-1].get("targetRateFrom"), j[-1].get("targetRateTo"), j[-1]["effectiveDate"])
            out["upper"] = pd.Series({pd.Timestamp(x["effectiveDate"]): _num(x.get("targetRateTo")) for x in j}, dtype=float).dropna()
    return out


def nyfed_rp(n: int = 260) -> dict:
    """ON RRP（國內）每日承作量與利率、常備回購（SRF）每日承作量與上限利率。"""
    out = {}
    j = get(f"https://markets.newyorkfed.org/api/rp/reverserepo/all/results/last/{n}.json").json()["repo"]["operations"]
    rrp = {}
    for o in j:
        if o.get("term") == "Overnight":
            rrp[pd.Timestamp(o["operationDate"])] = (o.get("totalAmtAccepted") or 0) / 1e9
            if "rrp_rate" not in out:
                d = (o.get("details") or [{}])[0]
                out["rrp_rate"] = d.get("percentAwardRate") or d.get("percentOfferingRate")
    out["rrp"] = pd.Series(rrp).sort_index()
    j = get(f"https://markets.newyorkfed.org/api/rp/repo/all/results/last/{n}.json").json()["repo"]["operations"]
    rp = {}
    for o in j:
        k = pd.Timestamp(o["operationDate"])
        rp[k] = rp.get(k, 0) + (o.get("totalAmtAccepted") or 0) / 1e9
        if "srf_rate" not in out:
            out["srf_rate"] = (o.get("details") or [{}])[0].get("percentOfferingRate")
    out["srf"] = pd.Series(rp).sort_index()
    return out


def treasury_csv(kind: str, years) -> pd.DataFrame:
    frames = []
    for y in years:
        u = (f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all"
             f"?type={kind}&field_tdr_date_value={y}&page&_format=csv")
        try:
            df = pd.read_csv(io.StringIO(get(u).text))
            df["Date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y")
            frames.append(df.set_index("Date"))
        except Exception as e:  # noqa: BLE001
            log(f"財政部 {kind} {y} 失敗：{e}")
    return pd.concat(frames).sort_index() if frames else pd.DataFrame()


def nfci() -> pd.Series:
    df = pd.read_csv(io.StringIO(get("https://www.chicagofed.org/-/media/publications/nfci/nfci-data-series-csv.csv").text))
    df["d"] = pd.to_datetime(df.iloc[:, 0], format="%m/%d/%Y")
    return df.set_index("d")["NFCI"].astype(float)


def fred(series_id: str, start: str) -> pd.Series | None:
    key = os.environ.get("FRED_API_KEY")
    if not key:
        return None
    j = get("https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": series_id, "api_key": key, "file_type": "json", "observation_start": start}).json()
    s = pd.Series({pd.Timestamp(o["date"]): _num(o["value"]) for o in j.get("observations", [])}, dtype=float)
    return s.dropna()


def ind(name, s: pd.Series | None, *, unit="%", d=2, bad=None, fixed=None, chg_unit="bp", group="", note="", star_note=True):
    """一般指標卡：目前值、一週變化、一年位置與判定。"""
    if s is None or not len(s.dropna()):
        return {"name": name, "group": group, "value": None, "signal": None, "note": note or "資料未取得"}
    s = s.dropna()
    v, dt = float(s.iloc[-1]), s.index[-1]
    wk = last_on_or_before(s, dt - pd.Timedelta(days=7))
    yr = s[s.index > dt - pd.Timedelta(days=365)]
    p = pct_rank(yr.tolist(), v)
    chg = None if wk is None else (v - wk) * (100 if chg_unit == "bp" else 1)
    sig = worse(pct_signal(p, bad) if bad else None, fixed(v) if fixed else None)
    return {"name": name, "group": group, "value": r(v, d), "unit": unit, "date": dt.strftime("%Y-%m-%d"),
            "chg_wk": r(chg, 1 if chg_unit == "bp" else d), "chg_unit": chg_unit, "pct": p,
            "lo": r(yr.min(), d), "hi": r(yr.max(), d), "signal": sig or "方向", "note": note}


# ============================================================ 財政部：每日 TGA、標售
def dts_tga(start: str) -> pd.Series:
    u = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance"
         f"?filter=record_date:gte:{start}&page%5Bsize%5D=1000")
    rows = get(u).json()["data"]
    s = {}
    for x in rows:
        if "Closing Balance" in x.get("account_type", ""):
            v = _num(x.get("close_today_bal")) or _num(x.get("open_today_bal"))
            if v is not None:
                s[pd.Timestamp(x["record_date"])] = v / 1000.0
    return pd.Series(s, dtype=float).sort_index()


def auctions(days: int = 9) -> list[dict]:
    out = []
    try:
        j = get(f"https://www.treasurydirect.gov/TA_WS/securities/auctioned?format=json&days={days}").json()
        for x in j:
            btc = _num(x.get("bidToCoverRatio"))
            if btc is None:
                continue
            comp = _num(x.get("competitiveAccepted")) or _num(x.get("totalAccepted"))
            pd_acc, ind_acc = _num(x.get("primaryDealerAccepted")), _num(x.get("indirectBidderAccepted"))
            out.append({"date": (x.get("auctionDate") or "")[:10], "type": x.get("securityType"), "term": x.get("securityTerm"),
                        "size_b": r((_num(x.get("offeringAmount")) or 0) / 1e9, 1),
                        "rate": _num(x.get("highYield")) or _num(x.get("highInvestmentRate")) or _num(x.get("highDiscountRate")),
                        "btc": r(btc, 2), "band": bid_to_cover_band(btc),
                        "dealer_pct": r(100 * pd_acc / comp, 1) if pd_acc and comp else None,
                        "indirect_pct": r(100 * ind_acc / comp, 1) if ind_acc and comp else None,
                        "reopening": x.get("reopening"), "cmb": x.get("cashManagementBillCMB")})
    except Exception as e:  # noqa: BLE001
        log(f"TreasuryDirect 標售失敗：{e}")
    out.sort(key=lambda x: x["date"])
    return out


# ============================================================ 部位：CFTC、主要交易商
CFTC = [("098662", "美元指數"), ("13874A", "S&P 500（E-mini）"), ("209742", "那斯達克100（mini）")]


def cftc() -> list[dict]:
    out = []
    for code, name in CFTC:
        try:
            lg = get(f"https://publicreporting.cftc.gov/resource/6dca-aqww.json?cftc_contract_market_code={code}"
                     "&$order=report_date_as_yyyy_mm_dd%20DESC&$limit=2").json()
            tf = get(f"https://publicreporting.cftc.gov/resource/gpe5-46if.json?cftc_contract_market_code={code}"
                     "&$order=report_date_as_yyyy_mm_dd%20DESC&$limit=2").json()
            net = lambda x, a, b: (_num(x.get(a)) or 0) - (_num(x.get(b)) or 0)  # noqa: E731
            nc = [net(x, "noncomm_positions_long_all", "noncomm_positions_short_all") for x in lg]
            lm = [net(x, "lev_money_positions_long", "lev_money_positions_short") for x in tf]
            am = [net(x, "asset_mgr_positions_long", "asset_mgr_positions_short") for x in tf]
            out.append({"name": name, "date": (lg[0]["report_date_as_yyyy_mm_dd"] if lg else "")[:10],
                        "noncomm_net": nc[0] if nc else None, "noncomm_chg": nc[0] - nc[1] if len(nc) > 1 else None,
                        "levmoney_net": lm[0] if lm else None, "levmoney_chg": lm[0] - lm[1] if len(lm) > 1 else None,
                        "assetmgr_net": am[0] if am else None, "assetmgr_chg": am[0] - am[1] if len(am) > 1 else None})
        except Exception as e:  # noqa: BLE001
            log(f"CFTC {name} 失敗：{e}")
    return out


def primary_dealers() -> dict | None:
    lst = get("https://markets.newyorkfed.org/api/pd/list/timeseries.json").json()["pd"]["timeseries"]
    desc = {x["keyid"]: x["description"] for x in lst if x.get("seriesbreak") == "SBN2024"}
    latest = get("https://markets.newyorkfed.org/api/pd/latest/SBN2024.json").json()["pd"]["timeseries"]
    val = {x["keyid"]: (_num(x.get("value")), x.get("asofdate")) for x in latest}
    pick = []
    for k, dsc in desc.items():
        if k.startswith("PDPOS") and "U.S. Treasury" in dsc and "TIPS" not in dsc and k in val and val[k][0] is not None:
            pick.append({"key": k, "desc": dsc, "value_b": r(val[k][0] / 1000, 1), "asof": val[k][1]})
    pick.sort(key=lambda x: x["key"])
    return {"asof": pick[0]["asof"] if pick else None, "positions": pick[:12]} if pick else None


# ============================================================ 市場內部、全球、商品（Yahoo）
YF = {
    "credit": [("HYG/SHY", "HYG", "SHY", "low"), ("垃圾債 JNK", "JNK", None, "low"), ("區域銀行 KRE", "KRE", None, "low"), ("長天期公債 TLT", "TLT", None, None)],
    "internal": [("IWM/QQQ 小型對大型", "IWM", "QQQ", "low"), ("RSP/SPY 市場廣度", "RSP", "SPY", "low"), ("QQQ/SPY", "QQQ", "SPY", None),
                 ("XLY/XLP 非必需對必需", "XLY", "XLP", "low"), ("半導體 SOXX", "SOXX", None, None), ("住宅建築 XHB", "XHB", None, None), ("運輸 IYT", "IYT", None, None)],
    "sentiment": [("VIX", "^VIX", None, "high"), ("MOVE 債券波動度", "^MOVE", None, "high")],
    "global": [("美元指數 DXY", "DX-Y.NYB", None, None), ("美元兌新台幣", "TWD=X", None, None), ("美元兌日圓", "JPY=X", None, None),
               ("美元兌人民幣", "CNY=X", None, None), ("歐元兌美元", "EURUSD=X", None, None), ("美元兌韓元", "KRW=X", None, None),
               ("新興市場股票 EEM", "EEM", None, None), ("新興市場債 EMB", "EMB", None, None), ("日經 225", "^N225", None, None), ("歐洲 STOXX 50", "^STOXX50E", None, None)],
    "commod": [("黃金 GLD", "GLD", None, None), ("白銀 SLV", "SLV", None, None), ("銅 CPER", "CPER", None, None), ("金銅比 GLD/CPER", "GLD", "CPER", None),
               ("原油 USO", "USO", None, None), ("布蘭特 BNO", "BNO", None, None), ("天然氣 UNG", "UNG", None, None),
               ("比特幣", "BTC-USD", None, None), ("以太幣", "ETH-USD", None, None)],
}
YF_GROUP = {"credit": "信用", "internal": "市場內部", "sentiment": "情緒與波動度", "global": "全球與匯率", "commod": "原物料與加密貨幣"}


def yahoo_block() -> dict:
    import yfinance as yf
    tick = sorted({t for g in YF.values() for _, a, b, _ in g for t in (a, b) if t})
    raw = yf.download(tick, period="14mo", interval="1d", auto_adjust=True, group_by="ticker", progress=False, threads=True)
    px = {}
    for t in tick:
        try:
            s = raw[t]["Close"].dropna()
            s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
            px[t] = s
        except Exception:  # noqa: BLE001
            pass
    out = {}
    for g, items in YF.items():
        lst = []
        for name, a, b, bad in items:
            s = px.get(a)
            if s is not None and b:
                s = (s / px.get(b)).dropna() if px.get(b) is not None else None
            lst.append(ind(name, s, unit="", d=4 if b else 2, bad=bad, chg_unit="abs", group=YF_GROUP[g],
                           note="★ 一年分布" if bad else "○ 只記方向"))
        out[g] = lst
    return out


# ============================================================ 組裝
def build_liquidity() -> dict:
    out: dict = {"generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z", "log": LOG}
    qra = None
    try:
        qra = json.loads((DATA / "qra" / "latest.json").read_text(encoding="utf-8"))
        out["qra_key"] = qra.get("key")
    except Exception as e:  # noqa: BLE001
        log(f"QRA 檔讀取失敗：{e}")

    try:
        out["h41"] = build_h41(h41_history(), qra)
    except Exception as e:  # noqa: BLE001
        log(f"H.4.1 失敗：{type(e).__name__} {e}")
        out["h41"] = {"error": f"H.4.1 資料未取得（{type(e).__name__}）"}

    today = date.today()
    rates, rp = {}, {}
    try:
        rates = nyfed_rates()
    except Exception as e:  # noqa: BLE001
        log(f"NY Fed 利率失敗：{e}")
    try:
        rp = nyfed_rp()
    except Exception as e:  # noqa: BLE001
        log(f"NY Fed 回購失敗：{e}")
    yc = treasury_csv("daily_treasury_yield_curve", [today.year - 1, today.year])
    real = treasury_csv("daily_treasury_real_yield_curve", [today.year - 1, today.year])
    bills = treasury_csv("daily_treasury_bill_rates", [today.year])

    # 利率階梯
    lo, hi = (rates.get("range") or (None, None, None))[:2]
    iorb_off = json.loads((ROOT / "config.json").read_text(encoding="utf-8")).get("liquidity", {}).get("iorb_minus_upper", -0.10)
    iorb = (hi + iorb_off) if hi is not None else None
    sofr = rates.get("SOFR")
    ladder = [
        {"name": "隔夜逆回購 ON RRP（下限）", "rate": rp.get("rrp_rate") or lo, "src": "紐約聯準銀行"},
        {"name": "有效聯邦基金利率 EFFR", "rate": None if rates.get("EFFR") is None else float(rates["EFFR"].iloc[-1]),
         "date": None if rates.get("EFFR") is None else rates["EFFR"].index[-1].strftime("%Y-%m-%d"), "src": "紐約聯準銀行"},
        {"name": "準備金餘額利率 IORB", "rate": r(iorb, 2), "src": f"計算：目標區間上限 {iorb_off:+.2f}（依 FOMC 執行說明慣例）"},
        {"name": "SOFR", "rate": None if sofr is None else float(sofr.iloc[-1]), "date": None if sofr is None else sofr.index[-1].strftime("%Y-%m-%d"), "src": "紐約聯準銀行"},
        {"name": "常備回購 SRF（上限）", "rate": rp.get("srf_rate") or hi, "src": "紐約聯準銀行"},
    ]
    if not bills.empty:
        for col, nm in [("4 WEEKS COUPON EQUIVALENT", "1 個月期 T-bill"), ("13 WEEKS COUPON EQUIVALENT", "3 個月期 T-bill")]:
            if col in bills:
                ladder.append({"name": nm, "rate": float(bills[col].dropna().iloc[-1]), "date": bills.index[-1].strftime("%Y-%m-%d"), "src": "財政部（約當殖利率）"})
    out["rate_ladder"] = {"target": [lo, hi], "items": ladder}

    spread = None
    if sofr is not None and rates.get("upper") is not None:
        up = rates["upper"].reindex(sofr.index, method="ffill")
        spread = ((sofr - (up + iorb_off)) * 100).dropna()  # bp
    def col(df, c):  # noqa: E301
        return df[c].astype(float) if (not df.empty and c in df) else None
    y10, y2, y3m, y30, y6m = col(yc, "10 Yr"), col(yc, "2 Yr"), col(yc, "3 Mo"), col(yc, "30 Yr"), col(yc, "6 Mo")
    r10 = col(real, "10 YR")
    bei = (y10 - r10).dropna() if (y10 is not None and r10 is not None) else None
    rates_block = [
        ind("美國 3 個月期公債", y3m, group="利率結構", note="○ 只記方向"),
        ind("美國 6 個月期公債", y6m, group="利率結構", note="○ 只記方向"),
        ind("美國 2 年期公債", y2, bad="high", group="利率結構", note="★ 一年分布"),
        ind("美國 10 年期公債", y10, bad="high", group="利率結構", note="★ 一年分布"),
        ind("美國 30 年期公債", y30, bad="high", group="利率結構", note="★ 一年分布"),
        ind("10 年－3 個月利差", None if y10 is None or y3m is None else (y10 - y3m).dropna(), group="利率結構",
            fixed=lambda v: "警告" if v < 0 else "正常", note="☆ 低於 0 為倒掛"),
        ind("10 年－2 年利差", None if y10 is None or y2 is None else (y10 - y2).dropna(), group="利率結構", note="○ 只記方向"),
        ind("實質利率 10 年 TIPS", r10, group="利率結構", fixed=lambda v: fixed_signal(v, 2.0, None), note="☆ 超過 2% 壓抑成長股"),
        ind("預期通膨 10 年 BEI（計算）", bei, group="利率結構", fixed=lambda v: "正常" if 2 <= v <= 2.5 else "注意", note="☆ 2–2.5% 正常；＝名目 10 年－實質 10 年"),
        ind("SOFR－IORB（bp）", spread, unit="bp", d=0, chg_unit="abs", group="資金市場", bad="high", fixed=lambda v: fixed_signal(v, 5, None),
            note="★ 一年分布＋☆ 5bp 以上▲，取較保守者；IORB＝目標上限 −0.10（計算）"),
        ind("國內 ON RRP 每日（十億美元）", rp.get("rrp"), unit="B", d=1, chg_unit="abs", group="資金市場", note="○ 只記方向"),
        ind("常備回購每日（十億美元）", rp.get("srf"), unit="B", d=2, chg_unit="abs", group="資金市場", fixed=lambda v: fixed_signal(v, 1, None), note="☆ 達 10 億美元▲"),
    ]
    try:
        n = nfci()
        rates_block.append(ind("NFCI 芝加哥聯準銀行", n, unit="", d=3, chg_unit="abs", bad="high", group="金融情勢",
                               note="★ 一年分布；☆ −0.5～0 屬寬鬆、正值偏緊"))
    except Exception as e:  # noqa: BLE001
        log(f"NFCI 失敗：{e}")
    start = (today - timedelta(days=430)).isoformat()
    for sid, nm, kw in [("BAMLH0A0HYM2", "高收益債利差", dict(bad="high", fixed=lambda v: fixed_signal(v, 2.9, 3.5), note="★＋☆ 2.9–3.5% 注意區")),
                        ("BAMLC0A0CM", "投資等級債利差", dict(bad="high", note="★ 一年分布")),
                        ("STLFSI4", "STLFSI4 聖路易聯準銀行", dict(unit="", d=3, chg_unit="abs", fixed=lambda v: "正常" if v < 0 else "注意", note="☆ 低於 0 無壓力")),
                        ("RESPPLLOPNWW", "聯準會遞延資產（十億美元）", dict(unit="B", d=1, chg_unit="abs", note="○ 只記方向")),
                        ("WM2NS", "M2 貨幣供給（十億美元）", dict(unit="B", d=0, chg_unit="abs", note="○ 只記方向")),
                        ("BUSLOANS", "工商業貸款 C&I（十億美元）", dict(unit="B", d=0, chg_unit="abs", note="○ 只記方向")),
                        ("ICSA", "初領失業救濟金（人）", dict(unit="", d=0, chg_unit="abs", note="○ 只記方向"))]:
        try:
            s = fred(sid, start)
            if s is not None and sid == "RESPPLLOPNWW":
                s = s / 1000.0
            rates_block.append(ind(nm, s, group="FRED（選用）", **kw) if s is not None else
                               {"name": nm, "group": "FRED（選用）", "value": None, "note": "未設定 FRED_API_KEY，資料未取得"})
        except Exception as e:  # noqa: BLE001
            log(f"FRED {sid} 失敗：{e}")
            rates_block.append({"name": nm, "group": "FRED（選用）", "value": None, "note": f"FRED 失敗（{type(e).__name__}）"})
    out["rates"] = rates_block

    try:
        out["market"] = yahoo_block()
    except Exception as e:  # noqa: BLE001
        log(f"Yahoo 指標失敗：{e}")

    try:
        t = dts_tga((today - timedelta(days=45)).isoformat())
        out["tga_daily"] = [{"date": d.strftime("%Y-%m-%d"), "tga": r(v, 1)} for d, v in t.items()][-25:]
    except Exception as e:  # noqa: BLE001
        log(f"每日 TGA 失敗：{e}")
    out["auctions"] = auctions()
    out["cftc"] = cftc()
    try:
        out["dealers"] = primary_dealers()
    except Exception as e:  # noqa: BLE001
        log(f"主要交易商失敗：{e}")
    if qra:
        out["qra"] = qra
        tga_w = next((c.get("wed") for c in (out.get("h41") or {}).get("cards", []) if c.get("key") == "tga"), None)
        if tga_w is not None:
            t = qra.get("tga", {})
            out["qra_check"] = {"tga_wed": tga_w, "peak": t.get("peak_b"), "band": t.get("peak_band_b"), "end_dec": t.get("end_dec_assumption_b"),
                                "in_peak_band": abs(tga_w - (t.get("peak_b") or 0)) <= (t.get("peak_band_b") or 0),
                                "gap_to_end_dec": r(tga_w - (t.get("end_dec_assumption_b") or 0), 1)}
    return out


if __name__ == "__main__":
    L = build_liquidity()
    h = L.get("h41", {})
    print("H41 week", h.get("week"), "weeks", h.get("weeks_in_history"))
    for c in h.get("cards", []):
        print("  CARD", c["name"], c["avg"], c["wed"], c["chg_wk"], c["chg_wed"], c["pct"], c["signal"])
    print("  WF", h.get("waterfall"))
    print("  NL", h.get("net_liquidity"))
    print("  TREND", h.get("trend"))
    print("  MAT", h.get("maturity"))
    print("  SCEN", h.get("tga_scenarios"))
    print("LADDER", L.get("rate_ladder"))
    for x in L.get("rates", []):
        print("  RATE", x.get("name"), x.get("value"), x.get("chg_wk"), x.get("pct"), x.get("signal"), x.get("date"))
    for g, lst in (L.get("market") or {}).items():
        for x in lst:
            print("  MKT", g, x.get("name"), x.get("value"), x.get("chg_wk"), x.get("pct"), x.get("signal"))
    print("TGA_DAILY", (L.get("tga_daily") or [])[-5:])
    print("AUCTIONS", L.get("auctions"))
    print("CFTC", L.get("cftc"))
    print("DEALERS", json.dumps(L.get("dealers"), ensure_ascii=False)[:1500])
    print("QRA_CHECK", L.get("qra_check"))
    print("LOG", L.get("log"))
    print("SIZE", len(json.dumps(L, ensure_ascii=False, default=str)))
