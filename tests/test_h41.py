import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from liquidity import build_h41, parse_h41  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "h41_20261029_partial.html"


def test_parse_matches_word_doc():
    p = parse_h41(FIX.read_text())
    assert p["week"] == "2026-10-28"
    assert round(p["reserves"]["avg"], 1) == 2893.8 and round(p["reserves"]["chg_wk"], 1) == -68.8
    assert round(p["tga"]["wed"], 1) == 1015.6 and round(p["rrp_others"]["wed"], 2) == 0.18
    assert round(p["total_assets"]["wed"], 1) == 6745.6
    assert round(p["custody_ust"]["avg"], 1) == 2571.8


def test_build_h41_waterfall_and_netliq():
    cur = parse_h41(FIX.read_text())
    prev = copy.deepcopy(cur)
    prev["week"] = "2026-10-21"
    for k in ("reserves", "tga", "rrp", "rrp_others", "supply"):
        prev[k]["avg"] -= prev[k]["chg_wk"]
    cache = {"2026-10-21": prev, "2026-10-28": cur}
    h = build_h41(cache, {"tga": {"end_dec_assumption_b": 850, "peak_b": 1025, "peak_band_b": 50}})
    wf = h["waterfall"]
    assert wf[-1]["impact"] == -68.8
    assert abs(sum(x["impact"] for x in wf if not x.get("total")) - (-68.8)) < 0.2
    nl = h["net_liquidity"]
    assert nl["level"] == round(6745.635 - 1015.632 - 325.837, 1)
    assert nl["simple_chg"] == round(-1.091 - 47.725 - (-0.106), 1)
    assert [c["key"] for c in h["cards"]][:2] == ["reserves", "tga"]
    assert h["tga_scenarios"][0]["tga_change"] == round(850 - 1015.632, 1)
