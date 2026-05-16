"""
Regresyon (P3.3): df_latlon_to_geodataframe defansif davranmalı.

Audit bulgusu:
  • Eksik kolonda `df.get(col, 0)` → scalar 0 → `.fillna()` AttributeError.
  • Sessiz fallback: eksik koordinat (0,0)'a (Atlantic Ocean) yerleşiyordu.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.services.spatial_service import df_latlon_to_geodataframe


def test_missing_latitude_column_raises_value_error():
    df = pd.DataFrame({"Boylam": [29.0, 29.1], "ad": ["a", "b"]})
    with pytest.raises(ValueError, match="Enlem"):
        df_latlon_to_geodataframe(df)


def test_missing_longitude_column_raises_value_error():
    df = pd.DataFrame({"Enlem": [41.0], "ad": ["a"]})
    with pytest.raises(ValueError, match="Boylam"):
        df_latlon_to_geodataframe(df)


def test_invalid_coordinates_are_dropped_not_zeroed():
    """
    Aralık dışı / NaN koordinatlar SESSİZCE (0,0)'a düşmemeli — düşürülmeli.
    Önceden 6 satırın 4'ü Atlantic Ocean'a yerleşiyordu.
    """
    df = pd.DataFrame({
        "Enlem":  [41.0, None, 999.0,  41.5,  -91.0,  40.5],
        "Boylam": [29.0, 29.0, 29.0,   None,  29.0,   181.0],
        "ad":     ["a",  "b",  "c",    "d",   "e",    "f"],
    })
    out = df_latlon_to_geodataframe(df)
    # Sadece (41.0, 29.0) geçerli → 1 kayıt kalmalı
    assert len(out) == 1, (
        f"REGRESYON: geçersiz koordinatlar düşürülmedi. "
        f"Kalan: {out['ad'].tolist()}"
    )
    assert out.iloc[0]["ad"] == "a"
    pt = out.geometry.iloc[0]
    assert pt.x == 29.0 and pt.y == 41.0


def test_no_zero_zero_silent_fallback():
    """Önceki davranıştan regresyon koruması: hiçbir satır (0,0)'a düşmesin."""
    df = pd.DataFrame({
        "Enlem":  [None, None],
        "Boylam": [None, None],
        "ad":     ["x", "y"],
    })
    out = df_latlon_to_geodataframe(df)
    assert len(out) == 0, (
        "REGRESYON: NaN koordinatlar (0,0)'a yerleşmiş — "
        "Atlantic Ocean fallback'i geri gelmiş."
    )


def test_valid_data_unchanged():
    """Sanity: tüm koordinatlar geçerliyse hepsi korunur."""
    df = pd.DataFrame({
        "Enlem":  [41.0, 41.1, 40.9],
        "Boylam": [29.0, 29.1, 28.9],
    })
    out = df_latlon_to_geodataframe(df)
    assert len(out) == 3
