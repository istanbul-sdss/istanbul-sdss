"""
Regresyon: `_prepare_toplanma` eksik alanları şeffaf işaretlemeli
(bulgu B — eksik m² için sessiz 1000 m² varsayımı).

Artık `area_source` sütunu her kayıt için "measured" veya "estimated"
değerini taşır; UI bu işaretten sonra uyarı gösterir.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from src.optimizer.data_loader import _prepare_toplanma


def _mk_gdf(rows: list[dict]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        rows,
        geometry=[Point(r["lon"], r["lat"]) for r in rows],
        crs="EPSG:4326",
    )


def test_measured_rows_tagged_correctly():
    raw = _mk_gdf([
        {"Ad": "A", "Alan (m²)": 5000, "lat": 41.0, "lon": 28.9},
        {"Ad": "B", "Alan (m²)": 2000, "lat": 41.0, "lon": 28.95},
    ])
    out = _prepare_toplanma(raw)
    assert "area_source" in out.columns
    assert (out["area_source"] == "measured").all()


def test_missing_area_column_marks_all_estimated():
    """Sütun hiç yoksa tüm satırlar estimated işaretlenmeli."""
    raw = _mk_gdf([
        {"Ad": "A", "lat": 41.0, "lon": 28.9},
        {"Ad": "B", "lat": 41.0, "lon": 28.95},
    ])
    out = _prepare_toplanma(raw)
    assert (out["area_source"] == "estimated").all()
    # Varsayılan 1000 m² uygulanmış mı?
    assert (out["area_m2"] == 1000).all()


def test_mixed_null_and_zero_values_flagged():
    """Sütun var ama bazı satırlarda 0 veya NaN ise onlar estimated olmalı."""
    raw = _mk_gdf([
        {"Ad": "valid",   "Alan (m²)": 4000,  "lat": 41.0, "lon": 28.9},
        {"Ad": "zero",    "Alan (m²)": 0,     "lat": 41.0, "lon": 28.95},
        {"Ad": "missing", "Alan (m²)": None,  "lat": 41.0, "lon": 29.0},
    ])
    out = _prepare_toplanma(raw)
    assert out.loc[out["ad"] == "valid",   "area_source"].iloc[0] == "measured"
    assert out.loc[out["ad"] == "zero",    "area_source"].iloc[0] == "estimated"
    assert out.loc[out["ad"] == "missing", "area_source"].iloc[0] == "estimated"
    # Estimated satırlarda 1000 m² varsayımı kullanılmış olmalı
    assert out.loc[out["ad"] == "zero",    "area_m2"].iloc[0] == 1000
    assert out.loc[out["ad"] == "missing", "area_m2"].iloc[0] == 1000


def test_capacity_respects_afad_standard():
    """1000 m² varsayımı 1.5 m²/kişi'ye bölününce ~666 kişi yaklaşık olmalı."""
    raw = _mk_gdf([
        {"Ad": "missing", "Alan (m²)": None, "lat": 41.0, "lon": 28.9},
    ])
    out = _prepare_toplanma(raw)
    # estimate_capacity_afad min 50 kişi uygulayabilir; beklenen 1000/1.5 ≈ 666
    assert 500 <= int(out["kapasite"].iloc[0]) <= 700, (
        f"Beklenen ~666, bulunan {int(out['kapasite'].iloc[0])}"
    )
