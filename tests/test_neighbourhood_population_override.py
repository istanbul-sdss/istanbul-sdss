"""
Regresyon: Mahalle bazlı nüfus override.

Audit gereksinimi: footprint × kat × katsayı yaklaşımı tek başına
sistematik bias taşır (DEFAULT_LEVELS, ticari/ofis binası ayrımı yok).
TÜİK mahalle nüfus dosyası yüklendiğinde, footprint dağılımı *anahtar*
olarak korunur ama mahalle toplamı TÜİK'e kalibre edilir.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point

from src.optimizer.population_estimator import apply_neighbourhood_population_override


def _make_binalar(weights_by_mahalle):
    """{mahalle: [bina ağırlıkları]} → GeoDataFrame."""
    rows = []
    for mah, ws in weights_by_mahalle.items():
        for i, w in enumerate(ws):
            rows.append({
                "weight": float(w),
                "mahalle": mah,
                "geometry": Point(29.0 + i * 0.001, 41.0),
            })
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


def test_total_matches_tuik_after_calibration():
    """Mahalle toplamı TÜİK nüfusuna eşitlenmeli."""
    binalar = _make_binalar({"Acıbadem": [10, 20, 70], "Kozyatağı": [50, 50]})
    mahalle_pop = pd.DataFrame({
        "mahalle_adi": ["Acıbadem", "Kozyatağı"],
        "nufus": [1000, 500],
    })
    cal, audit = apply_neighbourhood_population_override(binalar, mahalle_pop)

    acibadem_sum = cal.loc[cal["mahalle"] == "Acıbadem", "weight"].sum()
    kozyatagi_sum = cal.loc[cal["mahalle"] == "Kozyatağı", "weight"].sum()
    assert abs(acibadem_sum - 1000.0) < 0.01
    assert abs(kozyatagi_sum - 500.0) < 0.01


def test_internal_distribution_preserved():
    """
    Mahalle içi binalar arası ORAN korunmalı.
    Acıbadem: [10, 20, 70] = 100 toplam → TÜİK 1000 → ölçek 10×.
    Yeni: [100, 200, 700].
    """
    binalar = _make_binalar({"Acıbadem": [10, 20, 70]})
    mahalle_pop = pd.DataFrame({
        "mahalle_adi": ["Acıbadem"],
        "nufus": [1000],
    })
    cal, _ = apply_neighbourhood_population_override(binalar, mahalle_pop)
    weights = cal["weight"].values
    np.testing.assert_allclose(weights, [100, 200, 700])


def test_unknown_mahalle_keeps_original_weight():
    """TÜİK'te olmayan mahalleler estimated olarak korunmalı."""
    binalar = _make_binalar({"Acıbadem": [50], "Bilinmeyen": [25]})
    mahalle_pop = pd.DataFrame({
        "mahalle_adi": ["Acıbadem"],
        "nufus": [200],
    })
    cal, audit = apply_neighbourhood_population_override(binalar, mahalle_pop)

    bilinmeyen = cal.loc[cal["mahalle"] == "Bilinmeyen", "weight"].iloc[0]
    assert bilinmeyen == 25.0
    assert cal.loc[cal["mahalle"] == "Bilinmeyen", "nufus_kaynak"].iloc[0] == "estimated"

    # Acıbadem kalibre edilmeli
    assert cal.loc[cal["mahalle"] == "Acıbadem", "nufus_kaynak"].iloc[0] == "neighbourhood_calibrated"


def test_case_insensitive_mahalle_match():
    """
    Mahalle adı eşleşmesi büyük/küçük harf farkına dayanıklı olmalı
    (whitespace + casing). Türkçe i/ı/İ/I normalizasyonu ayrı bir konu —
    burada aynı yazım için kasing test ediliyor.

    İki ayrı senaryo: (1) baştaki/sondaki whitespace + büyük harf,
    (2) sadece büyük harf farkı. İkisinde de aynı sonuç beklenir.
    """
    # Senaryo 1: TÜİK adı whitespace+uppercase, bina adı normal yazım
    binalar = _make_binalar({"Acıbadem": [100]})
    mahalle_pop = pd.DataFrame({
        "mahalle_adi": ["  ACIBADEM  "],   # baştaki boşluklar + büyük harf
        "nufus": [500],
    })
    cal1, _ = apply_neighbourhood_population_override(binalar, mahalle_pop)
    assert cal1["weight"].iloc[0] == 500.0, (
        "whitespace+uppercase TÜİK adı normal-yazım bina mahallesi ile eşleşmeli"
    )

    # Senaryo 2: aynı yazımla casing'i değiştir
    binalar2 = _make_binalar({"acibadem": [100]})   # not: ASCII i
    pop2 = pd.DataFrame({"mahalle_adi": ["ACIBADEM"], "nufus": [500]})
    cal2, _ = apply_neighbourhood_population_override(binalar2, pop2)
    assert cal2["weight"].iloc[0] == 500.0


def test_audit_df_reports_each_mahalle():
    """Audit DF her mahalle için bir satır içermeli."""
    binalar = _make_binalar({"A": [10], "B": [20], "C": [30]})
    mahalle_pop = pd.DataFrame({
        "mahalle_adi": ["A", "B"],
        "nufus": [100, 200],
    })
    cal, audit = apply_neighbourhood_population_override(binalar, mahalle_pop)
    assert len(audit) == 3
    assert set(audit["mahalle"].tolist()) == {"A", "B", "C"}

    # C için tuik_nufus None, durum açıklayıcı olmalı
    c_row = audit[audit["mahalle"] == "C"].iloc[0]
    assert c_row["tuik_nufus"] is None or pd.isna(c_row["tuik_nufus"])


def test_zero_estimate_with_tuik_skips_calibration():
    """
    Mahalle toplam tahmini 0 ise (örn. footprint kolonu yok), TÜİK'e
    ölçekleme matematiksel olarak imkansız → durum mesajı net olmalı.
    """
    binalar = _make_binalar({"Bos": [0, 0]})
    mahalle_pop = pd.DataFrame({
        "mahalle_adi": ["Bos"],
        "nufus": [500],
    })
    cal, audit = apply_neighbourhood_population_override(binalar, mahalle_pop)
    assert cal["weight"].sum() == 0.0
    assert "ölçeklenemez" in audit["durum"].iloc[0].lower() or "sıfır" in audit["durum"].iloc[0].lower()


def test_missing_mahalle_column_raises():
    """`mahalle` kolonu yoksa açık hata vermeli."""
    binalar = gpd.GeoDataFrame(
        {"weight": [10.0], "geometry": [Point(29, 41)]},
        crs="EPSG:4326",
    )
    mahalle_pop = pd.DataFrame({"mahalle_adi": ["X"], "nufus": [100]})
    with pytest.raises(ValueError, match="mahalle"):
        apply_neighbourhood_population_override(binalar, mahalle_pop)


def test_missing_pop_columns_raises():
    """mahalle_pop'ta beklenen kolonlar yoksa açık hata vermeli."""
    binalar = _make_binalar({"X": [10]})
    bad_pop = pd.DataFrame({"name": ["X"], "value": [100]})
    with pytest.raises(ValueError, match="mahalle_adi|nufus"):
        apply_neighbourhood_population_override(binalar, bad_pop)
