"""
ILP solver engine seçim katmanı regresyonu.

Akademik gereksinim: 19k bina × 150 alan + capacity + ILP exact senaryosunda
CBC pratikte yetersiz; kullanıcı Gurobi/HiGHS gibi alternatif solver'lara
geçebilmeli. Bu testler dispatch + fallback davranışını doğrular.
"""
from __future__ import annotations

import pulp

from src.optimizer.p_median import (
    _SUPPORTED_ILP_ENGINES,
    _make_ilp_solver,
    list_available_ilp_engines,
)


def test_cbc_always_in_available_list():
    """CBC PuLP ile bundled → her zaman erişilebilir olmalı."""
    available = list_available_ilp_engines()
    keys = [k for k, _ in available]
    assert "cbc" in keys, f"CBC mevcut listede yok: {keys}"


def test_available_list_subset_of_supported():
    """Listelenen tüm engine'ler _SUPPORTED_ILP_ENGINES sözlüğünde olmalı."""
    available_keys = {k for k, _ in list_available_ilp_engines()}
    supported_keys = set(_SUPPORTED_ILP_ENGINES.keys())
    assert available_keys.issubset(supported_keys), (
        f"Beklenmeyen engine key: {available_keys - supported_keys}"
    )


def test_available_list_returns_tuples():
    """Dropdown formatı: [(key, display_label), ...]."""
    for item in list_available_ilp_engines():
        assert isinstance(item, tuple) and len(item) == 2
        k, lbl = item
        assert isinstance(k, str) and k
        assert isinstance(lbl, str) and lbl


def test_make_ilp_solver_returns_cbc_for_default():
    """engine='cbc' → PULP_CBC_CMD instance, actual_engine='cbc'."""
    solver, actual = _make_ilp_solver("cbc", time_limit_sn=60)
    assert actual == "cbc"
    assert isinstance(solver, pulp.PULP_CBC_CMD)


def test_make_ilp_solver_falls_back_when_not_installed():
    """
    Kullanıcı kurulu olmayan bir engine isterse (örn. Gurobi yok) CBC'ye
    düşmeli ve actual_engine='cbc' raporlamalı — sessiz çökme YOK.
    """
    available_keys = {k for k, _ in list_available_ilp_engines()}
    # En olası kurulu OLMAYAN engine
    missing_candidate = None
    for candidate in ("gurobi", "cplex", "scip", "highs"):
        if candidate not in available_keys:
            missing_candidate = candidate
            break

    if missing_candidate is None:
        # Tüm engine'ler kuruluysa test atlanabilir (çok zengin makine)
        import pytest
        pytest.skip("Tüm solver'lar kurulu — fallback testi gereksiz")

    solver, actual = _make_ilp_solver(missing_candidate, time_limit_sn=60)
    assert actual == "cbc", (
        f"Kurulu olmayan '{missing_candidate}' istendi, CBC'ye düşmeliydi; "
        f"got '{actual}'"
    )
    assert isinstance(solver, pulp.PULP_CBC_CMD)


def test_make_ilp_solver_accepts_none_time_limit():
    """time_limit_sn=None → solver'a `timeLimit=None` (unlimited) iletilmeli."""
    solver, _ = _make_ilp_solver("cbc", time_limit_sn=None)
    # PULP_CBC_CMD timeLimit attribute olarak tutar
    assert solver.timeLimit is None


def test_make_ilp_solver_normalizes_engine_key():
    """Engine key case-insensitive olmalı (CBC / cbc / Cbc hepsi aynı)."""
    for variant in ("cbc", "CBC", " Cbc ", "cbc"):
        _, actual = _make_ilp_solver(variant, time_limit_sn=60)
        assert actual == "cbc"


def test_make_ilp_solver_unknown_engine_falls_back():
    """Bilinmeyen engine string'i sessizce CBC'ye düşmeli."""
    _, actual = _make_ilp_solver("nonexistent_solver_xyz", time_limit_sn=60)
    assert actual == "cbc"


def test_coz_passes_engine_to_ilp_path():
    """
    coz() → _coz_ilp ilp_engine parametresini geçirir; sonuç
    PMedianResult.ilp_engine_used alanı dolu döner.
    """
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import Point

    from src.optimizer.p_median import coz

    np.random.seed(0)
    n_bina, n_alan = 5, 3
    binalar = gpd.GeoDataFrame({
        "weight":       [10.0] * n_bina,
        "mahalle":      ["A"] * n_bina,
        "alan_m2":      [100.0] * n_bina,
        "levels":       [3] * n_bina,
        "bina_etiketi": [f"B{i}" for i in range(n_bina)],
        "geometry":     [Point(29.0 + i*0.001, 41.0) for i in range(n_bina)],
    }, crs="EPSG:4326")
    alanlar = gpd.GeoDataFrame({
        "ad":       [f"A{j}" for j in range(n_alan)],
        "kapasite": [200.0] * n_alan,
        "geometry": [Point(29.001 + j*0.002, 41.001) for j in range(n_alan)],
    }, crs="EPSG:4326")
    od = np.random.uniform(2.0, 15.0, size=(n_bina, n_alan)).astype(np.float32)

    result = coz(od, binalar, alanlar, p=2, solver="ilp", ilp_engine="cbc")

    assert result.yontem == "ILP"
    assert result.ilp_engine_used == "cbc"


def test_duyarlilik_analizi_accepts_ilp_engine():
    """
    Regresyon (BUG-1): duyarlilik_analizi() ilp_engine parametresini KABUL
    etmeli ve coz()'a forward etmeli. UI'dan ilp_engine geçildiğinde önceden
    `TypeError: unexpected keyword argument 'ilp_engine'` fırlatıyor +
    "Sensitivity analysis failed" mesajı üretiyordu.
    """
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import Point

    from src.optimizer.p_median import duyarlilik_analizi

    np.random.seed(0)
    n_bina, n_alan = 5, 3
    binalar = gpd.GeoDataFrame({
        "weight":       [10.0] * n_bina,
        "mahalle":      ["A"] * n_bina,
        "alan_m2":      [100.0] * n_bina,
        "levels":       [3] * n_bina,
        "bina_etiketi": [f"B{i}" for i in range(n_bina)],
        "geometry":     [Point(29.0 + i * 0.001, 41.0) for i in range(n_bina)],
    }, crs="EPSG:4326")
    alanlar = gpd.GeoDataFrame({
        "ad":       [f"A{j}" for j in range(n_alan)],
        "kapasite": [200.0] * n_alan,
        "geometry": [Point(29.001 + j * 0.002, 41.001) for j in range(n_alan)],
    }, crs="EPSG:4326")
    od = np.random.uniform(2.0, 15.0, size=(n_bina, n_alan)).astype(np.float32)

    # ilp_engine kwarg'ını geçtiğimizde TypeError fırlatmamalı + sonuç dönmeli
    df = duyarlilik_analizi(
        od, binalar, alanlar,
        p_aralik=range(1, 3),
        solver="ilp",
        ilp_engine="cbc",
    )
    assert len(df) == 2, "İki p değeri için iki satır beklenir"
    assert "Yöntem" in df.columns


def test_duyarlilik_analizi_accepts_multistart_kwargs():
    """
    Sprint 1.5 audit BUG-A regresyonu: duyarlilik_analizi imzasına
    n_restarts ve random_state Sprint 2 #14'te eklenmemişti. UI Step 3
    sensitivity panel bunları geçince TypeError sessizce yutuluyordu.
    """
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import Point

    from src.optimizer.p_median import duyarlilik_analizi

    rng = np.random.RandomState(0)
    n_bina, n_alan = 6, 4
    binalar = gpd.GeoDataFrame({
        "weight":       [10.0] * n_bina,
        "mahalle":      ["A"] * n_bina,
        "alan_m2":      [100.0] * n_bina,
        "levels":       [3] * n_bina,
        "bina_etiketi": [f"B{i}" for i in range(n_bina)],
        "geometry":     [Point(29.0 + i * 0.001, 41.0) for i in range(n_bina)],
    }, crs="EPSG:4326")
    alanlar = gpd.GeoDataFrame({
        "ad":       [f"A{j}" for j in range(n_alan)],
        "kapasite": [200.0] * n_alan,
        "geometry": [Point(29.001 + j * 0.002, 41.001) for j in range(n_alan)],
    }, crs="EPSG:4326")
    od = rng.uniform(2.0, 15.0, size=(n_bina, n_alan)).astype(np.float32)

    # K-Med + multi-start kombinasyonu UI'dan tetiklenen tipik akış
    df = duyarlilik_analizi(
        od, binalar, alanlar,
        p_aralik=range(1, 3),
        solver="kmedoids",
        n_restarts=3,
        random_state=42,
    )
    assert len(df) == 2, "İki p değeri için iki satır beklenir"
    assert "Yöntem" in df.columns

    # Aynı seed → aynı sonuç (reprodüksiyon)
    df2 = duyarlilik_analizi(
        od, binalar, alanlar,
        p_aralik=range(1, 3),
        solver="kmedoids",
        n_restarts=3,
        random_state=42,
    )
    # Sayısal sütunlar identik olmalı
    for col in ("Ort. Süre (dk)", "Max Süre (dk)"):
        if col in df.columns and col in df2.columns:
            assert list(df[col]) == list(df2[col]), (
                f"Aynı seed ile sensitivity sonucu identik olmalı (col={col})"
            )


def test_kmedoids_path_leaves_engine_used_as_none():
    """K-Med yolundan dönen result ilp_engine_used=None olmalı."""
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import Point

    from src.optimizer.p_median import coz

    n_bina, n_alan = 5, 3
    binalar = gpd.GeoDataFrame({
        "weight":       [10.0] * n_bina,
        "mahalle":      ["A"] * n_bina,
        "alan_m2":      [100.0] * n_bina,
        "levels":       [3] * n_bina,
        "bina_etiketi": [f"B{i}" for i in range(n_bina)],
        "geometry":     [Point(29.0 + i*0.001, 41.0) for i in range(n_bina)],
    }, crs="EPSG:4326")
    alanlar = gpd.GeoDataFrame({
        "ad":       [f"A{j}" for j in range(n_alan)],
        "kapasite": [200.0] * n_alan,
        "geometry": [Point(29.001 + j*0.002, 41.001) for j in range(n_alan)],
    }, crs="EPSG:4326")
    od = np.random.uniform(2.0, 15.0, size=(n_bina, n_alan)).astype(np.float32)

    result = coz(od, binalar, alanlar, p=2, solver="kmedoids")
    assert result.yontem == "K-Medoids"
    assert result.ilp_engine_used is None
