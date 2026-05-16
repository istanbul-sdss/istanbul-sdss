"""
Regresyon (P1.2 — satır bazlı): Alan kolonu mevcut ama bazı satırları NaN/0
ise, polygon geometrisi olan satırlar için yine de gerçek alan hesaplanmalı.

Önceki düzeltme yarım kalmıştı: _ensure_polygon_footprint_column herhangi
bir alan kolonu bulunca erken `return` yapıyordu. Sonuç: kolon var, bazı
satırlar boş → boş satırlar 1000 m² fallback'ine düşüyor (toplanma) ya da
0'a düşüyor (bina nüfus → weight=1).
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon

from src.optimizer.data_loader import _prepare_binalar, _prepare_toplanma


def _mixed_polygon_with_partial_area_column():
    """3 polygon: 1 değerli, 1 NaN, 1 sıfır."""
    polys = [
        Polygon([(29.000, 41.000), (29.000111, 41.000),
                 (29.000111, 41.0001), (29.000, 41.0001)]),
        Polygon([(29.001, 41.001), (29.0015, 41.001),
                 (29.0015, 41.0015), (29.001, 41.0015)]),
        Polygon([(29.002, 41.002), (29.0025, 41.002),
                 (29.0025, 41.0025), (29.002, 41.0025)]),
    ]
    return gpd.GeoDataFrame(
        {
            "name":      ["Var",  "Boş", "Sıfır"],
            "Alan (m²)": [123.0,  None,  0.0],
            "geometry":  polys,
        },
        crs="EPSG:4326",
    )


def test_toplanma_partial_area_column_uses_polygon_for_missing():
    """
    Toplanma alanı: kolon var ama bazı satırlar NaN/0 → o satırlar polygon
    geometrisinden hesaplanmalı, 1000 m² fallback'ine DÜŞMEMELİ.
    """
    out = _prepare_toplanma(_mixed_polygon_with_partial_area_column())
    assert len(out) == 3, "tüm satırlar korunmalı"

    # Kullanıcı verisi olan satır (123 m²) korunmalı
    var = out[out["ad"] == "Var"].iloc[0]
    assert var["area_m2"] == pytest.approx(123.0)

    # Boş ve sıfır olan satırlar polygon'dan hesaplanmalı, 1000 olmamalı
    bos = out[out["ad"] == "Boş"].iloc[0]
    sifir = out[out["ad"] == "Sıfır"].iloc[0]
    assert bos["area_m2"] != 1000.0, (
        f"REGRESYON: NaN olan satır 1000 m² fallback'e düştü: {bos['area_m2']}. "
        f"Polygon geometrisi var, gerçek alan kullanılmalıydı."
    )
    assert sifir["area_m2"] != 1000.0, (
        f"REGRESYON: 0 olan satır 1000 m² fallback'e düştü: {sifir['area_m2']}. "
        f"Polygon geometrisi var, gerçek alan kullanılmalıydı."
    )
    assert bos["area_m2"] > 0
    assert sifir["area_m2"] > 0


def test_toplanma_area_source_distinguishes_user_vs_geometry():
    """
    area_source provenance: 'measured' (kullanıcı) vs 'geometry_measured'
    (polygon'dan türetilmiş) ayrımı opsiyonel ama tercih edilir. En azından
    kullanıcı değeri olan satır 'estimated' işaretlenmemeli.
    """
    out = _prepare_toplanma(_mixed_polygon_with_partial_area_column())
    sources = dict(zip(out["ad"], out["area_source"]))
    # Kullanıcı verisi olan satır 'estimated' işaretlenmemeli
    assert sources["Var"] != "estimated", (
        f"Kullanıcı değeri olan satır 'estimated' olarak işaretlendi: "
        f"{sources['Var']}"
    )
    # Boş satır artık polygon'dan geldiği için 'estimated' olmamalı
    assert sources["Boş"] != "estimated", (
        f"Polygon'dan hesaplanan satır hâlâ 'estimated' işaretli: "
        f"{sources['Boş']} — provenance per-row ayrılmalı."
    )


def test_bina_partial_area_column_uses_polygon_for_missing():
    """
    Bina: alan kolonu var ama bazı satırlar NaN → polygon'dan hesapla,
    weight=1 (estimate_population min cap) sonucundan kaçın.
    """
    polys = [
        Polygon([(29.000, 41.000), (29.000222, 41.000),
                 (29.000222, 41.0002), (29.000, 41.0002)]),  # ~22×22 m
        Polygon([(29.001, 41.001), (29.001222, 41.001),
                 (29.001222, 41.0012), (29.001, 41.0012)]),
    ]
    gdf = gpd.GeoDataFrame(
        {
            "name":         ["Bina A",  "Bina B"],
            "Alan (m²)":    [200.0,     None],
            "Kat Sayısı":   [3,         5],
            "geometry":     polys,
        },
        crs="EPSG:4326",
    )
    out = _prepare_binalar(gdf)
    a = out[out["name"] == "Bina A"].iloc[0]
    b = out[out["name"] == "Bina B"].iloc[0]
    assert a["alan_m2"] == pytest.approx(200.0)
    assert b["alan_m2"] > 0, (
        f"REGRESYON: NaN alan polygon'dan hesaplanmadı; weight=1 düşmüş olabilir. "
        f"alan_m2={b['alan_m2']}, weight={b['weight']}"
    )
    assert b["weight"] > 1


def test_full_polygon_no_area_column_still_works():
    """Önceki testin değişmemesi için: hiç kolon yoksa hâlâ çalışıyor."""
    poly = Polygon([(29.0, 41.0), (29.0001, 41.0), (29.0001, 41.0001), (29.0, 41.0001)])
    gdf = gpd.GeoDataFrame({"name": ["X"], "geometry": [poly]}, crs="EPSG:4326")
    out = _prepare_toplanma(gdf)
    assert out.iloc[0]["area_m2"] > 0
    assert out.iloc[0]["area_m2"] != 1000.0


def test_point_geometry_with_missing_area_falls_back_to_default():
    """
    Point için polygon alanı hesaplanamaz. Kolon var ve NaN ise 1000
    fallback'i hâlâ devreye girer (mantıklı davranış — Point için alan yok).
    """
    gdf = gpd.GeoDataFrame(
        {
            "name":      ["Nokta"],
            "Alan (m²)": [None],
            "geometry":  [Point(29.0, 41.0)],
        },
        crs="EPSG:4326",
    )
    out = _prepare_toplanma(gdf)
    assert out.iloc[0]["area_m2"] == 1000.0  # Point için fallback geçerli
    assert out.iloc[0]["area_source"] == "estimated"
