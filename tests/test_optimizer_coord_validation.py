"""
Regresyon (P1.3): Optimizer'ın `_df_to_gdf` fonksiyonu eksik koordinatları,
WGS84 aralığı dışı değerleri ve `(0,0)` sentinel'ını eler; ardışık OD
matris adımı bunlara takılmaz.

Audit bulgusu: Önceki davranış sadece `dropna(subset=[lat, lon])` yapıyordu.
WGS84 aralık kontrolü, İstanbul bbox kontrolü, `(0,0)` sentinel kontrolü
yoktu. Sonuç: bozuk koordinatlar `ox.nearest_nodes` ile graf üzerindeki en
yakın node'a snap ediliyor → karar destek raporunda hayalet binalar.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.optimizer.data_loader import _df_to_gdf


def test_missing_lat_or_lon_column_raises():
    df = pd.DataFrame({"Boylam": [29.0]})
    with pytest.raises(ValueError, match="Enlem|atitude"):
        _df_to_gdf(df)


def test_invalid_range_coords_dropped():
    df = pd.DataFrame({
        "Enlem":  [41.0,  91.0,  -91.0,   45.0],   # 91/-91 aralık dışı
        "Boylam": [29.0,  29.0,  29.0,    181.0],  # 181 aralık dışı
        "ad":     ["ok",  "lat+", "lat-",  "lon+"],
    })
    out = _df_to_gdf(df)
    assert len(out) == 1
    assert out.iloc[0]["ad"] == "ok"


def test_zero_zero_sentinel_dropped():
    """
    (0,0) Atlantic Ocean'a düşer; veri temizliği bunu sentinel kabul eder.
    Önceden snap edilip "geçerli bina" gibi davranıyordu.
    """
    df = pd.DataFrame({
        "Enlem":  [41.0, 0.0],
        "Boylam": [29.0, 0.0],
        "ad":     ["istanbul_ok", "sentinel"],
    })
    out = _df_to_gdf(df)
    ads = out["ad"].tolist()
    assert "sentinel" not in ads, (
        f"REGRESYON: (0,0) sentinel'i temizlenmedi. ads={ads}"
    )
    assert "istanbul_ok" in ads


def test_outside_istanbul_bbox_dropped_with_warning():
    """
    İstanbul bbox dışı koordinatlar (ör. Ankara, Eskişehir) elenmeli.
    Kullanıcı yanlış ilçeden veri yüklediyse fark etsin.
    """
    df = pd.DataFrame({
        "Enlem":  [41.0,  39.92],   # 41=İst, 39.92=Ankara
        "Boylam": [29.0,  32.85],
        "ad":     ["ist", "ankara"],
    })
    out = _df_to_gdf(df)
    ads = out["ad"].tolist()
    assert "ist" in ads
    assert "ankara" not in ads, (
        f"REGRESYON: Ankara koordinatı İstanbul optimizer'ına sızdı. ads={ads}"
    )


def test_nan_coords_dropped():
    df = pd.DataFrame({
        "Enlem":  [41.0, None],
        "Boylam": [29.0, 29.0],
        "ad":     ["ok", "nan"],
    })
    out = _df_to_gdf(df)
    assert len(out) == 1
    assert out.iloc[0]["ad"] == "ok"


def test_count_of_dropped_rows_logged():
    """
    Düşürülen satır sayısı log'a yansımalı. Logger propagate=False ve kendi
    stdout referansını tutuyor (pytest'in capture'ı görmüyor); bu yüzden
    geçici bir handler ekleyip mesajları yakalıyoruz.
    """
    import logging

    from src.optimizer import data_loader as dl

    captured: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda record: captured.append(record.getMessage())
    handler.setLevel(logging.WARNING)
    dl.log.addHandler(handler)
    try:
        df = pd.DataFrame({
            "Enlem":  [41.0, 0.0, 999.0],
            "Boylam": [29.0, 0.0, 29.0],
        })
        out = _df_to_gdf(df)
    finally:
        dl.log.removeHandler(handler)

    assert len(out) == 1
    assert any(
        "2/3" in m or ("2 satır" in m) or "geçersiz" in m.lower()
        for m in captured
    ), f"Düşürme bilgisi log'a yansımadı; captured: {captured}"
