"""
Regresyon: Point geometrili kayıtlar (toplanma noktaları, park label'ları) için
polygon_overlay tier'ı EN KÜÇÜK (en spesifik) içerleyen poligonu seçmeli — en
büyüğünü değil.

Kullanıcı bulgusu: "Nokta olarak işaretlenen toplanma alanı ve parkların
alanları yanlış geliyor". Sebep: önceki implementasyon
`sort_values('__area_m2__', ascending=False).head(1)` ile EN BÜYÜK overlay
poligonunu seçiyordu. Bir park Point'i hem küçük park poligonu hem de daha
büyük bir landuse / yeşil alan / ilçe sınırı içine düşerse, alan ŞİŞİYOR.

Doğru mantık: en küçük overlay poligonu = en spesifik referans = en doğru
footprint tahmini. Park label point → kendi park poligonunu miras alır,
çevreleyen büyük "yeşil alan" landuse'ünü değil.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon

from src.services.spatial_service import add_footprint_area


def test_point_inside_nested_polygons_picks_smallest():
    """
    İki iç içe poligon: küçük park + onu kapsayan büyük landuse.
    Park label Point'i KÜÇÜK olanı miras almalı (gerçek footprint).
    """
    big_landuse = Polygon([
        (29.00, 41.00), (29.10, 41.00), (29.10, 41.10), (29.00, 41.10)
    ])  # ~100 km²
    small_park = Polygon([
        (29.04, 41.04), (29.06, 41.04), (29.06, 41.06), (29.04, 41.06)
    ])  # ~4 km²
    label_pt = Point(29.05, 41.05)  # her iki poligonun içinde

    gdf = gpd.GeoDataFrame(
        {
            "osm_id":   ["big_landuse", "small_park", "park_label_point"],
            "name":     ["Yeşil Alan", "Maçka Parkı", "Maçka Parkı"],
            "geometry": [big_landuse, small_park, label_pt],
        },
        crs="EPSG:4326",
    )
    out = add_footprint_area(gdf).set_index("osm_id")

    big_area   = out.loc["big_landuse",       "footprint_m2"]
    small_area = out.loc["small_park",        "footprint_m2"]
    pt_area    = out.loc["park_label_point",  "footprint_m2"]

    assert big_area > small_area > 0, "fixture sanity"
    assert out.loc["park_label_point", "area_source"] == "polygon_overlay"
    assert pt_area == pytest.approx(small_area, rel=1e-6), (
        f"REGRESYON: Point en BÜYÜK içerleyen poligonu miras almış "
        f"(pt={pt_area:.0f}, small={small_area:.0f}, big={big_area:.0f}). "
        f"En spesifik (en küçük) seçilmeliydi — kullanıcı şikâyeti: 'park "
        f"alanları yanlış geliyor'."
    )


def test_assembly_point_inside_park_takes_park_not_district():
    """
    AFAD toplanma Point'i bir park poligonu içinde + park bir ilçe sınırı
    içinde. Toplanma noktası PARK alanını miras almalı, ilçeyi değil.
    """
    district  = Polygon([(28.9, 40.9), (29.2, 40.9), (29.2, 41.1), (28.9, 41.1)])  # ~600 km²
    park      = Polygon([(29.05, 40.97), (29.07, 40.97), (29.07, 40.99), (29.05, 40.99)])
    assembly  = Point(29.06, 40.98)

    gdf = gpd.GeoDataFrame(
        {
            "osm_id":   ["kadikoy", "park", "afad_pt"],
            "geometry": [district, park, assembly],
        },
        crs="EPSG:4326",
    )
    out = add_footprint_area(gdf).set_index("osm_id")

    park_area = out.loc["park", "footprint_m2"]
    pt_area   = out.loc["afad_pt", "footprint_m2"]

    assert pt_area == pytest.approx(park_area, rel=1e-6), (
        f"REGRESYON: Toplanma noktası ilçe alanını miras almış "
        f"(pt={pt_area:.0f}, park={park_area:.0f}). Park (en küçük spesifik) "
        f"olmalıydı — Excel'e yüz binlerce m² yazılır, AFAD planında felaket."
    )


def test_point_with_single_overlay_unchanged():
    """Tek overlay poligonu varsa davranış aynı kalır (regresyon koruması)."""
    park = Polygon([(29.0, 41.0), (29.01, 41.0), (29.01, 41.01), (29.0, 41.01)])
    label = Point(29.005, 41.005)

    gdf = gpd.GeoDataFrame(
        {"osm_id": ["park", "lbl"], "geometry": [park, label]},
        crs="EPSG:4326",
    )
    out = add_footprint_area(gdf).set_index("osm_id")
    assert out.loc["lbl", "area_source"] == "polygon_overlay"
    assert out.loc["lbl", "footprint_m2"] == out.loc["park", "footprint_m2"]


def test_three_nested_polygons_picks_smallest():
    """3 iç içe poligon: en küçüğü kazanır."""
    huge   = Polygon([(29.00, 41.00), (29.10, 41.00), (29.10, 41.10), (29.00, 41.10)])
    medium = Polygon([(29.03, 41.03), (29.07, 41.03), (29.07, 41.07), (29.03, 41.07)])
    small  = Polygon([(29.045, 41.045), (29.055, 41.045), (29.055, 41.055), (29.045, 41.055)])
    pt     = Point(29.05, 41.05)

    gdf = gpd.GeoDataFrame(
        {
            "osm_id":   ["huge", "medium", "small", "pt"],
            "geometry": [huge, medium, small, pt],
        },
        crs="EPSG:4326",
    )
    out = add_footprint_area(gdf).set_index("osm_id")
    expected = out.loc["small", "footprint_m2"]
    assert out.loc["pt", "footprint_m2"] == pytest.approx(expected, rel=1e-6)
