"""
Regresyon: heuristic kapasite kısıtı gerçek bir hard-constraint olmalı
(bulgu #3).

Eski hali: kapasite yetersizse `_assign_with_capacity` binayı en yakın
alana taşır ve `kalan_kapasite` negatife düşerdi (AFAD 1.5 m²/kişi ihlali,
sessiz).
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
from shapely.geometry import Point

from src.optimizer.p_median import _assign_with_capacity, coz


def test_capacity_hard_constraint_no_overflow():
    """Kapasite yetmiyorsa bina yerleştirilmez, negatife düşmez.

    NOT: Greedy atama integer'dır. Kapasite=150 bir alana sadece 1 bina
    (weight=100) sığdırabilir; kalan 50 birim bir sonraki 100'lük binayı
    kaldıramaz. Yani toplam 300 birim kapasite 5 birim × 100 binada
    kuramsal olarak 3 binayı kaldırmalı gibi görünse de, integer kısıt
    altında sadece 2 bina yerleşir. Bu testin asıl amacı TAŞMA olmamasıdır.
    """
    od = np.array([
        [1.0, 10.0],
        [2.0,  9.0],
        [3.0,  8.0],
        [4.0,  7.0],
        [5.0,  6.0],
    ], dtype=float)
    agirliklar = np.array([100, 100, 100, 100, 100], dtype=float)  # toplam 500
    kapasiteler_all = np.array([150, 150, 999], dtype=float)
    acik = [0, 1]   # toplam açık kapasite = 300 < 500

    atama, sureler, sebep = _assign_with_capacity(
        od, agirliklar, acik, kapasiteler_all
    )

    n_yerlesmemis = int((atama == -1).sum())
    # En az 2 bina yerleşmemeli (kapasite açığı). Integer greedy nedeniyle
    # 3 olabilir — ikisi de kabul edilebilir, kritik olan taşma yok.
    assert n_yerlesmemis >= 2, (
        f"Kapasite ihlali görünmüyor: n_yerlesmemis={n_yerlesmemis}"
    )

    # KRİTİK: hiçbir atama kapasiteyi taşıracak şekilde zorlanmamış olmalı
    # (yerleşen binaların toplam ağırlığı alan kapasitesini geçmemeli)
    for alan_idx in acik:
        yerlesen_agirlik = agirliklar[atama == alan_idx].sum()
        assert yerlesen_agirlik <= kapasiteler_all[alan_idx], (
            f"TAŞMA: alan {alan_idx} kapasitesi {kapasiteler_all[alan_idx]}, "
            f"yerleşen {yerlesen_agirlik}"
        )

    # Yerleştirilemeyenlerin sebep kodu 2 (kapasite yetersiz) olmalı
    assert (sebep[atama == -1] == 2).all()


def test_no_overflow_preserves_afad_standard():
    """
    Küçük sentetik senaryoda (kapasite 50, 2 bina × 100 kişi), eski kod
    her iki binayı da aynı alana atıyor ve kapasite -150'ye düşüyordu.
    Yeni kod sadece 0 bina atamalı (hiçbirinin ağırlığı tek başına kapasiteyi
    geçiyor).
    """
    od = np.array([[1.0], [2.0]], dtype=float)
    agirliklar = np.array([100, 100], dtype=float)
    kapasiteler = np.array([50], dtype=float)  # tek alan, yetersiz
    acik = [0]

    atama, sureler, sebep = _assign_with_capacity(
        od, agirliklar, acik, kapasiteler
    )

    assert (atama == -1).all(), "Hiçbir bina yerleştirilmemeli (kapasite 50 < 100)"
    assert np.isinf(sureler).all()
    assert (sebep == 2).all()


def test_end_to_end_coz_reports_capacity_unreachable():
    """coz() uçtan uca — kapasite yetersiz binalar `ulasilamaz_binalar`'da görünmeli."""
    rng_geom = [Point(28.9 + 0.01 * i, 41.0) for i in range(6)]
    binalar = gpd.GeoDataFrame(
        {
            "weight":       [100] * 6,
            "mahalle":      ["M1"] * 6,
            "alan_m2":      [120] * 6,
            "levels":       [4] * 6,
            "bina_etiketi": [f"B{i+1}" for i in range(6)],
            "geometry":     rng_geom,
        },
        crs="EPSG:4326",
    )
    toplanma = gpd.GeoDataFrame(
        {
            "ad":       ["A1", "A2", "A3"],
            "kapasite": [150, 100, 50],   # toplam 300 < nüfus 600
            "geometry": [Point(28.92, 41.01), Point(28.95, 41.01), Point(28.98, 41.01)],
        },
        crs="EPSG:4326",
    )
    od = np.array([
        [ 3,  7, 11],
        [ 2,  6, 10],
        [ 4,  5,  9],
        [ 6,  4,  8],
        [10,  5,  3],
        [12,  8,  2],
    ], dtype=float)

    result = coz(od, binalar, toplanma, p=3, kapasite=True, max_sure_dk=30.0)

    assert result.kapasite_aktif is True
    assert result.ulasilamaz_sayisi > 0, "Capacity shortage was not reported"
    # Reason text should mention "capacity" (English) — TR fallback for compat.
    sebepler = result.ulasilamaz_binalar["sebep"].astype(str).str.lower().tolist()
    assert any(("capacity" in s) or ("kapasite" in s) for s in sebepler), (
        f"Reason text did not contain capacity/kapasite: {sebepler}"
    )
