"""
Regresyon (P2.2): _to_point_gdf concave/MultiPolygon'da nokta polygon
İÇİNDE üretmeli ve UTM projeksiyonunda hesaplamalı.

Audit bulgusu: Önceki versiyon WGS84'te `g.centroid` kullanıyordu;
concave polygon'da centroid polygon dışına düşebiliyor → OD snap noktası
gerçek bina/alan girişini temsil etmiyor + GeoPandas geographic CRS uyarısı.
"""
from __future__ import annotations

import warnings

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, Point, Polygon

from src.optimizer.data_loader import _to_point_gdf


def _u_polygon():
    """
    Belirgin C/donut-benzeri concave polygon — centroid orta deliğe düşer.
    L-şeklinin aksine C-şeklinin centroid'i geometrinin DIŞINDA kalır.
    """
    # Büyük dış halka eksi içeride bir oyuk:
    return Polygon(
        # Dış halka (büyük dikdörtgen)
        [(29.000, 41.000), (29.020, 41.000), (29.020, 41.020),
         (29.000, 41.020), (29.000, 41.000)],
        # İç delik (büyük oyuk — merkez bölge boşaltılır)
        [[(29.004, 41.004), (29.016, 41.004),
          (29.016, 41.016), (29.004, 41.016), (29.004, 41.004)]],
    )


def test_concave_polygon_point_lies_inside():
    """U-polygon'un temsili noktası polygon içinde olmalı."""
    poly = _u_polygon()
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[poly], crs="EPSG:4326")
    out = _to_point_gdf(gdf)
    pt = out.geometry.iloc[0]
    assert poly.contains(pt) or poly.touches(pt), (
        f"REGRESYON: U-polygon'un temsili noktası polygon DIŞINA düştü "
        f"({pt.wkt}). representative_point yerine centroid kullanılmış olabilir."
    )


def test_centroid_was_outside_polygon_sanity():
    """
    Test fixture sanity: bu polygon'un WGS84 centroid'i gerçekten polygon
    DIŞINDA mı? Eğer dışında değilse test fixture etkisiz.
    """
    poly = _u_polygon()
    c = poly.centroid
    assert not poly.contains(c), (
        "Fixture beklenmedik: U-polygon centroid'i polygon içinde. "
        "Daha agresif concave şekil seçilmeli."
    )


def test_multipolygon_handled():
    """MultiPolygon için de polygon parçalarından birinin içinde nokta üretmeli."""
    p1 = Polygon([(29.0, 41.0), (29.001, 41.0), (29.001, 41.001), (29.0, 41.001)])
    p2 = Polygon([(29.01, 41.01), (29.011, 41.01), (29.011, 41.011), (29.01, 41.011)])
    mp = MultiPolygon([p1, p2])
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[mp], crs="EPSG:4326")
    out = _to_point_gdf(gdf)
    pt = out.geometry.iloc[0]
    assert mp.contains(pt) or mp.touches(pt)


def test_point_geometry_unchanged():
    """Zaten Point olan kayıtlara dokunmamalı."""
    gdf = gpd.GeoDataFrame(
        {"id": [1, 2]},
        geometry=[Point(29.0, 41.0), Point(29.1, 41.1)],
        crs="EPSG:4326",
    )
    out = _to_point_gdf(gdf)
    assert out.geometry.iloc[0].equals(Point(29.0, 41.0))
    assert out.geometry.iloc[1].equals(Point(29.1, 41.1))


def test_no_geographic_crs_warning_on_polygon():
    """
    Önceden GeoPandas 'centroid in geographic CRS' uyarısı veriyordu.
    Yeni implementasyon UTM'de hesapladığı için uyarı çıkmamalı.
    """
    poly = _u_polygon()
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[poly], crs="EPSG:4326")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        _to_point_gdf(gdf)
    geo_warnings = [x for x in w if "geographic" in str(x.message).lower()]
    assert not geo_warnings, (
        f"REGRESYON: GeoPandas geographic CRS uyarısı hâlâ üretiliyor: "
        f"{[str(x.message) for x in geo_warnings]}"
    )
