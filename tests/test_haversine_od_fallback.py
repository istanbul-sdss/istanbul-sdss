"""
Regresyon: Sokak ağı yedeği — haversine OD matrisi.

Audit bulgusu: Overpass mirror'ları 504 dönerse veya internet kesilirse
get_walk_graph() RuntimeError fırlatıyor ve tüm pipeline çöküyor. Afet
aracı için kabul edilemez. Çözüm: kuş uçuşu mesafe × detour faktörü ile
yaklaşık OD üretebilen bir yedek fonksiyon — sınırlı doğrulukta ama
kullanılabilir.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
from shapely.geometry import Point

from src.optimizer.od_matrix import (
    HAVERSINE_DETOUR_FACTOR,
    WALK_SPEED_KPH,
    compute_od_matrix_haversine,
)


def _make_gdfs(b_coords, t_coords):
    binalar = gpd.GeoDataFrame(
        {"weight": [1.0] * len(b_coords),
         "geometry": [Point(x, y) for x, y in b_coords]},
        crs="EPSG:4326",
    )
    alanlar = gpd.GeoDataFrame(
        {"ad": [f"A{i}" for i in range(len(t_coords))],
         "kapasite": [100.0] * len(t_coords),
         "geometry": [Point(x, y) for x, y in t_coords]},
        crs="EPSG:4326",
    )
    return binalar, alanlar


def test_haversine_known_distance():
    """
    Aynı enlemde 0.01° boylam farkı ≈ 833 m (41° enleminde).
    Detour 1.4 ile 1166 m → 4.8 km/h → ~14.6 dk.
    """
    binalar, alanlar = _make_gdfs(
        b_coords=[(29.000, 41.000)],
        t_coords=[(29.010, 41.000)],
    )
    od = compute_od_matrix_haversine(binalar, alanlar)
    assert od.shape == (1, 1)

    # UTM projeksiyonda gerçek mesafe ~833 m × 1.4 = ~1166 m
    # 1166 m / (4.8 × 1000 / 60) = ~14.6 dk
    expected_min = 833 * HAVERSINE_DETOUR_FACTOR / (WALK_SPEED_KPH * 1000 / 60)
    assert abs(float(od[0, 0]) - expected_min) < 1.0, (
        f"Haversine OD beklenen ~{expected_min:.1f} dk, gelen {od[0, 0]:.1f} dk"
    )


def test_haversine_diagonal_is_finite():
    """Köşegen mesafelerde de inf üretilmemeli; tüm hücreler sonlu."""
    binalar, alanlar = _make_gdfs(
        b_coords=[(29.000, 41.000), (29.020, 41.010), (29.005, 41.020)],
        t_coords=[(29.010, 41.005), (29.015, 41.015)],
    )
    od = compute_od_matrix_haversine(binalar, alanlar)
    assert od.shape == (3, 2)
    assert np.isfinite(od).all(), "Haversine matrisinde inf olmamalı"
    assert (od >= 0).all()


def test_haversine_symmetric_distances():
    """Aynı bina-alan çiftleri ters konumda aynı süreyi vermeli."""
    binalar1, alanlar1 = _make_gdfs(
        b_coords=[(29.000, 41.000)], t_coords=[(29.010, 41.005)]
    )
    binalar2, alanlar2 = _make_gdfs(
        b_coords=[(29.010, 41.005)], t_coords=[(29.000, 41.000)]
    )
    od1 = compute_od_matrix_haversine(binalar1, alanlar1)
    od2 = compute_od_matrix_haversine(binalar2, alanlar2)
    assert abs(float(od1[0, 0]) - float(od2[0, 0])) < 0.01


def test_detour_factor_scales_linearly():
    """Detour 1.0 vs 2.0 → süreler tam 2× olmalı (saf geometri)."""
    binalar, alanlar = _make_gdfs(
        b_coords=[(29.000, 41.000)], t_coords=[(29.005, 41.000)]
    )
    od_no_detour = compute_od_matrix_haversine(binalar, alanlar, detour_factor=1.0)
    od_double = compute_od_matrix_haversine(binalar, alanlar, detour_factor=2.0)
    assert abs(float(od_double[0, 0]) - 2.0 * float(od_no_detour[0, 0])) < 0.01


def test_detour_factor_default_is_realistic():
    """Şehir-içi yaya literatürü için 1.3-1.5 aralığında olmalı."""
    assert 1.2 <= HAVERSINE_DETOUR_FACTOR <= 1.6, (
        f"HAVERSINE_DETOUR_FACTOR={HAVERSINE_DETOUR_FACTOR} şehir-içi yaya "
        f"literatür aralığı (1.3-1.5) dışında."
    )


# ── H-Opt-3: Mod-farkındalıklı detour ─────────────────────────────────────
def test_mode_aware_detour_walk_vs_drive():
    """
    transport_mode="walk" → 1.4 detour; "drive" → 1.25 detour.
    Aynı mesafe ve hız için drive süresi walk süresinden DAHA AZ olmalı
    (detour daha düşük çünkü araç arter/otoyol kullanır).
    """
    from src.optimizer.od_matrix import DEFAULT_DETOUR_FACTOR, MODE_DRIVE, MODE_WALK

    assert DEFAULT_DETOUR_FACTOR[MODE_WALK] > DEFAULT_DETOUR_FACTOR[MODE_DRIVE], (
        "Yaya detour'u araç detour'undan büyük olmalı (literatür beklentisi)"
    )

    binalar, alanlar = _make_gdfs(
        b_coords=[(29.000, 41.000)], t_coords=[(29.005, 41.000)]
    )
    # Hızı sabit tut; sadece detour mod'a göre değişsin
    od_walk = compute_od_matrix_haversine(
        binalar, alanlar, travel_speed_kph=5.0, transport_mode=MODE_WALK
    )
    od_drive = compute_od_matrix_haversine(
        binalar, alanlar, travel_speed_kph=5.0, transport_mode=MODE_DRIVE
    )
    # walk_dur * (drive_detour/walk_detour) == drive_dur
    ratio = DEFAULT_DETOUR_FACTOR[MODE_DRIVE] / DEFAULT_DETOUR_FACTOR[MODE_WALK]
    assert abs(float(od_drive[0, 0]) - float(od_walk[0, 0]) * ratio) < 0.01


def test_explicit_detour_overrides_mode():
    """detour_factor explicit verildiğinde transport_mode önemsiz."""
    binalar, alanlar = _make_gdfs(
        b_coords=[(29.000, 41.000)], t_coords=[(29.005, 41.000)]
    )
    od_drive = compute_od_matrix_haversine(
        binalar, alanlar, detour_factor=2.0, transport_mode="drive"
    )
    od_walk = compute_od_matrix_haversine(
        binalar, alanlar, detour_factor=2.0, transport_mode="walk"
    )
    # detour=2.0 her iki modda da aynı → süreler eşit (speed default)
    assert abs(float(od_drive[0, 0]) - float(od_walk[0, 0])) < 0.01


def test_no_mode_no_factor_uses_legacy_default():
    """
    transport_mode YOK + detour_factor YOK → eski HAVERSINE_DETOUR_FACTOR
    kullanılır (1.4). Backward-compat zorunlu.
    """
    binalar, alanlar = _make_gdfs(
        b_coords=[(29.000, 41.000)], t_coords=[(29.005, 41.000)]
    )
    od_legacy = compute_od_matrix_haversine(binalar, alanlar)
    od_walk_explicit = compute_od_matrix_haversine(
        binalar, alanlar, transport_mode="walk"
    )
    # Walk default == legacy default (1.4) → süreler eşit
    assert abs(float(od_legacy[0, 0]) - float(od_walk_explicit[0, 0])) < 0.01
