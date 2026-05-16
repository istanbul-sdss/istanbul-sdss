"""
Regresyon: `add_footprint_area`, Point geometrili kayıtlar için alanı
YALNIZCA iki gerçek/türevsel yöntemle üretmeli, default UYDURMAMALI.

Arka plan: Kadıköy ekstraksiyonunda Point olarak gelen 2 assembly_point
('tanzim', 'Ahmet Taner Kışlalı Parkı') için artık:
  • polygon_overlay: aynı fetch'teki bir poligon içindeyse alanı miras al
  • capacity_derived: OSM `capacity` tag varsa AFAD 1.5 m²/kişi
  • hiçbiri yoksa → footprint_m2 = NaN + area_source = "" (BOŞ BIRAK)

500 m² default artık yok — gerçekçi değildi, sessiz uydurma üretiyordu.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, Polygon

from src.services.spatial_service import (
    AFAD_M2_PER_PERSON,
    add_footprint_area,
)


def _mixed_gdf() -> gpd.GeoDataFrame:
    """Polygon + Point(kapasiteli) + Point(kapasitesiz) karışımı."""
    return gpd.GeoDataFrame(
        {
            "osm_id":   ["poly_1", "pt_capacity", "pt_bare"],
            "capacity": [None,     200,           None],
            "geometry": [
                Polygon([(29.00, 41.00), (29.01, 41.00), (29.01, 41.01), (29.00, 41.01)]),
                Point(29.02, 41.00),
                Point(29.03, 41.00),
            ],
        },
        crs="EPSG:4326",
    )


def test_polygon_rows_keep_measured_provenance():
    out = add_footprint_area(_mixed_gdf())
    poly = out[out["osm_id"] == "poly_1"].iloc[0]
    assert poly["area_source"] == "measured"
    assert poly["footprint_m2"] > 0


def test_point_with_capacity_uses_afad_standard():
    out = add_footprint_area(_mixed_gdf())
    row = out[out["osm_id"] == "pt_capacity"].iloc[0]
    assert row["area_source"] == "capacity_derived"
    assert row["footprint_m2"] == 200 * AFAD_M2_PER_PERSON  # 300 m²


def test_point_without_capacity_or_overlay_stays_empty():
    """
    En kritik invariant: Point için ne overlay ne capacity varsa alan
    UYDURULMAZ. footprint_m2 NaN, area_source "" kalır — Excel'de boş
    hücre olarak gider. Bir önceki sürümdeki 500 m² default KALDIRILDI
    (kullanıcı kararı: gerçekçi değildi).
    """
    out = add_footprint_area(_mixed_gdf())
    row = out[out["osm_id"] == "pt_bare"].iloc[0]
    assert pd.isna(row["footprint_m2"]), (
        "REGRESYON: Point için default alan uydurulmuş. Kanıt yoksa NaN kalmalı."
    )
    assert row["area_source"] == "", (
        "area_source de boş olmalı — 'point_default' gibi bir etiket geri gelmiş"
    )


def test_point_fallback_can_be_disabled():
    """point_fallback=False → capacity/overlay hiç denenmez, Point'ler NaN."""
    out = add_footprint_area(_mixed_gdf(), point_fallback=False)
    bare = out[out["osm_id"] == "pt_bare"].iloc[0]
    cap  = out[out["osm_id"] == "pt_capacity"].iloc[0]
    assert pd.isna(bare["footprint_m2"])
    assert bare["area_source"] == ""
    assert pd.isna(cap["footprint_m2"]), (
        "point_fallback=False iken capacity_derived de çalışmamalı"
    )


def test_point_inside_polygon_inherits_real_area():
    """
    polygon_overlay tier: Point aynı fetch içindeki poligonun içine
    düşüyorsa, gerçek poligon alanı miras alınır (tahmin değil).
    Bu, "Ahmet Taner Kışlalı Parkı" gibi isimli Point'lerin gerçek
    park poligonunun üstüne yerleştirilmiş label node olduğu senaryoyu
    yakalar.
    """
    # Büyük bir park poligonu, içinde bir label Point
    park_polygon = Polygon([
        (29.00, 41.00), (29.02, 41.00), (29.02, 41.02), (29.00, 41.02)
    ])
    label_point = Point(29.01, 41.01)  # poligonun tam ortası

    gdf = gpd.GeoDataFrame(
        {
            "osm_id":   ["park_polygon", "park_label_point"],
            "name":     ["Ahmet Taner Kışlalı Parkı", "Ahmet Taner Kışlalı Parkı"],
            "geometry": [park_polygon, label_point],
        },
        crs="EPSG:4326",
    )
    out = add_footprint_area(gdf).set_index("osm_id")

    # Poligon kendisi ölçülmüş
    assert out.loc["park_polygon", "area_source"] == "measured"
    poly_area = out.loc["park_polygon", "footprint_m2"]
    assert poly_area > 0

    # Label Point, aynı poligonu miras almalı (overlay tier)
    assert out.loc["park_label_point", "area_source"] == "polygon_overlay"
    assert out.loc["park_label_point", "footprint_m2"] == poly_area, (
        "Label Point içinde olduğu poligonun ALANINI miras almalı — "
        "default 500 m²'ye düşmemeli"
    )


def test_polygon_overlay_takes_precedence_over_capacity():
    """Point içinde capacity tag olsa bile, poligon overlay varsa o öncelikli."""
    park = Polygon([(29.0, 41.0), (29.01, 41.0), (29.01, 41.01), (29.0, 41.01)])
    point_in_park = Point(29.005, 41.005)

    gdf = gpd.GeoDataFrame(
        {
            "osm_id":   ["big_park", "marker_with_capacity"],
            "capacity": [None, 50],  # 50 kişi × 1.5 = 75 m² ama park çok daha büyük
            "geometry": [park, point_in_park],
        },
        crs="EPSG:4326",
    )
    out = add_footprint_area(gdf).set_index("osm_id")
    row = out.loc["marker_with_capacity"]
    assert row["area_source"] == "polygon_overlay", (
        "Poligon overlay capacity'yi override etmeli (gerçek > tahmin)"
    )
    # Gerçek park alanı >> capacity × 1.5 (50 × 1.5 = 75 m²)
    assert row["footprint_m2"] > 75


def test_external_overlay_polygons_layer():
    """Overlay poligonları dışarıdan (ayrı bir katman) verilebilir."""
    fetched = gpd.GeoDataFrame(
        {
            "osm_id":   ["orphan_point"],
            "geometry": [Point(29.01, 41.01)],
        },
        crs="EPSG:4326",
    )
    parks_layer = gpd.GeoDataFrame(
        {
            "park_id":  ["external_park_1"],
            "geometry": [Polygon([(29.0, 41.0), (29.02, 41.0), (29.02, 41.02), (29.0, 41.02)])],
        },
        crs="EPSG:4326",
    )
    out = add_footprint_area(fetched, overlay_polygons=parks_layer)
    row = out.iloc[0]
    assert row["area_source"] == "polygon_overlay"
    assert row["footprint_m2"] > 0


def test_kadikoy_two_point_assembly_scenario_without_overlay_stays_empty():
    """
    Kullanıcının Excel çıktısındaki Kadıköy senaryosu: iki Point kaydı
    için tek başlarına (çevreleyen poligon OLMADAN ve capacity OLMADAN)
    alan ÜRETİLMEZ. footprint_m2 NaN, area_source "" kalır.

    Gerçekte her iki Point de aynı fetch'teki park poligonlarıyla overlay
    üzerinden alan alıyor (kullanıcı 2342,8 / 3879,9 m²'lik gerçek değerleri
    gördü). Bu test ise izole Point'lerin ALT DAVRANIŞINI kilitliyor:
    bilinmiyorsa boş bırak.
    """
    gdf = gpd.GeoDataFrame(
        {
            "osm_id":   ["5253587679", "13724139159"],
            "name":     ["tanzim", "Ahmet Taner Kışlalı Parkı"],
            "geometry": [Point(29.0608, 40.9877), Point(29.0923, 40.9715)],
        },
        crs="EPSG:4326",
    )
    out = add_footprint_area(gdf)
    assert out["footprint_m2"].isna().all(), (
        "Çevreleyen poligon yoksa alan UYDURULMAMALI — 500 m² default geri gelmiş"
    )
    assert (out["area_source"] == "").all()
