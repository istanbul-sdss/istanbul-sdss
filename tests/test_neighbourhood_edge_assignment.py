"""
Regresyon: İlçe sınırına ÇOK yakın / sınırın üstündeki kayıtlara da en
mantıklı mahalle atanmalı — boş kalmamalı.

Kullanıcı bulgusu: "Kadıköy'den aldığımda mahalle atanmamış 2 alan geldi,
muhtemelen ilçe dışında ya da kesişim noktasındaydı."

Sebep: `assign_neighbourhoods` `predicate='within'` kullanıyor. Bir Point tam
mahalle sınırı üzerindeyse hiçbir poligonun "within"i olmaz (within strict
interior). Kayıt gelir ama mahallesi boş kalır.

Çözüm: 'within' boş dönerse 'intersects' (sınırı dahil eder), o da boşsa
en yakın mahalle (nearest) ile doldur. Tüm yollar başarısızsa
boş bırakmak yerine net bir log; ama varsayılan davranış mutlaka bir
mahalle atanması olsun.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, Polygon

from src.services.spatial_service import assign_neighbourhoods


def _two_neighbourhoods() -> gpd.GeoDataFrame:
    """Yan yana iki mahalle: Mah_A (sol) ve Mah_B (sağ), x=29.05'te paylaşılan kenar."""
    mah_a = Polygon([(29.00, 41.00), (29.05, 41.00), (29.05, 41.05), (29.00, 41.05)])
    mah_b = Polygon([(29.05, 41.00), (29.10, 41.00), (29.10, 41.05), (29.05, 41.05)])
    return gpd.GeoDataFrame(
        {"neighbourhood_name": ["Mah_A", "Mah_B"], "geometry": [mah_a, mah_b]},
        crs="EPSG:4326",
    )


def _gdf_with_rep_points(points: list[Point], ids: list[str]) -> gpd.GeoDataFrame:
    """assign_neighbourhoods rep_point bekler — onu set eder."""
    gdf = gpd.GeoDataFrame(
        {"osm_id": ids, "geometry": points},
        crs="EPSG:4326",
    )
    gdf["rep_point"] = gdf.geometry
    return gdf


def test_point_inside_polygon_gets_correct_neighbourhood():
    """Sanity: net iç noktası doğru mahalle alır."""
    g = _gdf_with_rep_points(
        [Point(29.02, 41.02), Point(29.08, 41.02)],
        ["pt_in_a", "pt_in_b"],
    )
    out = assign_neighbourhoods(g, _two_neighbourhoods())
    assignments = dict(zip(out["osm_id"], out["neighbourhood"]))
    assert assignments["pt_in_a"] == "Mah_A"
    assert assignments["pt_in_b"] == "Mah_B"


def test_point_exactly_on_shared_edge_gets_some_neighbourhood():
    """
    Tam paylaşılan kenarda olan Point — hangisi olursa olsun bir mahalle
    atanmalı (boş kalmamalı). Mevcut davranış 'within' yüzünden BOŞ.
    """
    edge_pt = Point(29.05, 41.025)  # Mah_A ve Mah_B kenarı
    g = _gdf_with_rep_points([edge_pt], ["edge_pt"])
    out = assign_neighbourhoods(g, _two_neighbourhoods())
    assigned = out.iloc[0]["neighbourhood"]
    assert pd.notna(assigned) and assigned in ("Mah_A", "Mah_B"), (
        f"REGRESYON: paylaşılan kenardaki Point'e mahalle atanmadı "
        f"(neighbourhood={assigned!r}). 'within' yetmediğinde fallback "
        f"(intersects → nearest) çalışmalı."
    )


def test_point_just_outside_boundary_gets_nearest_neighbourhood():
    """
    Mahalle dışında ama çok yakın Point — en yakın mahalle ile doldurulur.
    Kullanıcının "ilçe dışındaydı muhtemelen" senaryosu: kayıt çekildi (OSM
    bbox sızması), mahalle birleşiminin DIŞINA düştü, ama 50 m ötede mahalle var.
    """
    just_outside = Point(29.105, 41.025)  # Mah_B'nin sağ kenarının ~440 m sağında
    g = _gdf_with_rep_points([just_outside], ["edge_outside"])
    out = assign_neighbourhoods(g, _two_neighbourhoods())
    assigned = out.iloc[0]["neighbourhood"]
    assert pd.notna(assigned), (
        "REGRESYON: ilçe sınırına yakın ama dışındaki kayıt mahallesiz. "
        "Nearest fallback çalışmıyor."
    )
    assert assigned == "Mah_B", (
        f"En yakın mahalle Mah_B olmalıydı, atanan: {assigned!r}"
    )


def test_far_outside_point_still_assigned_or_logged_explicitly():
    """
    Çok uzak bir Point bile (örn. başka bir şehir) en yakın mahalle ile
    doldurulur — sessiz NaN bırakmaktan iyidir. Kullanıcı sonra fark eder
    ve siler. Testin amacı: davranış tutarlı; rastgele NaN olmasın.
    """
    far_pt = Point(30.0, 39.0)  # Eskişehir civarı
    g = _gdf_with_rep_points([far_pt], ["far_pt"])
    out = assign_neighbourhoods(g, _two_neighbourhoods())
    assigned = out.iloc[0]["neighbourhood"]
    assert pd.notna(assigned), (
        "Uzak Point bile nearest fallback ile doldurulmalı (sessiz NaN yok)"
    )
