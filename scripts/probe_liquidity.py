"""一次性探測：確認 FRED 序列代號、單位與 Wed/週平均屬性，以及各 API 欄位。"""
import io, json, sys, time
import pandas as pd, requests

IDS = """WALCL WRBWFRBL WORAL WRESBAL WLRESBAL WRESBALNS WLODLL WOTHLB WLDLL WTREGEN WDTGAL WLRRAL WLRRAFOIAL WLRRAOL
WREPODEL RRPONTSYD RRPONTSYAWARD WCURCIR WCICL WLCFLL WLCFLPCL WLCFLSECL WLCFLSCL WPC SWPT WSHOBL WSHONBNL WSHONBIIL
WSHOMCB WSHOTSL RESPPLLOPNWW WMTSECL1 WFCDA TREAS15 TREAS1590 TREAS911Y TREAS1T5 TREAS5T10 TREAS10Y RPONTSYD RPONTTLD
WORAL WREPO WLFN WDFOL WLOFDL SOFR IORB EFFR DFEDTARU DFEDTARL DTB4WK DTB3 DTB6 DGS1MO DGS3MO DGS6MO DGS2 DGS10 DGS30
T10Y3M T10Y2Y DFII10 T10YIE BAMLH0A0HYM2 BAMLC0A0CM NFCI STLFSI4 DTWEXBGS WM2NS BUSLOANS ICSA
H41RESPPALDKNWW H41RESPPALDKXAWNWW RESPPALGUOMNWW WUDSHO WLCFOCEL WFRBCSWAP""".split()

S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (us-sector-weekly research script)"
for u in ["https://fred.stlouisfed.org/graph/fredgraph.csv?id=WALCL",
          "https://www.federalreserve.gov/releases/h41/current/h41.htm",
          "https://www.federalreserve.gov/releases/h41/20261029/",
          "https://www.federalreserve.gov/datadownload/Choose.aspx?rel=H41"]:
    t = time.time()
    try:
        r = S.get(u, timeout=15); print(f"PING {r.status_code} {len(r.content)}B {time.time()-t:.1f}s {u}", flush=True)
    except Exception as e:
        print(f"PING ERR {time.time()-t:.1f}s {u} {e}", flush=True)
def fred(i):
    r = S.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={i}&cosd=2025-09-01", timeout=12)
    if r.status_code != 200 or "DATE" not in r.text[:200].upper():
        return None
    df = pd.read_csv(io.StringIO(r.text)); df.columns = ["d", "v"]
    df["v"] = pd.to_numeric(df["v"], errors="coerce"); df["d"] = pd.to_datetime(df["d"])
    return df.dropna().set_index("d")["v"]

import concurrent.futures as cf
def one(i):
    try:
        s = fred(i)
        if s is None or not len(s):
            return f"MISS {i}"
        at = lambda d: s[s.index <= d].iloc[-1] if (s.index <= d).any() else None
        return (f"OK {i:22s} n={len(s):4d} last={s.index[-1].date()} {s.iloc[-1]:.4f} | 10/28={at('2026-10-28')} 10/21={at('2026-10-21')}")
    except Exception as e:
        return f"ERR {i} {type(e).__name__} {e}"
ex = cf.ThreadPoolExecutor(8)
futs = {ex.submit(one, i): i for i in IDS}
done, pend = cf.wait(futs, timeout=150)
for fu in done: print(fu.result(), flush=True)
for fu in pend: print("TIMEOUT", futs[fu], flush=True)

def show(name, url):
    try:
        r = S.get(url, timeout=20); print(f"== {name} {r.status_code}")
        j = r.json(); d = j.get("data", j) if isinstance(j, dict) else j
        if isinstance(d, list):
            print(json.dumps(d[:3], ensure_ascii=False)[:1500])
        else:
            print(json.dumps(j, ensure_ascii=False)[:1500])
    except Exception as e:
        print(f"== {name} ERR {e}")

FD = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
show("DTS cash", FD + "/v1/accounting/dts/operating_cash_balance?sort=-record_date&page%5Bsize%5D=6")
show("auctions", FD + "/v1/accounting/od/auctions_query?sort=-auction_date&page%5Bsize%5D=3")
show("nyfed sofr", "https://markets.newyorkfed.org/api/rates/secured/sofr/last/3.json")
show("nyfed rp", "https://markets.newyorkfed.org/api/rp/all/all/results/last/3.json")
show("nyfed pd", "https://markets.newyorkfed.org/api/pd/latest/PDPOSGST-TOT.json")
show("cftc legacy", "https://publicreporting.cftc.gov/resource/6dca-aqww.json?cftc_contract_market_code=13874A&$order=report_date_as_yyyy_mm_dd%20DESC&$limit=1")
show("cftc tff", "https://publicreporting.cftc.gov/resource/gpe5-46if.json?cftc_contract_market_code=13874A&$order=report_date_as_yyyy_mm_dd%20DESC&$limit=1")
for code in ["209742", "098662", "20974+"]:
    show(f"cftc legacy {code}", f"https://publicreporting.cftc.gov/resource/6dca-aqww.json?cftc_contract_market_code={code}&$order=report_date_as_yyyy_mm_dd%20DESC&$limit=1")
show("ici", "https://www.ici.org/research/stats/mmf")
