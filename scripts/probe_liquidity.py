import json, requests
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (us-sector-weekly research script)"
j = S.get("https://www.treasurydirect.gov/TA_WS/securities/auctioned?format=json&days=9", timeout=30).json()
print("TD n", len(j)); print("TD keys", sorted(j[0].keys()))
for x in j[:3]:
    print("TD", json.dumps({k: v for k, v in x.items() if v not in ("", None)})[:1800])
lst = S.get("https://markets.newyorkfed.org/api/pd/list/timeseries.json", timeout=30).json()["pd"]["timeseries"]
for t in lst:
    if t["seriesbreak"] == "SBN2024" and t["keyid"].startswith("PDPOS"):
        print("PD", t["keyid"], "|", t["description"][:160])
