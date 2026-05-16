"""
Regresyon (P2.1): K-Medoids `min_max` (fairness) hedefini de desteklemeli;
büyük veri setlerinde sessizce `min_sum`'a düşmemeli.

Audit bulgusu: coz() n_bina > ILP_THRESHOLD (5000) olduğunda
_coz_kmedoids'e geçiyordu, ama _coz_kmedoids `amac` parametresi ALMIYORDU.
Sonuç: kullanıcı UI'da "fairness" seçtiyse de _build_result'a sabit
`amac="min_sum"` ile geri dönüyordu — hem hedef yanlıştı hem metadata yanlıştı.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point

from src.optimizer.p_median import ILP_THRESHOLD, _coz_kmedoids, coz


def _synthetic_inputs(n_bina: int, n_alan: int, seed: int = 42):
    """K-Medoids tetiklenecek ölçekte sahte input üretir."""
    rng = np.random.default_rng(seed)
    od = rng.uniform(2, 25, size=(n_bina, n_alan)).astype(float)
    binalar = gpd.GeoDataFrame(
        {
            "weight":       rng.integers(1, 100, n_bina).astype(float),
            "mahalle":      ["Mah_X"] * n_bina,
            "bina_etiketi": [f"B{i}" for i in range(n_bina)],
        },
        geometry=[Point(29.0 + i * 1e-4, 41.0) for i in range(n_bina)],
        crs="EPSG:4326",
    )
    toplanma = gpd.GeoDataFrame(
        {
            "ad":       [f"T{j}" for j in range(n_alan)],
            "kapasite": [10000] * n_alan,
        },
        geometry=[Point(29.0 + j * 1e-3, 41.005) for j in range(n_alan)],
        crs="EPSG:4326",
    )
    return od, binalar, toplanma


def test_kmedoids_signature_accepts_objective():
    """_coz_kmedoids artık `amac` parametresi almalı."""
    import inspect
    sig = inspect.signature(_coz_kmedoids)
    assert "amac" in sig.parameters, (
        "REGRESYON: _coz_kmedoids `amac` parametresi taşımıyor → büyük "
        "veri setinde min_max seçimi sessizce kayboluyor."
    )


def test_coz_min_max_metadata_preserved_at_large_scale():
    """
    n_bina > ILP_THRESHOLD ile coz(amac='min_max') çağrıldığında sonuç
    metadata'sı min_max olarak gelmeli — silently min_sum'a düşmemeli.
    """
    n = ILP_THRESHOLD + 50
    od, binalar, toplanma = _synthetic_inputs(n, 6)
    result = coz(od, binalar, toplanma, p=3, amac="min_max")
    assert result.yontem == "K-Medoids", f"yöntem={result.yontem}"
    assert result.amac == "min_max", (
        f"REGRESYON: amac='min_max' istendi ama sonuç '{result.amac}'. "
        f"Kullanıcı UI'da fairness seçtiğini sanıyor, sistem efficiency "
        f"çözümü veriyor."
    )


def test_coz_min_sum_still_works_at_large_scale():
    """min_sum varsayılanı bozulmamalı (regresyon koruması)."""
    n = ILP_THRESHOLD + 50
    od, binalar, toplanma = _synthetic_inputs(n, 6)
    result = coz(od, binalar, toplanma, p=3, amac="min_sum")
    assert result.amac == "min_sum"


def test_min_max_actually_reduces_worst_case_distance():
    """
    Davranış doğrulaması: min_max çözümü, min_sum'a göre EN KÖTÜ atama
    süresini azaltma yönünde tercih yapmalı (mutlak garanti vermez ama
    eşit problemler üzerinde çoğu zaman başarır).
    Bu test "objektif fonksiyonu çalışıyor mu" kontrolüdür.
    """
    n = ILP_THRESHOLD + 50
    od, binalar, toplanma = _synthetic_inputs(n, 8)

    res_sum = coz(od, binalar, toplanma, p=4, amac="min_sum")
    res_max = coz(od, binalar, toplanma, p=4, amac="min_max")

    # En kötü atama süresi: PMedianResult.max_sure_dk doğrudan veriyor.
    worst_sum = res_sum.max_sure_dk
    worst_max = res_max.max_sure_dk

    # min_max en kötü süreyi DAHA YÜKSEK üretmemeli (eşit kabul, daha düşük tercih)
    assert worst_max <= worst_sum + 0.5, (
        f"min_max amacı en kötü süreyi düşürmüyor: min_sum worst={worst_sum:.2f}, "
        f"min_max worst={worst_max:.2f}. Hedef fonksiyonu yanlış tanımlanmış olabilir."
    )
