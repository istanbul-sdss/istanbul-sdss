"""
Regresyon (P1.2): GeoJSON polygon yüklendiğinde gerçek alan hesaplanmalı.

Audit bulgusu: load_from_geojson() → _prepare_binalar()/_prepare_toplanma()
ÖNCE _to_point_gdf() çağırarak polygon'u centroid'e çeviriyordu, sonra
_extract_alan_m2() sadece kolondan okuyordu. GeoJSON'da polygon var ama "Alan
(m²)" / "area_m2" kolonu yoksa:
  • bina nüfusu 0 m² × 0 = 0 → weight=1 (estimate_population min cap)
  • toplanma kapasitesi → 1000 m² varsayım fallback'ine düşüyordu

Düzeltme: _to_point_gdf'den ÖNCE polygon footprint'i UTM'de hesaplanır ve
"footprint_m2" kolonuna yazılır. Sonra extract zincirinde bu kolon yakalanır.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon

from src.optimizer.data_loader import _prepare_binalar, _prepare_toplanma


def _polygon_gdf_no_area_column() -> gpd.GeoDataFrame:
    """Polygon GeoJSON, ama alan kolonu YOK (kullanıcı senaryosu)."""
    # Yaklaşık 10×10 m² (İstanbul UTM'de) — küçük bir bina
    poly = Polygon([
        (29.000, 41.000),
        (29.000111, 41.000),    # ~9.4 m doğu
        (29.000111, 41.0001),   # ~11.1 m kuzey
        (29.000, 41.0001),
    ])
    bigger = Polygon([
        (29.001, 41.001),
        (29.0015, 41.001),       # ~42 m doğu
        (29.0015, 41.0015),      # ~55 m kuzey
        (29.001, 41.0015),
    ])
    return gpd.GeoDataFrame(
        {
            "name":     ["Küçük Bina", "Toplanma Alanı 1"],
            "geometry": [poly, bigger],
        },
        crs="EPSG:4326",
    )


def test_polygon_building_area_computed_from_geometry():
    """Polygon bina, alan kolonu yoksa GERÇEK polygon alanı kullanılmalı."""
    out = _prepare_binalar(_polygon_gdf_no_area_column())
    assert len(out) == 2
    # Küçük polygon ~100 m², bigger ~2300 m² civarı (UTM)
    assert (out["alan_m2"] > 0).all(), (
        "REGRESYON: polygon GeoJSON yüklenince alan_m2=0 kalmış. "
        "_to_point_gdf'den önce footprint hesaplanmalı."
    )
    # Küçük < büyük (sıralama korunur)
    assert out.iloc[0]["alan_m2"] < out.iloc[1]["alan_m2"]


def test_polygon_assembly_area_uses_real_area_not_default():
    """Toplanma alanı polygon'u → 1000 m² varsayım fallback'ine DÜŞMEMELİ."""
    out = _prepare_toplanma(_polygon_gdf_no_area_column())
    assert len(out) == 2
    # Hiçbiri 1000 default'una düşmemiş olmalı (gerçek alanlar farklı boyutta)
    assert (out["area_m2"] != 1000.0).all(), (
        f"REGRESYON: polygon toplanma alanı {out['area_m2'].tolist()} — "
        f"1000 m² varsayımına düştü. Gerçek polygon alanı kullanılmalıydı."
    )
    # area_source kolonu varsa "measured" veya "geometry_measured" olmalı.
    # Satır-bazlı provenance düzeltmesinden sonra: kullanıcı kolonu yokken
    # geometriden gelen polygon alanı 'geometry_measured' işaretlenir
    # (bkz. tests/test_polygon_footprint_per_row.py).
    if "area_source" in out.columns:
        assert out["area_source"].isin(["measured", "geometry_measured"]).all(), (
            f"area_source: {out['area_source'].tolist()} — polygon alanı "
            f"hesaplandığında 'measured' veya 'geometry_measured' olmalı."
        )


def test_existing_area_column_takes_precedence_over_geometry():
    """
    Veride zaten 'Alan (m²)' kolonu varsa onu kullan (kullanıcı manuel girmiş
    olabilir). Geometriden hesaplama sadece kolon yoksa devreye girer.
    """
    poly = Polygon([(29.0, 41.0), (29.001, 41.0), (29.001, 41.001), (29.0, 41.001)])
    gdf = gpd.GeoDataFrame(
        {
            "name":      ["Bina"],
            "Alan (m²)": [123.0],
            "geometry":  [poly],
        },
        crs="EPSG:4326",
    )
    out = _prepare_binalar(gdf)
    assert out.iloc[0]["alan_m2"] == pytest.approx(123.0), (
        f"Mevcut 'Alan (m²)' kolonu override edildi: {out.iloc[0]['alan_m2']}. "
        f"Kullanıcı verisi öncelikli olmalı."
    )


def test_point_geometry_unchanged_uses_column_or_default():
    """Point geometry için davranış değişmemeli (regresyon koruması)."""
    gdf = gpd.GeoDataFrame(
        {
            "name":     ["Nokta"],
            "geometry": [Point(29.0, 41.0)],
        },
        crs="EPSG:4326",
    )
    # Bina: alan kolonu yok → 0 (eskisi gibi, çünkü Point için footprint çıkarılamaz)
    out_b = _prepare_binalar(gdf)
    assert out_b.iloc[0]["alan_m2"] == 0.0
    # Toplanma: 1000 default fallback (Point için biliyoruz, alan tahmini imkansız)
    out_t = _prepare_toplanma(gdf)
    assert out_t.iloc[0]["area_m2"] == 1000.0


def test_polygon_population_estimate_is_realistic():
    """
    P1.2'nin asıl etkisi: polygon → gerçek alan → gerçek nüfus tahmini.
    Bir 100 m² × 4 kat bina → ~16 kişi olmalı (TÜİK ortalama 6.25 m²/kişi).
    Önceden alan=0 yüzünden weight=1 (min cap) çıkıyordu.
    """
    poly = Polygon([
        (29.000, 41.000),
        (29.000111, 41.000),
        (29.000111, 41.0001),
        (29.000, 41.0001),
    ])
    gdf = gpd.GeoDataFrame(
        {
            "name":             ["Apartman"],
            "Kat Sayısı":       [4],
            "geometry":         [poly],
        },
        crs="EPSG:4326",
    )
    out = _prepare_binalar(gdf)
    weight = out.iloc[0]["weight"]
    assert weight > 1, (
        f"REGRESYON: polygon bina için nüfus tahmini hâlâ 1 (={weight}). "
        f"Polygon alanı hesaplanmadığı için estimate_population min'e düşmüş."
    )
