"""
R5 regresyon: K-Medoids convergence şeffaflığı.

Bulgu: K-Medoids 1-swap local search heuristic'i lokal optimuma yakınsamayı
matematiksel olarak garanti etmez — MAX_ITER limitine takılabilir. Önceki
davranış: takılma yalnızca process log'una düşüyor, sonuç KPI'larıyla
"certified" sonuç arasında fark yok → kullanıcı/jüri sonucun kalitesini
inceleme zorluğu.

Düzeltme: `PMedianResult.kmedoids_converged` (bool | None) +
`kmedoids_iterations` (int | None) alanları ile üç durumlu ayrım:
  • True  → no improving swap found (certified locally optimal)
  • False → MAX_ITER hit (best-found, NOT certified)
  • None  → ILP path (convergence kavramı farklı — ilp_status taşır)

Test kapsamı:
  1. Normal yakınsama → converged=True, iterations<MAX_ITER
  2. MAX_ITER=1 monkeypatch → converged=False, iterations=1
  3. ILP path → converged=None, iterations=None
  4. p == n_alan edge case → anında yakınsama (tek seçim)
  5. min_p95 amacı (her zaman K-Med) → convergence raporlanır
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point

from src.optimizer import p_median as pm
from src.optimizer.p_median import KMEDOIDS_MAX_ITER, coz


def _make_small_problem(n_bina: int = 6, n_alan: int = 4):
    """3 saha + 6 bina küçük problem — hızlı convergence için."""
    rng = np.random.RandomState(42)
    # OD matrisi — random ama mantıklı aralık (1-30 dk)
    od = rng.uniform(1.0, 30.0, size=(n_bina, n_alan)).astype(np.float32)

    binalar = gpd.GeoDataFrame({
        "weight":       np.ones(n_bina) * 100,
        "mahalle":      ["A"] * n_bina,
        "alan_m2":      [100.0] * n_bina,
        "levels":       [3] * n_bina,
        "name":         [f"B{i}" for i in range(n_bina)],
        "bina_etiketi": [f"Bina {i+1}" for i in range(n_bina)],
        "geometry":     [Point(28.97 + i*0.001, 41.01) for i in range(n_bina)],
    }, crs="EPSG:4326")

    toplanma = gpd.GeoDataFrame({
        "ad":       [f"A{j+1}" for j in range(n_alan)],
        "area_m2":  [10000.0] * n_alan,
        "kapasite": [5000] * n_alan,
        "geometry": [Point(28.97 + j*0.002, 41.02) for j in range(n_alan)],
    }, crs="EPSG:4326")

    return od, binalar, toplanma


# ── 1. Normal yakınsama → converged=True ──────────────────────────────────
def test_kmedoids_normal_convergence_reported():
    """
    Normal küçük problem: local search 1-swap mahallesinde improving
    bulamadığı ana kadar koşar. Çok hızlı yakınsamalı.
    """
    od, b, t = _make_small_problem(n_bina=6, n_alan=4)
    sonuc = coz(od, b, t, p=2, kapasite=False, solver="kmedoids")

    # Convergence raporlanmalı: True
    assert sonuc.kmedoids_converged is True, (
        f"Normal problemde converged=True beklenirdi; "
        f"got {sonuc.kmedoids_converged}"
    )
    # Iteration count makul olmalı (1-30 arası)
    assert sonuc.kmedoids_iterations is not None
    assert 1 <= sonuc.kmedoids_iterations < KMEDOIDS_MAX_ITER, (
        f"Iteration count beklenmeyen aralıkta: "
        f"{sonuc.kmedoids_iterations} (MAX_ITER={KMEDOIDS_MAX_ITER})"
    )


# ── 2. MAX_ITER hit → converged=False ─────────────────────────────────────
def test_kmedoids_max_iter_hit_reported(monkeypatch):
    """
    `KMEDOIDS_MAX_ITER` 1'e indirilirse her problem zorlama olarak
    takılı sayılır — local search ilk turda durur. converged=False
    olarak raporlanmalı.
    """
    monkeypatch.setattr(pm, "KMEDOIDS_MAX_ITER", 1)

    od, b, t = _make_small_problem(n_bina=8, n_alan=5)
    sonuc = coz(od, b, t, p=3, kapasite=False, solver="kmedoids")

    # MAX_ITER=1 ile zorlanmış takılma
    assert sonuc.kmedoids_converged is False, (
        f"MAX_ITER=1 ile converged=False bekleniyordu; "
        f"got {sonuc.kmedoids_converged}"
    )
    # Iteration tam olarak MAX_ITER kadar
    assert sonuc.kmedoids_iterations == 1


# ── 3. ILP path → her iki alan None ───────────────────────────────────────
def test_ilp_path_returns_none_for_convergence():
    """
    ILP yolundan dönen sonuç convergence alanlarını None bırakmalı —
    PuLP/CBC için convergence kavramı `ilp_status` ile ayrı raporlanır.
    """
    od, b, t = _make_small_problem(n_bina=5, n_alan=3)
    sonuc = coz(od, b, t, p=2, kapasite=False, solver="ilp", amac="min_sum")

    # ILP yontemiyle çözüldü
    assert sonuc.yontem == "ILP"
    # Convergence alanları None (K-Med'e özgü)
    assert sonuc.kmedoids_converged is None, (
        f"ILP path'te kmedoids_converged=None beklenirdi; "
        f"got {sonuc.kmedoids_converged}"
    )
    assert sonuc.kmedoids_iterations is None
    # Bunun yerine ilp_status doldurulmuş olmalı
    assert sonuc.ilp_status is not None


# ── 4. p == n_alan edge case → anında yakınsama ──────────────────────────
def test_kmedoids_p_equals_n_alan_converges_immediately():
    """
    Eğer tüm aday alanları açıyorsak swap için aday yok → local search
    hemen converge eder (zaten 0 iterasyon ile). Edge case.
    """
    od, b, t = _make_small_problem(n_bina=5, n_alan=3)
    # p = n_alan
    sonuc = coz(od, b, t, p=3, kapasite=False, solver="kmedoids")

    assert sonuc.kmedoids_converged is True, (
        "p==n_alan edge case'inde immediate convergence beklenirdi"
    )
    # 1 turda gelisim=False olmalı (swap aday kümesi boş)
    assert sonuc.kmedoids_iterations is not None
    assert sonuc.kmedoids_iterations <= 2, (
        f"p==n_alan'da {sonuc.kmedoids_iterations} iter — beklenmedik kadar fazla"
    )


# ── 5. min_p95 amacı (zorla K-Med) → convergence raporlanır ──────────────
def test_min_p95_objective_reports_convergence():
    """
    min_p95 hedefi ILP'de çözülemez (non-linear), K-Med'e zorlanır.
    Convergence raporlaması bu yolda da çalışmalı.
    """
    od, b, t = _make_small_problem(n_bina=8, n_alan=5)
    sonuc = coz(od, b, t, p=2, kapasite=False, amac="min_p95", solver="auto")

    # auto + min_p95 → K-Med'e gider
    assert sonuc.yontem == "K-Medoids"
    # Convergence raporlanmalı
    assert sonuc.kmedoids_converged is not None, (
        "K-Med yolundan dönen sonuç kmedoids_converged'ı set etmeli"
    )
    assert sonuc.kmedoids_iterations is not None


# ── 6. Dataclass field default'ları geriye uyumlu ─────────────────────────
def test_pmedian_result_default_fields():
    """
    PMedianResult'a manuel constructor çağrısı (örn. test fixture'larında)
    yeni alanları default=None ile alabilmeli — backward-compat.
    """
    from src.optimizer.p_median import PMedianResult
    # Minimum gerekli pozisyonel alanlar — kalan her şey default
    r = PMedianResult(
        atamalar=__import__("pandas").DataFrame(),
        acik_alanlar=[],
        acik_alan_adlari=[],
        toplam_agirlikli_sure=0.0,
        ort_sure_dk=0.0,
        agirlikli_ort_sure_dk=0.0,
        max_sure_dk=0.0,
        p95_sure_dk=0.0,
        kapsama_5dk_pct=0.0,
        kapsama_10dk_pct=0.0,
        kapsama_30dk_pct=0.0,
        nufus_kapsama_5dk_pct=0.0,
        nufus_kapsama_10dk_pct=0.0,
        nufus_kapsama_30dk_pct=0.0,
    )
    # Default'lar None
    assert r.kmedoids_converged is None
    assert r.kmedoids_iterations is None
