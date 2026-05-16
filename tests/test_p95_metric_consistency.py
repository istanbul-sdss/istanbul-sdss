"""
P95 metriği tutarlılık testleri (Faz 2 sonrası — kritik bug fix).

Bulgu: Önceden `PMedianResult.p95_sure_dk` `np.percentile(sureler, 95)`
ile bina-bazlı (ağırlıksız) hesaplanıyordu; ancak `min_p95` modunda
optimizer `_weighted_percentile(sureler, weights, 95)` ile nüfus-ağırlıklı
p95'i optimize ediyordu. İki farklı metrik → karar verici tutarsız sayılar
gördü; min_p95 modunun akademik anlamı (nüfus-ağırlıklı outlier-robust
fairness) raporda kaybolmuştu.

Düzeltme: `p95_sure_dk` artık nüfus-ağırlıklı; ek olarak ağırlıksız değer
`p95_bina_sure_dk` informasyonel yan alanda taşınır.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from src.optimizer.p_median import (
    P95_PERCENTILE,
    _weighted_percentile,
    coz,
)


def _build_skewed_problem():
    """
    Karşı örnek senaryo: Az sayıda BÜYÜK NÜFUSLU bina yakın, çok sayıda
    KÜÇÜK NÜFUSLU bina uzak.

      - 2 bina: weight=1000 her biri (toplam 2000 kişi), 0-2 dk uzaklıkta
      - 8 bina: weight=10 her biri (toplam 80 kişi), 50 dk uzaklıkta

    Ağırlıksız bina-bazlı p95 → 50 dk civarı (8 uzak binadan birini hit)
    Ağırlıklı nüfus-bazlı p95 → 2 dk civarı (nüfusun %95'i yakın 2 binada)

    İki sayı arasındaki fark net bir karşı örnek üretir.
    """
    n_close, n_far = 2, 8
    n_bina = n_close + n_far
    # Tek alan; p=1 zorlanır. Aday alan sayısı OD shape'inden anlaşılır.

    weights = np.array([1000.0] * n_close + [10.0] * n_far)
    times   = np.array([1.0] * n_close + [50.0] * n_far)

    od = times.reshape(-1, 1).astype(np.float32)

    binalar = gpd.GeoDataFrame({
        "weight":        weights,
        "mahalle":       ["A"] * n_bina,
        "alan_m2":       [100.0] * n_bina,
        "levels":        [3] * n_bina,
        "name":          [f"B{i}" for i in range(n_bina)],
        "bina_etiketi":  [f"Bina {i+1}" for i in range(n_bina)],
        "geometry":      [Point(28.97 + i*0.001, 41.01) for i in range(n_bina)],
    }, crs="EPSG:4326")

    toplanma = gpd.GeoDataFrame({
        "ad":       ["A1"],
        "area_m2":  [10000.0],
        "kapasite": [5000],
        "geometry": [Point(28.97, 41.02)],
    }, crs="EPSG:4326")

    return od, binalar, toplanma, weights, times


# ── 1. p95_sure_dk artık nüfus-ağırlıklı ──────────────────────────────────
def test_p95_sure_dk_is_population_weighted():
    """
    Karşı örnekte rapor edilen `p95_sure_dk` nüfus-ağırlıklı olmalı —
    nüfusun %95'i yakın binalarda, dolayısıyla p95 değeri DÜŞÜK çıkmalı
    (50 dk uzak binalar nüfus yönünden marjinal).
    """
    od, b, t, weights, times = _build_skewed_problem()
    sonuc = coz(od, b, t, p=1, kapasite=False, amac="min_p95")

    # Manuel ağırlıklı p95 hesabı (referans)
    expected_weighted_p95 = _weighted_percentile(times, weights, P95_PERCENTILE)

    # Rapor edilen p95 ağırlıklı versiyona ÇOK YAKIN olmalı (tolerans float)
    assert abs(sonuc.p95_sure_dk - expected_weighted_p95) < 1e-6, (
        f"p95_sure_dk={sonuc.p95_sure_dk} ağırlıklı versiyondan "
        f"({expected_weighted_p95}) sapıyor — rapor hâlâ ağırlıksız mı?"
    )


def test_p95_diverges_from_unweighted_in_skewed_case():
    """
    Karşı örnekte ağırlıklı ve ağırlıksız p95 BELİRGİN ŞEKİLDE farklı
    olmalı — bu, raporun hangi metriği kullandığının önemli olduğunu
    doğrular. Aksi halde "fark yoksa tutarlılık sorunu da yok" diye
    yanlış sonuca varılabilir.
    """
    _, _, _, weights, times = _build_skewed_problem()
    weighted = _weighted_percentile(times, weights, P95_PERCENTILE)
    unweighted = float(np.percentile(times, 95))

    # Karşı örnekte fark 10+ dk olmalı
    assert abs(weighted - unweighted) > 10.0, (
        f"Karşı örnek anlamlı bir fark üretmiyor: "
        f"weighted={weighted}, unweighted={unweighted}"
    )
    # Yön: nüfus yakın binalarda toplandığı için ağırlıklı DAHA DÜŞÜK
    assert weighted < unweighted


# ── 2. p95_bina_sure_dk ağırlıksız bina-bazlı versiyonu taşır ─────────────
def test_p95_bina_sure_dk_is_unweighted():
    """
    `p95_bina_sure_dk` informasyonel ağırlıksız değer olmalı —
    `np.percentile(sureler, 95)` ile aynı (her bina eşit ağırlık).
    """
    od, b, t, _, times = _build_skewed_problem()
    sonuc = coz(od, b, t, p=1, kapasite=False, amac="min_p95")

    expected_unweighted = float(np.percentile(times, 95))
    assert abs(sonuc.p95_bina_sure_dk - expected_unweighted) < 1e-6, (
        f"p95_bina_sure_dk={sonuc.p95_bina_sure_dk} bina-bazlı "
        f"({expected_unweighted})'den sapıyor"
    )


# ── 3. Eşit ağırlıklı senaryoda iki p95 aynı olmalı ──────────────────────
def test_p95_equals_when_weights_uniform():
    """
    Tüm binalar eşit ağırlıklı ise ağırlıklı ve ağırlıksız p95 aynı
    değeri verir (sanity check — _weighted_percentile'ın uniform
    durumda np.percentile ile uyumu).
    """
    n = 20
    od = np.linspace(1, 30, n, dtype=np.float32).reshape(-1, 1)
    weights = np.ones(n) * 100

    binalar = gpd.GeoDataFrame({
        "weight":       weights,
        "mahalle":      ["A"] * n,
        "alan_m2":      [100.0] * n,
        "levels":       [3] * n,
        "name":         [f"B{i}" for i in range(n)],
        "bina_etiketi": [f"Bina {i+1}" for i in range(n)],
        "geometry":     [Point(28.97 + i*0.001, 41.01) for i in range(n)],
    }, crs="EPSG:4326")
    toplanma = gpd.GeoDataFrame({
        "ad":       ["A1"],
        "area_m2":  [10000.0],
        "kapasite": [3000],
        "geometry": [Point(28.97, 41.02)],
    }, crs="EPSG:4326")

    sonuc = coz(od, binalar, toplanma, p=1, kapasite=False, amac="min_p95")

    # Eşit ağırlıkta ikisi de yaklaşık aynı olmalı (lower interpolation
    # vs linear küçük farkı tolere et)
    assert abs(sonuc.p95_sure_dk - sonuc.p95_bina_sure_dk) < 2.0, (
        f"Uniform ağırlıkta p95'ler çok ayrı: "
        f"weighted={sonuc.p95_sure_dk}, bina={sonuc.p95_bina_sure_dk}"
    )


# ── 4. Sensitivity (duyarlilik_analizi) iki ayrı kolonu raporluyor ────────
def test_sensitivity_analysis_reports_both_p95():
    """
    `duyarlilik_analizi` çıktısında hem ağırlıklı hem ağırlıksız p95
    sütunu olmalı — kullanıcı raporda hangisinin gösterildiğini
    açıkça görebilsin.
    """
    from src.optimizer.p_median import duyarlilik_analizi
    od, b, t, _, _ = _build_skewed_problem()
    df = duyarlilik_analizi(
        od, b, t, p_aralik=range(1, 2),
        kapasite=False, amac="min_p95",
    )
    cols = set(df.columns)
    assert "P95 Süre (dk, nüfus-ağırlıklı)" in cols, (
        f"Ağırlıklı p95 sütunu eksik. Mevcut: {cols}"
    )
    assert "P95 Süre (dk, bina-bazlı)" in cols, (
        f"Bina-bazlı p95 sütunu eksik. Mevcut: {cols}"
    )
