import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from liqcalc import (direction_check, fixed_signal, pct_rank, pct_signal, tga_scenarios,  # noqa: E402
                     waterfall, worse)


def test_pct_rank_and_signal():
    h = list(range(1, 101))
    assert pct_rank(h, 10) == 10
    assert pct_signal(10, "low") == "注意"
    assert pct_signal(5, "low") == "警告"
    assert pct_signal(98, "high") == "警告"
    assert pct_signal(50, "high") == "正常"


def test_fixed_and_worse():
    assert fixed_signal(9.5, 5, 15) == "注意"
    assert fixed_signal(0.2, 100, None, bad="low") == "注意"
    assert worse("正常", "警告", None) == "警告"


def test_waterfall_sums():
    # Word 檔 10/28 當週：供給 −1.1、TGA +47.7、RRP +3.1、現金 −1.8、準備金 −68.8
    w = waterfall([("供給", -1.091), ("TGA", -47.725), ("其他存款等", -15.818), ("現金", 1.757),
                   ("逆回購", -3.146), ("其他負債與資本", -2.814)], -68.837)
    parts = [x["impact"] for x in w if not x.get("total")]
    assert abs(sum(parts) - (-68.8)) < 0.15
    assert w[-1]["impact"] == -68.8


def test_tga_scenarios():
    hist = [2850 + i for i in range(0, 330, 5)]
    sc = tga_scenarios(1015.6, 2895.2, hist, {"tga": {"end_dec_assumption_b": 850, "peak_b": 1025, "peak_band_b": 50}})
    assert sc[0]["tga_change"] == -165.6 and sc[0]["reserves_end"] == 3060.8
    assert sc[1]["reserves_end"] == 2835.8 and sc[2]["tga_change"] == 0


def test_direction():
    assert direction_check(-74.3, -68.8) == "方向一致"
    assert direction_check(-8.3, 3.2).startswith("方向不同")
