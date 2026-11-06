"""一次性探測（第二輪）：H.4.1 HTML 表格結構、財政部殖利率、NFCI、NY Fed 其他端點。"""
import io, json, re, time
import pandas as pd, requests

S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (us-sector-weekly research script)"

def get(u, t=20):
    t0 = time.time()
    try:
        r = S.get(u, timeout=t); print(f"GET {r.status_code} {len(r.content)}B {time.time()-t0:.1f}s {u}", flush=True); return r
    except Exception as e:
        print(f"GET ERR {type(e).__name__} {time.time()-t0:.1f}s {u}", flush=True)

r = get("https://www.federalreserve.gov/releases/h41/20261029/")
if r is not None and r.ok:
    html = r.text
    tabs = pd.read_html(io.StringIO(html))
    print("N_TABLES", len(tabs))
    for i, t in enumerate(tabs):
        cols = [" | ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in t.columns]
        print(f"\n### T{i} shape={t.shape} cols={cols[:8]}")
        for _, row in t.head(60).iterrows():
            vals = [str(v)[:60] for v in row.tolist()[:6]]
            print("   ", " || ".join(vals))
    caps = re.findall(r"<caption[^>]*>(.*?)</caption>", html, flags=re.S)
    print("\nCAPTIONS", [re.sub(r"<[^>]+>|\s+", " ", c).strip()[:90] for c in caps])
    heads = re.findall(r"<h[2-4][^>]*>(.*?)</h[2-4]>", html, flags=re.S)
    print("HEADS", [re.sub(r"<[^>]+>|\s+", " ", c).strip()[:80] for c in heads][:60])

r = get("https://www.federalreserve.gov/datadownload/Choose.aspx?rel=H41")
if r is not None and r.ok:
    print("DDP links", sorted(set(re.findall(r'href="([^"]*(?:Build|Output|Download|series)[^"]*)"', r.text)))[:40])

y = 2026
for typ in ["daily_treasury_yield_curve", "daily_treasury_real_yield_curve", "daily_treasury_bill_rates"]:
    r = get(f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all?type={typ}&field_tdr_date_value={y}&page&_format=csv")
    if r is not None and r.ok: print(r.text[:600])

r = get("https://www.chicagofed.org/-/media/publications/nfci/nfci-data-series-csv.csv")
if r is not None and r.ok: print(r.text[:300], "...", r.text[-300:])
r = get("https://api.stlouisfed.org/fred/series/observations?series_id=WALCL&file_type=json", 15)
if r is not None: print(r.text[:300])
for u in ["https://markets.newyorkfed.org/api/rates/unsecured/effr/last/3.json",
          "https://markets.newyorkfed.org/api/pd/list/timeseries.json",
          "https://markets.newyorkfed.org/api/pd/latest/SBN2024.json",
          "https://markets.newyorkfed.org/api/rp/reverserepo/propositions/search.json?startDate=2026-11-02&endDate=2026-11-05",
          "https://markets.newyorkfed.org/api/rp/reverserepo/all/results/last/3.json",
          "https://markets.newyorkfed.org/api/rp/repo/all/results/last/2.json",
          "https://www.ici.org/research/stats/mmf",
          "https://www.ici.org/mm_summary_data_2026.xls"]:
    r = get(u)
    if r is not None and r.ok: print(r.text[:900])

r = get("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance?filter=record_date:gte:2026-10-26&page%5Bsize%5D=100")
if r is not None and r.ok:
    for d in r.json()["data"]:
        print(d["record_date"], "|", d["account_type"], "|", d["open_today_bal"], "|", d["close_today_bal"])
r = get("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query?filter=auction_date:gte:2026-10-26&sort=-auction_date&page%5Bsize%5D=30&fields=auction_date,security_type,security_term,offering_amt,high_yield,high_investment_rate,high_discnt_rate,bid_to_cover_ratio,primary_dealer_accepted,indirect_bidder_accepted,direct_bidder_accepted,total_accepted,comp_accepted,cash_management_bill_cmb")
if r is not None and r.ok:
    for d in r.json()["data"]: print(json.dumps(d))
