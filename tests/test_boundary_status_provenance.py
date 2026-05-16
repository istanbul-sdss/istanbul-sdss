"""
Regresyon: assign_neighbourhoods her kayıt için boundary_status üretir;
analist Excel/CSV'de hangi kayıtların gerçekten ilçe içinde, hangilerinin
nearest-fallback ile doldurulduğunu görür.

Kullanıcı sorusu: "Şişli'de 10 bina sınır içinde değilmiş, bunlar başka
ilçelerde mi?" — evet, muhtemelen komşu ilçelerden Overpass sızıntısı.
Sessizce silmek yerine boundary_status='ilçe_dışı' olarak işaretliyoruz.

Statü değerleri:
  • "ilçe_içi"   → strict within (mahalle poligonunun strict iç bölgesi)
  • "sınır_üstü" → intersects (paylaşılan kenarda)
  • "ilçe_dışı"  → nearest fallback (gerçekte sınır dışında)
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon

from src.services.spatial_service import assign_neighbourhoods


def _two_neighbourhoods():
    """Yan yana iki mahalle paylaşılan kenar x=29.05'te."""
    a = Polygon([(29.00, 41.00), (29.05, 41.00), (29.05, 41.05), (29.00, 41.05)])
    b = Polygon([(29.05, 41.00), (29.10, 41.00), (29.10, 41.05), (29.05, 41.05)])
    return gpd.GeoDataFrame(
        {"neighbourhood_name": ["Mah_A", "Mah_B"], "geometry": [a, b]},
        crs="EPSG:4326",
    )


def _gdf(points, ids):
    gdf = gpd.GeoDataFrame({"osm_id": ids, "geometry": points}, crs="EPSG:4326")
    gdf["rep_point"] = gdf.geometry
    return gdf


def test_boundary_status_inside_for_strict_within():
    """Mahalle poligonunun ortasındaki Point ilçe_içi."""
    g = _gdf([Point(29.02, 41.02)], ["inside"])
    out = assign_neighbourhoods(g, _two_neighbourhoods())
    assert out.iloc[0]["neighbourhood"] == "Mah_A"
    assert out.iloc[0]["boundary_status"] == "ilçe_içi"


def test_boundary_status_on_boundary_for_shared_edge():
    """İki mahallenin paylaşılan kenarındaki Point sınır_üstü."""
    g = _gdf([Point(29.05, 41.025)], ["edge"])
    out = assign_neighbourhoods(g, _two_neighbourhoods())
    assert pd.notna(out.iloc[0]["neighbourhood"])
    assert out.iloc[0]["boundary_status"] == "sınır_üstü", (
        f"Paylaşılan kenardaki Point boundary_status='sınır_üstü' olmalı, "
        f"gelen: {out.iloc[0]['boundary_status']!r}"
    )


def test_boundary_status_outside_for_nearest_fallback():
    """
    Mahalle birleşiminin DIŞINDAKİ Point boundary_status='ilçe_dışı'
    olmalı — kullanıcı bu kaydın aslında komşu ilçeye ait olduğunu
    görsün, "ilçe_içi" sanmasın.
    """
    g = _gdf([Point(29.20, 41.025)], ["far_outside"])  # mahallelerin çok dışında
    out = assign_neighbourhoods(g, _two_neighbourhoods())
    assert pd.notna(out.iloc[0]["neighbourhood"]), (
        "REGRESYON: nearest fallback hâlâ boş bırakıyor"
    )
    assert out.iloc[0]["boundary_status"] == "ilçe_dışı", (
        f"REGRESYON: ilçe sınırı dışındaki kayıt 'ilçe_dışı' olarak "
        f"işaretlenmedi. Gelen: {out.iloc[0]['boundary_status']!r}. "
        f"Kullanıcı bu kaydı sahte 'ilçe_içi' sanır → karar destek bozulur."
    )


def test_boundary_status_mixed_set_correctly_assigned():
    """3 farklı tier için tek seferde doğru status üretimi."""
    g = _gdf(
        [
            Point(29.02, 41.02),    # inside Mah_A
            Point(29.05, 41.025),   # paylaşılan kenar
            Point(29.20, 41.025),   # uzak dış
        ],
        ["inside", "edge", "outside"],
    )
    out = assign_neighbourhoods(g, _two_neighbourhoods()).set_index("osm_id")
    assert out.loc["inside",  "boundary_status"] == "ilçe_içi"
    assert out.loc["edge",    "boundary_status"] == "sınır_üstü"
    assert out.loc["outside", "boundary_status"] == "ilçe_dışı"


def test_boundary_status_in_export_columns():
    """boundary_status COMMON_OUTPUT_COLUMNS içinde (export'a otomatik girer)."""
    from src.config.output_columns import COMMON_OUTPUT_COLUMNS
    assert "boundary_status" in COMMON_OUTPUT_COLUMNS, (
        "REGRESYON: boundary_status export şemasında yok — Excel/CSV'de "
        "kullanıcıya gösterilmeyecek."
    )


def test_boundary_status_translates_to_english():
    """to_english() Sınır Durumu → Boundary Status + değer çevirisi."""
    from components.translations import to_english
    df = pd.DataFrame({
        "Sınır Durumu": ["ilçe_içi", "sınır_üstü", "ilçe_dışı"],
        "ad":           ["a", "b", "c"],
    })
    en = to_english(df)
    assert "Boundary Status" in en.columns, (
        f"REGRESYON: Sınır Durumu kolonu çevrilmedi. EN cols: {list(en.columns)}"
    )
    assert en["Boundary Status"].tolist() == [
        "Inside district", "On boundary", "Outside district",
    ], f"Boundary Status değerleri çevrilmedi: {en['Boundary Status'].tolist()}"


def test_empty_neighbourhood_input_returns_empty_status_column():
    """Mahalle gdf boşsa boundary_status kolonu yine olmalı (downstream güvenli)."""
    g = _gdf([Point(29.0, 41.0)], ["x"])
    empty_nbhd = gpd.GeoDataFrame(
        {"neighbourhood_name": [], "geometry": []}, crs="EPSG:4326"
    )
    out = assign_neighbourhoods(g, empty_nbhd)
    assert "boundary_status" in out.columns
