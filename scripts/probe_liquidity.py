"""一次性探測（第三輪）：DDP H.4.1 ZIP 結構、紐約聯準銀行交易商部位代號、標售欄位。"""
import io, json, re, time, zipfile
import pandas as pd, requests

S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (us-sector-weekly research script)"
t0 = time.time()
r = S.get("https://www.federalreserve.gov/datadownload/Output.aspx?rel=H41&filetype=zip", timeout=120)
print("ZIP", r.status_code, len(r.content), f"{time.time()-t0:.1f}s", r.headers.get("content-type"))
z = zipfile.ZipFile(io.BytesIO(r.content))
for n in z.namelist():
    info = z.getinfo(n); print("FILE", n, info.file_size)
for n in z.namelist():
    if not n.lower().endswith(".csv"):
        print("--- non-csv head", n, z.read(n)[:1500].decode("utf-8", "ignore")); continue
    raw = z.read(n).decode("utf-8", "ignore").splitlines()
    print(f"--- {n}: {len(raw)} lines")
    for L in raw[:7]: print("   H", L[:400])
    for L in raw[-2:]: print("   T", L[:400])
    hdr = [list(x) for x in pd.read_csv(io.StringIO("\n".join(raw[:6])), header=None).values]
    ncol = len(hdr[0]); print("   ncol", ncol)
    keys = ["Reserve balances", "General Account", "Reverse repurchase", "Currency in circulation", "Reserve Bank credit",
            "Primary credit", "Secondary credit", "Seasonal", "liquidity swaps", "Bills", "nominal", "inflation-indexed",
            "Mortgage-backed", "Total assets", "Repurchase agreements", "Foreign official", "Other deposits", "Others",
            "custody", "Earnings remittances", "Securities lent", "Within 15 days", "16 days", "91 days", "1 year to 5",
            "5 year", "Over 10", "Total factors", "Other liabilities", "Deposits with F.R."]
    for j in range(1, ncol):
        desc = str(hdr[0][j]); code = str(hdr[-1][j]) if len(hdr) > 1 else ""
        col = [str(h[j]) for h in hdr]
        if any(k.lower() in desc.lower() for k in keys):
            print(f"   C{j} ", " ~ ".join(c[:160] for c in col))

r = S.get("https://markets.newyorkfed.org/api/pd/list/timeseries.json", timeout=30)
for t in r.json()["pd"]["timeseries"]:
    d = t["description"]
    if t["seriesbreak"] == "SBN2024" and ("U.S. Treasury" in d or "Treasury" in d) and ("Net" in d or "TOT" in t["keyid"]) and "Financing" not in d:
        print("PD", t["keyid"], "|", d[:200])

r = S.get("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query?filter=auction_date:gte:2026-10-26&sort=-auction_date&page%5Bsize%5D=40", timeout=30)
print("AUC", r.status_code)
for d in r.json().get("data", []):
    print("AUC", {k: d.get(k) for k in ["auction_date", "security_type", "security_term", "offering_amt", "high_yield", "high_investment_rate", "high_discnt_rate", "bid_to_cover_ratio", "primary_dealer_accepted", "indirect_bidder_accepted", "direct_bidder_accepted", "total_accepted", "comp_accepted", "reopening", "cash_management_bill_cmb"]})
