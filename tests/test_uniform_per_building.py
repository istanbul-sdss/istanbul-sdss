"""
Uniform per-building nüfus tahmini testleri (Madde 1.1).

Yöntem: bina_ağırlığı = mahalle_nüfus / mahalle_bina_sayısı

Test odakları:
  1. Tek mahalle — tüm binalar eşit ağırlık alır
  2. Birden fazla mahalle — her biri kendi mahalle dağılımını korur
  3. Mahalle TÜİK'te yok → weight=NaN (downstream filtre için)
  4. Fuzzy eşleşme (Caferağa ↔ Caferaga Mh.)
  5. Casing/whitespace toleransı
  6. Mahalle kolonu eksik → ValueError
  7. Audit DataFrame yapısı
  8. _prepare_binalar entegrasyonu (footprint yok ama mahalle var)
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from src.optimizer.data_loader import (
    POP_METHOD_FOOTPRINT,
    POP_METHOD_UNIFORM,
    _prepare_binalar,
    detect_population_method,
)
from src.optimizer.population_estimator import (
    estimate_population_uniform_per_building,
)


def _make_gdf(mahalleler: list[str], with_footprint: bool = False) -> gpd.GeoDataFrame:
    """5'erli mahalle gruplarıyla minimal test GDF üret."""
    points = [Point(28.97 + i * 0.001, 41.01 + i * 0.001) for i in range(len(mahalleler))]
    data = {"mahalle": mahalleler, "geometry": points}
    if with_footprint:
        data["alan_m2"] = [100.0] * len(mahalleler)
    return gpd.GeoDataFrame(data, crs="EPSG:4326")


# ── 1. Tek mahalle ─────────────────────────────────────────────────────────
def test_single_mahalle_uniform_distribution():
    """500 kişi / 5 bina → her bina 100 kişi"""
    gdf = _make_gdf(["Caferağa"] * 5)
    mahalle_pop = pd.DataFrame({
        "mahalle_adi": ["Caferağa"],
        "nufus": [500],
    })
    weights, audit = estimate_population_uniform_per_building(gdf, mahalle_pop)

    assert weights.notna().all(), "Tüm binalar weight almalı"
    assert (weights == 100.0).all(), f"Beklenen 100, alınan {weights.tolist()}"
    assert len(audit) == 1
    assert audit.iloc[0]["bina_basi"] == 100.0
    assert audit.iloc[0]["bina_sayisi"] == 5


# ── 2. Birden fazla mahalle ────────────────────────────────────────────────
def test_multiple_mahalleler_independent_distributions():
    """Her mahalle kendi dağıtımını yapar."""
    gdf = _make_gdf(["A"] * 3 + ["B"] * 7)
    mahalle_pop = pd.DataFrame({
        "mahalle_adi": ["A", "B"],
        "nufus": [300, 1400],
    })
    weights, audit = estimate_population_uniform_per_building(gdf, mahalle_pop)

    # A binaları: 300/3 = 100
    a_mask = gdf["mahalle"] == "A"
    assert (weights[a_mask] == 100.0).all()
    # B binaları: 1400/7 = 200
    b_mask = gdf["mahalle"] == "B"
    assert (weights[b_mask] == 200.0).all()


# ── 3. Mahalle TÜİK'te yok ─────────────────────────────────────────────────
def test_missing_mahalle_yields_nan_weight():
    """Eşleşmeyen mahalle binaları NaN weight alır."""
    gdf = _make_gdf(["Bilinmeyen"] * 3)
    mahalle_pop = pd.DataFrame({
        "mahalle_adi": ["Caferağa"],
        "nufus": [500],
    })
    weights, audit = estimate_population_uniform_per_building(gdf, mahalle_pop)

    assert weights.isna().all(), "Eşleşmeyen mahalle binaları NaN olmalı"
    assert audit.iloc[0]["eslesme"] == "—"
    assert "kayıtsız" in audit.iloc[0]["durum"].lower()


# ── 4. Fuzzy eşleşme ───────────────────────────────────────────────────────
def test_fuzzy_match_typographic_variant():
    """Tipografik farklı yazımlar fuzzy ile eşleşir."""
    gdf = _make_gdf(["Zühtüpaşa"] * 4)
    mahalle_pop = pd.DataFrame({
        "mahalle_adi": ["Zühütpaşa"],   # not: hatalı yazım
        "nufus": [800],
    })
    weights, audit = estimate_population_uniform_per_building(
        gdf, mahalle_pop, fuzzy_threshold=80.0,
    )

    # Fuzzy ile yakalanmalı; her bina 200 alır
    assert weights.notna().all()
    assert (weights == 200.0).all()
    assert audit.iloc[0]["eslesme"].startswith("fuzzy:")


# ── 5. Casing & whitespace toleransı ───────────────────────────────────────
def test_casing_and_whitespace_match():
    """'  CAFERAGA  ' ile 'Caferağa' eşleşmeli (normalized cascade)."""
    gdf = _make_gdf(["Caferağa"] * 2)
    mahalle_pop = pd.DataFrame({
        "mahalle_adi": ["  CAFERAGA  "],
        "nufus": [100],
    })
    weights, audit = estimate_population_uniform_per_building(gdf, mahalle_pop)

    assert weights.notna().all()
    assert (weights == 50.0).all()


# ── 6. Mahalle kolonu eksik → hata ─────────────────────────────────────────
def test_missing_mahalle_column_raises():
    gdf = gpd.GeoDataFrame({"geometry": [Point(28.97, 41.01)]}, crs="EPSG:4326")
    mahalle_pop = pd.DataFrame({"mahalle_adi": ["A"], "nufus": [100]})
    with pytest.raises(ValueError, match="mahalle"):
        estimate_population_uniform_per_building(gdf, mahalle_pop)


def test_missing_pop_columns_raises():
    gdf = _make_gdf(["A"])
    bad_pop = pd.DataFrame({"wrong_name": ["A"], "wrong_pop": [100]})
    with pytest.raises(ValueError):
        estimate_population_uniform_per_building(gdf, bad_pop)


# ── 7. Audit DF yapısı ─────────────────────────────────────────────────────
def test_audit_columns_complete():
    gdf = _make_gdf(["A", "B"])
    mahalle_pop = pd.DataFrame({"mahalle_adi": ["A"], "nufus": [200]})
    _, audit = estimate_population_uniform_per_building(gdf, mahalle_pop)

    expected_cols = {"mahalle", "bina_sayisi", "tuik_nufus", "bina_basi",
                     "eslesme", "durum"}
    assert expected_cols.issubset(set(audit.columns))
    # Her mahalle için bir satır
    assert len(audit) == 2
    assert set(audit["mahalle"].tolist()) == {"A", "B"}


# ── 8. _prepare_binalar entegrasyonu ───────────────────────────────────────
def test_prepare_binalar_uniform_mode():
    """End-to-end: footprint olmayan veri + TÜİK ile uniform mod."""
    gdf = _make_gdf(["Caferağa", "Caferağa", "Caferağa"])  # footprint yok
    mahalle_pop = pd.DataFrame({"mahalle_adi": ["Caferağa"], "nufus": [600]})

    out = _prepare_binalar(
        gdf,
        population_method=POP_METHOD_UNIFORM,
        mahalle_pop=mahalle_pop,
    )

    assert len(out) == 3
    assert (out["weight"] == 200.0).all(), f"Beklenen 200, alınan {out['weight'].tolist()}"
    assert (out["nufus_kaynak"] == "uniform_per_building").all()
    assert out.attrs["population_method"] == POP_METHOD_UNIFORM


def test_prepare_binalar_uniform_requires_mahalle_pop():
    """Uniform mod mahalle_pop olmadan hata vermeli."""
    gdf = _make_gdf(["A"])
    with pytest.raises(ValueError, match="uniform"):
        _prepare_binalar(gdf, population_method=POP_METHOD_UNIFORM)


def test_prepare_binalar_footprint_mode_unchanged():
    """Footprint mode'da mevcut davranış korunur (regresyon koruması)."""
    gdf = _make_gdf(["A"] * 2, with_footprint=True)
    out = _prepare_binalar(gdf, population_method=POP_METHOD_FOOTPRINT)
    # weight > 0 (formül uygulanmış)
    assert (out["weight"] > 0).all()
    assert (out["nufus_kaynak"] == "footprint_based").all()


def test_prepare_binalar_uniform_missing_mahalle_dropped():
    """
    Uniform modda mahalle TÜİK'te yoksa o satırlar optimizasyon dışı
    bırakılır (drop) — bilgi attrs.dropped_missing_weight* alanlarına
    taşınır. Aksi halde NaN weight optimizer'da cost'u kirletir.
    """
    gdf = _make_gdf(["A", "B"])
    mahalle_pop = pd.DataFrame({"mahalle_adi": ["A"], "nufus": [100]})

    out = _prepare_binalar(
        gdf,
        population_method=POP_METHOD_UNIFORM,
        mahalle_pop=mahalle_pop,
    )
    # Yalnızca A binası kaldı
    assert len(out) == 1
    assert out["mahalle"].iloc[0] == "A"
    assert out["nufus_kaynak"].iloc[0] == "uniform_per_building"
    assert out["weight"].iloc[0] == 100.0  # A mahallesinde 1 bina, TÜİK=100 → 100/1=100

    # B düşürüldü, attrs'a yansıdı
    assert out.attrs["dropped_missing_weight_count"] == 1
    dropped = out.attrs["dropped_missing_weight"]
    assert len(dropped) == 1
    assert dropped["mahalle"].iloc[0] == "B"
    assert dropped["nufus_kaynak"].iloc[0] == "uniform_missing_mahalle"


# ── Auto-detect ────────────────────────────────────────────────────────────
def test_detect_population_method_with_footprint():
    """Footprint kolonu var ve dolu ise footprint_based önerilir."""
    gdf = _make_gdf(["A"] * 3, with_footprint=True)
    assert detect_population_method(gdf) == POP_METHOD_FOOTPRINT


def test_detect_population_method_without_footprint():
    """Footprint kolonu yok ise uniform önerilir."""
    gdf = _make_gdf(["A"] * 3, with_footprint=False)
    assert detect_population_method(gdf) == POP_METHOD_UNIFORM


def test_detect_population_method_all_zero_footprint():
    """Footprint kolonu var ama tüm satırlar 0 → uniform önerilir."""
    gdf = _make_gdf(["A"] * 3)
    gdf["alan_m2"] = 0.0
    assert detect_population_method(gdf) == POP_METHOD_UNIFORM
