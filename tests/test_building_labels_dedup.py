"""
H-Opt-8 regresyonu: _generate_building_labels aynı OSM `name` ile birden
fazla bina geldiğinde önceden hepsi aynı etiketi (örn. "Migros") alıyordu;
Step 4 building selectbox `set(label_options)` ile dedup ettiği için
ikinci binaya UI'dan ulaşılamıyordu.

Düzeltme: ilk geliş suffix'siz kalır, sonrakiler "#2", "#3" alır → her
bina için unique label garanti.
"""
from __future__ import annotations

import pandas as pd

from src.optimizer.data_loader import _generate_building_labels


def test_unique_names_unchanged():
    """Tek-tek isimler suffix almamalı (geriye uyumluluk)."""
    names      = pd.Series(["Migros", "Macrocenter", "Pegasus Plaza"])
    mahalleler = pd.Series(["Caferağa Mh."] * 3)
    out = _generate_building_labels(names, mahalleler)
    assert list(out) == ["Migros", "Macrocenter", "Pegasus Plaza"]


def test_duplicate_names_get_numeric_suffix():
    """Aynı isim 3 kez → "Migros", "Migros #2", "Migros #3" sırası."""
    names      = pd.Series(["Migros", "Migros", "Migros"])
    mahalleler = pd.Series(["Caferağa Mh.", "Caferağa Mh.", "Fenerbahçe Mh."])
    out = _generate_building_labels(names, mahalleler)
    assert list(out) == ["Migros", "Migros #2", "Migros #3"]
    # Tümü unique
    assert len(set(out)) == 3


def test_mixed_duplicates_and_unique():
    """Bazı isimler tek, bazıları tekrarlı — sadece tekrarlılar suffix alır."""
    names = pd.Series(["Migros", "Pegasus", "Migros", "MASKO", "MASKO"])
    mahalleler = pd.Series(["A Mh."] * 5)
    out = _generate_building_labels(names, mahalleler)
    assert list(out) == ["Migros", "Pegasus", "Migros #2", "MASKO", "MASKO #2"]
    assert len(set(out)) == 5


def test_meaningless_names_still_use_mahalle_fallback():
    """`yes` / `nan` / `building` gibi anlamsız OSM name'leri eski fallback'i alır."""
    names      = pd.Series(["yes", "Migros", "nan", ""])
    mahalleler = pd.Series(["Caferağa Mh.", "Caferağa Mh.", "Caferağa Mh.", "Caferağa Mh."])
    out = _generate_building_labels(names, mahalleler)
    # 0: yes → "Caferağa Mh. #1"
    # 1: Migros → "Migros" (unique, no suffix)
    # 2: nan → "Caferağa Mh. #2"
    # 3: "" → "Caferağa Mh. #3"
    assert out.iloc[0] == "Caferağa Mh. #1"
    assert out.iloc[1] == "Migros"
    assert out.iloc[2] == "Caferağa Mh. #2"
    assert out.iloc[3] == "Caferağa Mh. #3"


def test_truncation_preserves_dedup():
    """50 karakteri aşan isim kesilir; aynı kesilmiş kök yine dedup'a girer."""
    long_name = "A" * 60  # 60 char → kesilir → 50 A
    names = pd.Series([long_name, long_name])
    mahalleler = pd.Series(["A Mh.", "A Mh."])
    out = _generate_building_labels(names, mahalleler)
    truncated = "A" * 50
    assert list(out) == [truncated, f"{truncated} #2"]
