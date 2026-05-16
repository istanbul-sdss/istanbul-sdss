"""
Regresyon: Solver seçim modu (auto/ilp/kmedoids) + time_limit override
+ allow_fallback davranışı.

Audit gereksinimi: Kullanıcı bazen otomatik eşiği bypass edip belirli bir
çözücü zorlamak ister (akademik karşılaştırma, hız testi, A/B çalışma).
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point

from src.optimizer.p_median import ILP_THRESHOLD, coz


def _make_data(n_bina=20, n_alan=4, weight=10.0, kapasite=200.0):
    """Küçük ama gerçekçi bir test fixture'ı."""
    np.random.seed(0)
    binalar = gpd.GeoDataFrame(
        {
            "weight": [weight] * n_bina,
            "mahalle": ["M"] * n_bina,
            "alan_m2": [100.0] * n_bina,
            "levels": [3] * n_bina,
            "bina_etiketi": [f"B{i}" for i in range(n_bina)],
            "geometry": [
                Point(29.0 + (i % 5) * 0.001, 41.0 + (i // 5) * 0.001)
                for i in range(n_bina)
            ],
        },
        crs="EPSG:4326",
    )
    alanlar = gpd.GeoDataFrame(
        {
            "ad": [f"A{j}" for j in range(n_alan)],
            "kapasite": [kapasite] * n_alan,
            "geometry": [Point(29.001 + j * 0.002, 41.001) for j in range(n_alan)],
        },
        crs="EPSG:4326",
    )
    od = np.random.uniform(2.0, 15.0, size=(n_bina, n_alan)).astype(np.float32)
    return od, binalar, alanlar


def test_solver_auto_uses_ilp_for_small_problem():
    """Küçük problem (n_bina < ILP_THRESHOLD) ve min_sum → ILP seçilir."""
    od, binalar, alanlar = _make_data(n_bina=20)
    sonuc = coz(od, binalar, alanlar, p=2, solver="auto", amac="min_sum")
    assert sonuc.yontem == "ILP"


def test_solver_force_kmedoids_overrides_threshold():
    """Küçük problem olsa da kullanıcı kmedoids zorlarsa K-Medoids çalışır."""
    od, binalar, alanlar = _make_data(n_bina=20)
    sonuc = coz(od, binalar, alanlar, p=2, solver="kmedoids", amac="min_sum")
    assert sonuc.yontem == "K-Medoids"


def test_solver_force_ilp_for_min_max():
    """solver='ilp' + amac='min_max' geçerli — ILP min_max destekler."""
    od, binalar, alanlar = _make_data(n_bina=20)
    sonuc = coz(od, binalar, alanlar, p=2, solver="ilp", amac="min_max")
    assert sonuc.yontem == "ILP"


def test_solver_ilp_with_p95_rejected():
    """
    solver='ilp' + amac='min_p95' kombinasyonu reddedilmeli — p95 ILP'de
    doğrusal değil. ValueError, sessizce K-Medoids'e düşmek değil.
    """
    od, binalar, alanlar = _make_data(n_bina=20)
    with pytest.raises(ValueError, match="min_p95"):
        coz(od, binalar, alanlar, p=2, solver="ilp", amac="min_p95")


def test_solver_auto_routes_p95_to_kmedoids():
    """auto + min_p95 → otomatik K-Medoids (geriye uyumlu davranış)."""
    od, binalar, alanlar = _make_data(n_bina=20)
    sonuc = coz(od, binalar, alanlar, p=2, solver="auto", amac="min_p95")
    assert sonuc.yontem == "K-Medoids"


def test_solver_kmedoids_accepts_p95():
    """Açıkça K-Medoids + p95 sorunsuz çalışmalı."""
    od, binalar, alanlar = _make_data(n_bina=20)
    sonuc = coz(od, binalar, alanlar, p=2, solver="kmedoids", amac="min_p95")
    assert sonuc.yontem == "K-Medoids"
    assert sonuc.amac == "min_p95"


def test_solver_invalid_value_rejected():
    """Geçersiz solver değeri ValueError vermeli."""
    od, binalar, alanlar = _make_data(n_bina=20)
    with pytest.raises(ValueError, match="solver="):
        coz(od, binalar, alanlar, p=2, solver="gurobi")


def test_time_limit_override_passes_through():
    """
    time_limit_sn parametresi ILP'ye iletilmeli. Çok kısa bir limit (1 sn) ile
    karmaşık bir problemde timeLimit etkisi gözlenebilir; küçük testte
    sadece kabul edildiğini doğrularız.
    """
    od, binalar, alanlar = _make_data(n_bina=20)
    sonuc = coz(
        od, binalar, alanlar, p=2,
        solver="ilp", time_limit_sn=60,
    )
    assert sonuc.yontem == "ILP"


def test_allow_fallback_false_raises_on_ilp_failure():
    """
    Kapasite çok yetersiz → ILP infeasible → allow_fallback=False ise
    RuntimeError vermeli (sessizce K-Medoids'e düşmemeli).

    Setup: ulaşılabilirlik tamam (max_sure_dk=None), ama Σwᵢxᵢⱼ ≤ Cⱼ·yⱼ ve
    Σⱼyⱼ=p kısıtları birlikte talep > p·max_kapasite olduğu için infeasible.
    """
    od, binalar, alanlar = _make_data(n_bina=20, weight=100.0, kapasite=10.0)
    # od finite kalsın → ulaşılabilirlik kontrolü geçer; ILP'nin
    # kapasite kısıtları 2000 talep vs 20 kapasite ile infeasible döner.

    with pytest.raises(RuntimeError, match="allow_fallback=False"):
        coz(
            od, binalar, alanlar, p=2,
            solver="ilp", kapasite=True,
            allow_fallback=False,
        )


def test_allow_fallback_true_falls_back_silently():
    """allow_fallback=True (varsayılan) → ILP infeasible'da K-Medoids'e düşer."""
    od, binalar, alanlar = _make_data(n_bina=20, weight=100.0, kapasite=10.0)
    sonuc = coz(
        od, binalar, alanlar, p=2,
        solver="ilp", kapasite=True,
        allow_fallback=True,
    )
    # Fallback gerçekleştiyse K-Medoids dönmeli ve fallback_nedeni dolu olmalı
    assert sonuc.yontem == "K-Medoids"
    assert sonuc.fallback_nedeni is not None
