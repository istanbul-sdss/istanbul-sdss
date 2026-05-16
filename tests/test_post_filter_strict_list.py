"""
Regresyon: post_filter, strict_tags hem `dict` hem `list[dict]` biçimini
kabul etmeli. Aksi halde assembly_point (list biçimi kullanıyor) pipeline'ı
`AttributeError: 'list' object has no attribute 'items'` ile çöker
(bkz. Kadıköy extraction log).
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from src.services.post_filter import _row_matches_strict, apply_strict_post_filter


def test_row_matches_strict_accepts_dict_form():
    row = pd.Series({"building": "residential", "name": "X"})
    assert _row_matches_strict(row, {"building": "residential"}) is True
    assert _row_matches_strict(row, {"building": "house"}) is False


def test_row_matches_strict_accepts_list_of_dict_form():
    row = pd.Series({"amenity": "assembly_point", "emergency": None})
    # 3 alternatifli OR-of-AND: herhangi biri tam eşleşirse True
    strict = [
        {"emergency": "assembly_point"},
        {"amenity":   "assembly_point"},
        {"amenity":   "emergency_assembly_point"},
    ]
    assert _row_matches_strict(row, strict) is True

    # Hiçbir alternatifi karşılamayan bir satır False dönmeli
    park_row = pd.Series({"amenity": None, "emergency": None, "leisure": "park"})
    assert _row_matches_strict(park_row, strict) is False


def test_apply_strict_post_filter_does_not_crash_for_list_strict():
    """
    Tam pipeline: list-biçimli strict_tags olan assembly_point için
    post_filter çağrısı `.items()` AttributeError fırlatmamalı.
    """
    gdf = gpd.GeoDataFrame(
        {
            "amenity":   ["assembly_point", None,           None],
            "emergency": [None,             "assembly_point", None],
            "leisure":   [None,             None,           "park"],
            "name":      ["Toplanma A",     "Toplanma B",   "Moda Parkı"],
            "osm_id":    ["1", "2", "3"],
            "geometry":  [Point(29.00, 41.0), Point(29.01, 41.0), Point(29.02, 41.0)],
        },
        crs="EPSG:4326",
    )

    # Çökmemeli — ve strict-eşleşen iki kaydı tutmalı.
    filtered = apply_strict_post_filter(gdf, "assembly_point")

    # Park strict'e uymuyor ama query_tags (leisure=park) primary_check'e
    # uyduğu için post_filter'da tutulur (rule_engine aşaması bunu sonra
    # unresolved'a atar — burası sadece tag-temel filtre).
    kept_ids = set(filtered["osm_id"].astype(str).tolist())
    assert "1" in kept_ids
    assert "2" in kept_ids
