"""
Regresyon (B4): CBC time-limit aşımında feasible-ama-optimal-değil çözüm
korunmalı; K-Medoids'e sessizce düşmemeli.

Önceki davranış: `_coz_ilp` yalnızca `prob.status == 1` (Optimal) durumunu
kabul ediyordu. Time-limit aşımında PuLP `prob.status = 0` (NotSolved)
döndürür AMA CBC çoğu zaman bulduğu en iyi integer-feasible çözümü saklar;
PuLP 2.5+ bunu `prob.sol_status = 2` (LpSolutionIntegerFeasible) ile
sinyalliyor. Eski kod o çözümü atıp sıfırdan K-Medoids koşturuyordu —
gereksiz iş + kullanıcının optimizer çıktısı kalitesi gerçekte CBC'den
daha kötü olabiliyordu.

Yeni davranış: status=NotSolved + sol_status=IntegerFeasible birlikte
gözlenirse, CBC değişken değerlerini kullanarak normal `_build_result`
yolu üzerinden ILP yöntem olarak dön; `ilp_status = "Feasible (time
limit)"` ile bunun proven-optimal olmayan bir çözüm olduğu UI'da görünür.

Test stratejisi: gerçek CBC'ye bu durumu deterministik tetiklemek zor
(time-limit + problem zorluğunun tam dengelenmesi gerek). Onun yerine
küçük tractable bir problemi gerçek CBC ile çözüyoruz (değişkenler tamamen
populate olur), sonra prob.status / prob.sol_status'u monkey-patch ile
time-limit senaryosuna eşitliyoruz. Bu, fix'in extraction-yoluna gittiğini
ve doğru etiket bastığını ispatlamak için yeterli.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point

from src.optimizer.p_median import coz


def _make_data(n_bina=20, n_alan=4, weight=10.0, kapasite=200.0):
    np.random.seed(0)
    binalar = gpd.GeoDataFrame(
        {
            "weight":       [weight] * n_bina,
            "mahalle":      ["M"] * n_bina,
            "alan_m2":      [100.0] * n_bina,
            "levels":       [3] * n_bina,
            "bina_etiketi": [f"B{i}" for i in range(n_bina)],
            "geometry":     [
                Point(29.0 + (i % 5) * 0.001, 41.0 + (i // 5) * 0.001)
                for i in range(n_bina)
            ],
        },
        crs="EPSG:4326",
    )
    alanlar = gpd.GeoDataFrame(
        {
            "ad":        [f"A{j}" for j in range(n_alan)],
            "kapasite":  [kapasite] * n_alan,
            "geometry":  [Point(29.001 + j * 0.002, 41.001) for j in range(n_alan)],
        },
        crs="EPSG:4326",
    )
    od = np.random.uniform(2.0, 15.0, size=(n_bina, n_alan)).astype(np.float32)
    return od, binalar, alanlar


def _patch_solve_to_simulate_time_limit(monkeypatch):
    """
    pulp.LpProblem.solve'u sar: önce gerçek çözücüyü koştur (değişkenler
    populate olsun), sonra prob.status=0 (NotSolved) + sol_status=2
    (IntegerFeasible) yaparak time-limit-feasible senaryosunu taklit et.
    """
    import pulp

    original_solve = pulp.LpProblem.solve

    def fake_solve(self, *args, **kwargs):
        ret = original_solve(self, *args, **kwargs)
        # Time-limit case taklit: değişkenler dolu ama optimal olduğu
        # kanıtlanmamış gibi davran.
        self.status = 0       # LpStatusNotSolved
        self.sol_status = 2   # LpSolutionIntegerFeasible
        return ret

    monkeypatch.setattr(pulp.LpProblem, "solve", fake_solve)


def test_time_limit_feasible_solution_kept_not_fallback(monkeypatch):
    """
    Time-limit'te feasible bulunduysa K-Medoids fallback'e gitmemeli;
    CBC çözümü ILP yöntem etiketiyle dönmeli.
    """
    _patch_solve_to_simulate_time_limit(monkeypatch)
    od, binalar, alanlar = _make_data(n_bina=20)

    sonuc = coz(od, binalar, alanlar, p=2, solver="ilp", amac="min_sum")

    # K-Medoids'e düşmemiş olmalı
    assert sonuc.yontem == "ILP", (
        f"Time-limit feasible çözüm kaybolup K-Medoids'e düşülmüş — fix gerilemiş. "
        f"yontem={sonuc.yontem!r}, ilp_status={sonuc.ilp_status!r}"
    )
    # fallback_nedeni dolmamış olmalı (K-Medoids fallback işareti)
    assert sonuc.fallback_nedeni is None, (
        f"fallback_nedeni doldu: {sonuc.fallback_nedeni!r} — "
        f"K-Medoids yoluna girilmiş demektir."
    )
    # ilp_status etiketi "Feasible (time limit)" olmalı, downstream UI bunu
    # "not-proven-optimal" olarak gösterebilsin.
    assert sonuc.ilp_status == "Feasible (time limit)", (
        f"ilp_status yanlış: {sonuc.ilp_status!r}; beklenen 'Feasible (time limit)'."
    )
    # Sonuçlar tutarlı olmalı — atamalar tüm binaları kapsamalı
    assert len(sonuc.atamalar) == 20
    assert len(sonuc.acik_alanlar) == 2


def test_time_limit_feasible_respects_allow_fallback_false(monkeypatch):
    """
    allow_fallback=False bile olsa feasible çözüm varsa hatasız dönmeli —
    çünkü ILP gerçekten feasible bir sonuç verdi; "fallback" yok.
    Bu, B4 değişikliğinin allow_fallback semantiğini koruduğunu gösterir.
    """
    _patch_solve_to_simulate_time_limit(monkeypatch)
    od, binalar, alanlar = _make_data(n_bina=20)

    sonuc = coz(
        od, binalar, alanlar, p=2,
        solver="ilp", amac="min_sum",
        allow_fallback=False,
    )
    assert sonuc.yontem == "ILP"
    assert sonuc.ilp_status == "Feasible (time limit)"


def test_no_feasible_solution_still_falls_back(monkeypatch):
    """
    sol_status=0 (No Solution Found) + status=0 (NotSolved) durumunda
    eski fallback davranışı korunmalı — fix bu yolu kırmamış olmalı.
    """
    import pulp

    original_solve = pulp.LpProblem.solve

    def fake_solve(self, *args, **kwargs):
        ret = original_solve(self, *args, **kwargs)
        self.status = 0
        self.sol_status = 0   # No Solution Found
        return ret

    monkeypatch.setattr(pulp.LpProblem, "solve", fake_solve)
    od, binalar, alanlar = _make_data(n_bina=20)

    sonuc = coz(od, binalar, alanlar, p=2, solver="ilp", amac="min_sum")

    # K-Medoids fallback'e düşmeli
    assert sonuc.yontem == "K-Medoids"
    assert sonuc.fallback_nedeni is not None
    assert "time limit" in sonuc.fallback_nedeni.lower()


def test_optimal_path_unchanged_by_b4(monkeypatch):
    """
    Optimal durumda (status=1) hiçbir davranış değişmemeli.
    Bu, B4 değişikliğinin happy-path'i bozmadığını ispatlar.
    """
    od, binalar, alanlar = _make_data(n_bina=20)
    sonuc = coz(od, binalar, alanlar, p=2, solver="ilp", amac="min_sum")

    assert sonuc.yontem == "ILP"
    assert sonuc.ilp_status == "Optimal"
    assert sonuc.fallback_nedeni is None


def test_missing_sol_status_attribute_falls_through(monkeypatch):
    """
    Çok eski PuLP'lerde `prob.sol_status` yoksa fix güvenle eski davranışa
    döner: status=0 → fallback. Defansif `getattr` kontrolü.
    """
    import pulp

    original_solve = pulp.LpProblem.solve

    def fake_solve(self, *args, **kwargs):
        import contextlib
        ret = original_solve(self, *args, **kwargs)
        self.status = 0
        # sol_status'u SİL — eski PuLP simülasyonu
        if hasattr(self, "sol_status"):
            with contextlib.suppress(AttributeError):
                del self.sol_status
        return ret

    monkeypatch.setattr(pulp.LpProblem, "solve", fake_solve)
    od, binalar, alanlar = _make_data(n_bina=20)

    sonuc = coz(od, binalar, alanlar, p=2, solver="ilp", amac="min_sum")

    # sol_status yoksa eski yol — K-Medoids fallback
    assert sonuc.yontem == "K-Medoids"
    assert sonuc.fallback_nedeni is not None


@pytest.mark.parametrize("amac", ["min_sum", "min_max"])
def test_feasible_path_works_for_both_objectives(monkeypatch, amac):
    """min_sum ve min_max her ikisinde de feasible time-limit yolu çalışmalı."""
    _patch_solve_to_simulate_time_limit(monkeypatch)
    od, binalar, alanlar = _make_data(n_bina=20)
    sonuc = coz(od, binalar, alanlar, p=2, solver="ilp", amac=amac)
    assert sonuc.yontem == "ILP"
    assert sonuc.amac == amac
    assert sonuc.ilp_status == "Feasible (time limit)"
