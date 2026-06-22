"""
Regresyon: min_p95 hedef modu (nüfus-ağırlıklı 95. yüzdelik).

Audit bulgusu: Klasik min_max tek küçük bir bina (weight=1) çözümü domine
edebilir — outlier-hassas. min_p95 nüfus-ağırlıklı 95. yüzdelik süreyi
optimize eder; tipik (büyük) binaları rahatsız etmeden marjinal aykırı
binayı tolere eder.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
from shapely.geometry import Point

from src.optimizer.p_median import (
    P95_PERCENTILE,
    _weighted_percentile,
    coz,
)


def test_weighted_percentile_equal_weights_matches_numpy():
    """
    Eşit ağırlıklarda np.percentile ile (lower interpolation) tutarlı.
    """
    values = np.array([1.0, 5.0, 10.0, 50.0, 100.0])
    weights = np.ones(5)

    p95 = _weighted_percentile(values, weights, percentile=95.0)
    # 5 elemanın p95'i: cum=[1,2,3,4,5], threshold=0.95*5=4.75
    # searchsorted(cum, 4.75, left) = 4 → values[4] = 100.0
    assert p95 == 100.0


def test_weighted_percentile_high_weight_dominates():
    """
    Tek bina çok yüksek ağırlığa sahipse, p95 onun süresine yakınsar.
    """
    values = np.array([5.0, 5.0, 5.0, 100.0])
    weights = np.array([1.0, 1.0, 1.0, 1000.0])  # son bina 1000 kişi

    p95 = _weighted_percentile(values, weights, percentile=95.0)
    assert p95 == 100.0, "Büyük ağırlıklı bina p95'i domine etmeli"


def test_weighted_percentile_outlier_tiny_building_ignored():
    """
    Tek küçük bir bina (weight=1) 100 dk uzakta, geri kalan 999 bina ×
    weight=10 hep 5 dk → p95 küçük binayı YOK SAYMALI (outlier-robust).
    """
    values = np.concatenate([np.full(999, 5.0), np.array([100.0])])
    weights = np.concatenate([np.full(999, 10.0), np.array([1.0])])

    p95 = _weighted_percentile(values, weights, percentile=95.0)
    assert p95 == 5.0, (
        f"Tek outlier küçük bina p95'i kirletmemeli. p95={p95}; "
        f"toplam ağırlık {weights.sum()}, outlier sadece {weights[-1]/weights.sum()*100:.4f}%"
    )


def test_weighted_percentile_handles_inf():
    """Inf değerler p95'i şişirebilmeli (ulaşılamaz binalar fairness'a yansıyor)."""
    values = np.array([5.0, 5.0, np.inf])
    weights = np.array([1.0, 1.0, 1.0])
    p95 = _weighted_percentile(values, weights, percentile=95.0)
    assert np.isinf(p95)


def test_weighted_percentile_skips_nan():
    """NaN değerler dışlanır."""
    values = np.array([5.0, 10.0, np.nan])
    weights = np.array([1.0, 1.0, 1.0])
    p95 = _weighted_percentile(values, weights, percentile=95.0)
    assert p95 == 10.0


def _make_outlier_setup():
    """
    100 büyük bina (weight=10) hep 5 dk mesafede + 1 küçük bina (weight=1) çok uzak.
    İki açık alan: A1 ana binalara yakın, A2 küçük binaya yakın.
    """
    np.random.seed(0)
    n_main = 100
    binalar = gpd.GeoDataFrame(
        {
            "weight": [10.0] * n_main + [1.0],
            "mahalle": ["M"] * (n_main + 1),
            "alan_m2": [100.0] * (n_main + 1),
            "levels": [3] * (n_main + 1),
            "bina_etiketi": [f"B{i}" for i in range(n_main + 1)],
            "geometry": (
                [Point(29.0 + i * 0.0001, 41.0) for i in range(n_main)]
                + [Point(29.05, 41.05)]   # outlier
            ),
        },
        crs="EPSG:4326",
    )
    alanlar = gpd.GeoDataFrame(
        {
            "ad": ["A1_ana", "A2_outlier"],
            "kapasite": [100000.0, 100000.0],
            "geometry": [Point(29.005, 41.0), Point(29.05, 41.05)],
        },
        crs="EPSG:4326",
    )

    od = np.full((n_main + 1, 2), 5.0, dtype=np.float32)
    # A1 her ana binaya 5 dk
    od[:n_main, 0] = 5.0
    # A2 her ana binaya 30 dk
    od[:n_main, 1] = 30.0
    # Outlier bina A1'e 60 dk uzak, A2'ye 2 dk
    od[n_main, 0] = 60.0
    od[n_main, 1] = 2.0
    return od, binalar, alanlar


def test_min_p95_does_not_sacrifice_main_population_for_outlier():
    """
    p=1: Bir alan seçilebiliyor. Outlier (1 kişi) için A2'yi seçmek 100 ana
    binayı 30 dk yürütür — kötü. min_p95 A1'i seçmeli (ana kütle için iyi),
    outlier'ın 60 dk'sını tolere etmeli.

    min_max bunun TAM TERSİNİ yapardı: en kötü süreyi minimize için A2'yi
    seçer (max=30 < max=60), 100 büyük binayı 30 dk yürütür.
    """
    od, binalar, alanlar = _make_outlier_setup()

    sonuc_p95 = coz(od, binalar, alanlar, p=1, kapasite=False, amac="min_p95")
    # min_p95: A1 seçmeli — main bina p95'i 5 dk, p99 ~5 dk, p100 (outlier) 60 dk
    assert sonuc_p95.acik_alan_adlari == ["A1_ana"], (
        f"min_p95 ana kütle için A1_ana seçmeliydi, geldi: {sonuc_p95.acik_alan_adlari}"
    )

    sonuc_max = coz(od, binalar, alanlar, p=1, kapasite=False, amac="min_max")
    # min_max: A2 seçer — max(30, 2) = 30 < max(5, 60) = 60
    assert sonuc_max.acik_alan_adlari == ["A2_outlier"], (
        f"min_max outlier için A2_outlier seçmeliydi (worst-case fairness), "
        f"geldi: {sonuc_max.acik_alan_adlari}"
    )


def test_min_p95_metadata_preserved():
    """min_p95 sonucunda amac field'ı doğru aktarılmalı."""
    od, binalar, alanlar = _make_outlier_setup()
    sonuc = coz(od, binalar, alanlar, p=1, kapasite=False, amac="min_p95")
    assert sonuc.amac == "min_p95"
    assert sonuc.yontem == "Heuristic"   # min_p95 ILP'de uygulanmaz


def test_min_p95_constant():
    """P95_PERCENTILE makul aralıkta (90-99)."""
    assert 90.0 <= P95_PERCENTILE <= 99.0
