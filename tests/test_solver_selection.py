"""
Regresyon: Solver seçim modu (auto/ilp/heuristic) + time_limit override
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


def test_solver_force_heuristic_overrides_threshold():
    """Küçük problem olsa da kullanıcı heuristic zorlarsa Heuristic çalışır."""
    od, binalar, alanlar = _make_data(n_bina=20)
    sonuc = coz(od, binalar, alanlar, p=2, solver="heuristic", amac="min_sum")
    assert sonuc.yontem == "Heuristic"


def test_solver_force_ilp_for_min_max():
    """solver='ilp' + amac='min_max' geçerli — ILP min_max destekler."""
    od, binalar, alanlar = _make_data(n_bina=20)
    sonuc = coz(od, binalar, alanlar, p=2, solver="ilp", amac="min_max")
    assert sonuc.yontem == "ILP"


def test_solver_ilp_with_p95_rejected():
    """
    solver='ilp' + amac='min_p95' kombinasyonu reddedilmeli — p95 ILP'de
    doğrusal değil. ValueError, sessizce Heuristic'e düşmek değil.
    """
    od, binalar, alanlar = _make_data(n_bina=20)
    with pytest.raises(ValueError, match="min_p95"):
        coz(od, binalar, alanlar, p=2, solver="ilp", amac="min_p95")


def test_solver_auto_routes_p95_to_heuristic():
    """auto + min_p95 → otomatik Heuristic (geriye uyumlu davranış)."""
    od, binalar, alanlar = _make_data(n_bina=20)
    sonuc = coz(od, binalar, alanlar, p=2, solver="auto", amac="min_p95")
    assert sonuc.yontem == "Heuristic"


def test_solver_heuristic_accepts_p95():
    """Açıkça Heuristic + p95 sorunsuz çalışmalı."""
    od, binalar, alanlar = _make_data(n_bina=20)
    sonuc = coz(od, binalar, alanlar, p=2, solver="heuristic", amac="min_p95")
    assert sonuc.yontem == "Heuristic"
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


def test_unlimited_bool_param_overrides_time_limit(monkeypatch):
    """
    Sprint 2 #13: `unlimited=True` time_limit_sn'den bağımsız olarak
    solver'a `timeLimit=None` gönderir. Niyet-açık API (eskiden
    `time_limit_sn=0` sentinel'i).
    """
    import pulp

    captured: dict = {}
    _OriginalCBC = pulp.PULP_CBC_CMD

    class _MockCmd:
        def __init__(self, *_, **kwargs):
            captured["timeLimit"] = kwargs.get("timeLimit")
            self._delegate = _OriginalCBC(msg=0, timeLimit=kwargs.get("timeLimit"))

        def actualSolve(self, prob):  # noqa: N802
            return self._delegate.actualSolve(prob)

        def solve(self, prob):
            return self.actualSolve(prob)

    monkeypatch.setattr(pulp, "PULP_CBC_CMD", _MockCmd)

    od, binalar, alanlar = _make_data(n_bina=10)

    # unlimited=True → time_limit_sn ne olursa olsun None geçer
    coz(od, binalar, alanlar, p=2, solver="ilp",
        time_limit_sn=120, unlimited=True)
    assert captured["timeLimit"] is None, (
        "unlimited=True ile time_limit_sn=120 verilse bile None bekleniyor"
    )

    # unlimited=False → time_limit_sn dikkate alınır
    coz(od, binalar, alanlar, p=2, solver="ilp",
        time_limit_sn=180, unlimited=False)
    assert captured["timeLimit"] == 180


def test_time_limit_sentinel_zero_means_unlimited(monkeypatch):
    """
    Sentinel: time_limit_sn=0 → CBC'ye timeLimit=None gönderilir (sınırsız).
    Önceden `or` operatörü 0'ı falsy sayıp default'a düşürüyordu — kullanıcı
    "sınırsız" istediğinde sessizce settings.ILP_TIME_LIMIT_SN'e iniyordu.

    Davranış doğrulaması: PULP_CBC_CMD mock'lanarak timeLimit kwarg'ı yakalanır;
    0 → None ve int>0 → int eşlemesi test edilir.
    """
    import pulp

    from src.optimizer import p_median as pm

    captured: dict = {}
    _OriginalCBC = pulp.PULP_CBC_CMD   # patch öncesi referansı tut

    class _MockCmd:
        def __init__(self, *_, **kwargs):
            captured["timeLimit"] = kwargs.get("timeLimit")
            # Gerçek CBC sürücüsünü dahili olarak kullan (mesaj kapalı,
            # timeLimit'i de aynen ilet ki sınırsız=None davranışı çalışsın)
            self._delegate = _OriginalCBC(msg=0, timeLimit=kwargs.get("timeLimit"))

        # PuLP solver protokolünün küçük yüzeyi
        def actualSolve(self, prob):  # noqa: N802 (PuLP API)
            return self._delegate.actualSolve(prob)

        def solve(self, prob):
            return self.actualSolve(prob)

    monkeypatch.setattr(pulp, "PULP_CBC_CMD", _MockCmd)

    od, binalar, alanlar = _make_data(n_bina=10)

    # 0 → unlimited (None CBC'ye iletilmeli)
    coz(od, binalar, alanlar, p=2, solver="ilp", time_limit_sn=0)
    assert captured["timeLimit"] is None, (
        f"time_limit_sn=0 ile CBC'ye None geçilmeli; got {captured['timeLimit']}"
    )

    # int>0 → o değer aynen iletilir
    coz(od, binalar, alanlar, p=2, solver="ilp", time_limit_sn=120)
    assert captured["timeLimit"] == 120

    # None → default kullanılır (ILP_TIME_LIMIT_SN)
    coz(od, binalar, alanlar, p=2, solver="ilp", time_limit_sn=None)
    assert captured["timeLimit"] == pm.ILP_TIME_LIMIT_SN


def test_allow_fallback_false_raises_on_ilp_failure():
    """
    Kapasite çok yetersiz → ILP infeasible → allow_fallback=False ise
    RuntimeError vermeli (sessizce Heuristic'e düşmemeli).

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
    """allow_fallback=True (varsayılan) → ILP infeasible'da Heuristic'e düşer."""
    od, binalar, alanlar = _make_data(n_bina=20, weight=100.0, kapasite=10.0)
    sonuc = coz(
        od, binalar, alanlar, p=2,
        solver="ilp", kapasite=True,
        allow_fallback=True,
    )
    # Fallback gerçekleştiyse Heuristic dönmeli ve fallback_nedeni dolu olmalı
    assert sonuc.yontem == "Heuristic"
    assert sonuc.fallback_nedeni is not None
