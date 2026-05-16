"""
Regresyon: harita bileşenleri canonical `category_group` key'i kullanmalı
(bulgu #4).

Eski kodu `kat` (result dict anahtarı) = display label olduğu için palette
lookup'lar DEFAULT_COLOR'a düşüyordu. Artık her `res` dict'i `category_group`
taşıyor ve `map_builder` bunu kullanıyor.
"""
from __future__ import annotations

import pandas as pd

from components.map_builder import CATEGORY_COLORS, DEFAULT_COLOR, legend_data


def _fake_result_entry(lat=41.01, lon=28.97, label_tr="Hastane", cat_group="health"):
    df = pd.DataFrame({
        "Enlem":  [lat, lat + 0.001, lat - 0.001],
        "Boylam": [lon, lon + 0.001, lon - 0.001],
        "Ad":     ["Sample A", "Sample B", "Sample C"],
    })
    return {
        "df":             df,
        "gdf":            None,
        "label_tr":       label_tr,
        "category_group": cat_group,
        "rule_code":      "health_hospital",
    }


def test_legend_uses_canonical_category_group():
    """category_group palette lookup için kullanılmalı, label değil.

    NOT: legend, label_tr'yi translate_category_label() ile İngilizceye
    çevirir (UI İngilizce). Renk lookup'ı ise cat_key üzerinden yapılır —
    burayı kontrol ediyoruz.
    """
    nonempty = {
        "health_hospital":        _fake_result_entry(label_tr="Hastane",      cat_group="health"),
        "green_area_park":        _fake_result_entry(label_tr="Park",         cat_group="green_area"),
        "infrastructure_police":  _fake_result_entry(label_tr="Karakol",      cat_group="infrastructure"),
    }
    legend = legend_data(nonempty)

    # Her entry cat_key taşımalı + renk cat_key'den türemeli
    assert len(legend) == 3
    by_key = {it["cat_key"]: it for it in legend}
    assert by_key["health"]["color"]         == CATEGORY_COLORS["health"]
    assert by_key["green_area"]["color"]     == CATEGORY_COLORS["green_area"]
    assert by_key["infrastructure"]["color"] == CATEGORY_COLORS["infrastructure"]

    # DEFAULT_COLOR hiçbir kayda düşmemiş olmalı
    assert DEFAULT_COLOR not in {it["color"] for it in legend}


def test_legend_falls_back_to_rule_code_prefix_when_no_category_group():
    """Geriye uyumluluk: category_group yoksa rule_code'un ilk segmenti kullanılsın."""
    entry = {
        "df":             pd.DataFrame({"Enlem": [41.0], "Boylam": [29.0], "Ad": ["x"]}),
        "gdf":            None,
        "label_tr":       "Test",
        # category_group YOK — eski bir consumer'ın gönderdiği result gibi
    }
    legend = legend_data({"health_hospital": entry})
    assert len(legend) == 1
    assert legend[0]["color"] == CATEGORY_COLORS["health"], (
        f"Fallback (rule_code ilk segmenti) çalışmıyor: {legend[0]['color']}"
    )


def test_assembly_point_now_paints_green_area_color():
    """
    Bulgu #4'ün bir parçası: assembly_point tag_rules'ta "emergency" iken
    palette'te emergency yoktu → DEFAULT_COLOR'a düşüyordu. Artık
    registry ile hizalı olarak "green_area" kullanıyor.
    """
    from src.config.tag_rules import TAG_RULES
    assert TAG_RULES["assembly_point"]["category_group"] == "green_area", (
        "assembly_point tag_rules'ta hâlâ emergency — palette'te bu key yok, "
        "harita DEFAULT_COLOR'a düşer"
    )
