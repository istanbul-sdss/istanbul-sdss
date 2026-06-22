"""
Sprint 2 #14 + #20: Heuristic multi-start + stable seed regresyonu.

Akademik gereksinim:
  • Multi-start: tek-shot greedy local optimum'a takılabilir; N restart ile
    en iyi sonucu seçmek heuristik kaliteyi artırır.
  • Stable seed: aynı seed + aynı problem = aynı sonuç → tez figürleri
    reprodüklenebilir.

Bu testler şunları doğrular:
  1. n_restarts=1 (default) backward-compat (eski tek-shot davranışı).
  2. n_restarts>1 deterministik 1. restart + N-1 random restart.
  3. random_state aynı verildiğinde sonuç identik (reprodüksiyon).
  4. Multi-start sonucu tek-shot sonucundan daima ≤ (ya aynı ya daha iyi).
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
from shapely.geometry import Point

from src.optimizer.p_median import coz


def _make_data(n_bina: int = 30, n_alan: int = 10, seed: int = 0):
    """Reprodüklenebilir orta-boy test problemi."""
    rng = np.random.RandomState(seed)
    binalar = gpd.GeoDataFrame({
        "weight":       rng.uniform(50, 200, n_bina).astype(float),
        "mahalle":      ["A"] * n_bina,
        "alan_m2":      [100.0] * n_bina,
        "levels":       [3] * n_bina,
        "bina_etiketi": [f"B{i}" for i in range(n_bina)],
        "geometry":     [Point(29.0 + i * 0.001, 41.0) for i in range(n_bina)],
    }, crs="EPSG:4326")
    alanlar = gpd.GeoDataFrame({
        "ad":       [f"A{j}" for j in range(n_alan)],
        "kapasite": [10000.0] * n_alan,
        "geometry": [Point(29.001 + j * 0.002, 41.001) for j in range(n_alan)],
    }, crs="EPSG:4326")
    od = rng.uniform(2.0, 25.0, size=(n_bina, n_alan)).astype(np.float32)
    return od, binalar, alanlar


def test_n_restarts_default_is_one():
    """Default n_restarts=1 → eski tek-shot davranışı korunur."""
    od, b, t = _make_data()
    r = coz(od, b, t, p=3, solver="heuristic")
    # Hâlâ Heuristic dönmeli, convergence raporlanmalı
    assert r.yontem == "Heuristic"
    assert r.heuristic_converged in (True, False)
    assert isinstance(r.heuristic_iterations, int)


def test_multistart_returns_no_worse_cost():
    """
    n_restarts=5 sonucu, n_restarts=1 sonucundan **daima** ≤ cost'lu olmalı.
    (Aynı 1. deterministik restart'ı zaten içeriyor; ek random restartlar
    sadece iyileştirme katabilir.)
    """
    od, b, t = _make_data(n_bina=30, n_alan=10)
    single = coz(od, b, t, p=3, solver="heuristic", n_restarts=1)
    multi  = coz(od, b, t, p=3, solver="heuristic", n_restarts=5, random_state=42)
    # toplam_agirlikli_sure (min_sum amaç fonksiyonu cost'u)
    assert multi.toplam_agirlikli_sure <= single.toplam_agirlikli_sure + 1e-6, (
        f"Multi-start daha kötü sonuç verdi: {multi.toplam_agirlikli_sure} > "
        f"{single.toplam_agirlikli_sure}"
    )


def test_seed_reproducibility():
    """Aynı seed + aynı problem = aynı sonuç (alan seti, cost, atama)."""
    od, b, t = _make_data(n_bina=25, n_alan=8)
    r1 = coz(od, b, t, p=3, solver="heuristic", n_restarts=5, random_state=123)
    r2 = coz(od, b, t, p=3, solver="heuristic", n_restarts=5, random_state=123)
    assert sorted(r1.acik_alanlar) == sorted(r2.acik_alanlar), (
        "Aynı seed farklı alan seti döndü: "
        f"{r1.acik_alanlar} vs {r2.acik_alanlar}"
    )
    assert abs(r1.toplam_agirlikli_sure - r2.toplam_agirlikli_sure) < 1e-6


def test_different_seeds_can_diverge():
    """
    Farklı seed'ler farklı (veya eşit) sonuca yol açabilir.
    Burada yalnızca "çağrı çalışır" ve "sonuç döner" garantisi;
    farklılık şart değil (problem çok küçükse identik olabilir).
    """
    od, b, t = _make_data(n_bina=30, n_alan=10)
    r_a = coz(od, b, t, p=3, solver="heuristic", n_restarts=5, random_state=0)
    r_b = coz(od, b, t, p=3, solver="heuristic", n_restarts=5, random_state=999)
    # Her ikisi de geçerli K-Med sonucu
    assert r_a.yontem == r_b.yontem == "Heuristic"
    assert len(r_a.acik_alanlar) == len(r_b.acik_alanlar) == 3


def test_multistart_with_capacity_works():
    """Capacity-aware multi-start hatasız çalışmalı."""
    od, b, t = _make_data(n_bina=20, n_alan=8)
    r = coz(
        od, b, t, p=3, solver="heuristic", kapasite=True,
        n_restarts=3, random_state=42,
    )
    assert r.yontem == "Heuristic"
    assert r.kapasite_aktif is True


def test_random_state_none_still_runs():
    """random_state=None (default) → her run farklı RNG kullanır, çökmez."""
    od, b, t = _make_data(n_bina=15, n_alan=6)
    r = coz(od, b, t, p=2, solver="heuristic", n_restarts=3, random_state=None)
    assert r.yontem == "Heuristic"


def test_n_restarts_zero_treated_as_one():
    """n_restarts=0 (geçersiz) silent olarak 1'e normalize edilmeli."""
    od, b, t = _make_data(n_bina=10, n_alan=5)
    r = coz(od, b, t, p=2, solver="heuristic", n_restarts=0)
    assert r.yontem == "Heuristic"
    # Sonuç convergence rapor etmiş olmalı
    assert isinstance(r.heuristic_iterations, int)
