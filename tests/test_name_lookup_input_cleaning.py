"""
tests/test_name_lookup_input_cleaning.py

`_is_empty_input` helper'ının Excel/CSV'den gelen tüm "boş" varyantlarını
yakaladığını doğrular. Bug raporu: bazı reader'lar NaN'ı literal "nan"
string'e çeviriyordu; eski kod bunu arama girdisi sayıyordu.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from src.services.name_lookup_service import _is_empty_input


@pytest.mark.parametrize("value", [
    None,
    float("nan"),
    pd.NA,
    "",
    "   ",
    "\t\n",
    "nan",
    "NaN",
    "NAN",
    "none",
    "None",
    "null",
    "NULL",
    "n/a",
    "N/A",
    "na",
    "-",
    "—",
    " nan ",
    " NONE  ",
])
def test_recognizes_empty_variants(value):
    """Tüm bilinen 'boş' temsillerini tek noktadan filtrele."""
    assert _is_empty_input(value) is True, f"{value!r} boş sayılmalı"


@pytest.mark.parametrize("value", [
    "Şifa Eczanesi",
    "Aile",
    "x",
    "0",          # numerik string ama anlamlı isim
    "1234",
    "Bilinmeyen", # 'unknown' Türkçe değil; bunu boş sayma
    "ASM",        # kısaltma — gerçek bir POI'nin adı olabilir
    "İÖO",
])
def test_does_not_drop_real_names(value):
    """Gerçek isimleri yanlışlıkla boş işaretleme."""
    assert _is_empty_input(value) is False, f"{value!r} boş sayılmamalı"


def test_handles_non_string_truthy_values():
    """Sayı, bool gibi non-string girdiler de string'e çevrilip kontrol edilmeli."""
    # 0 stringe "0" olur → "0" not in literals → False (gerçek isim sayılır)
    assert _is_empty_input(0) is False
    assert _is_empty_input(123) is False
    # NaN float
    assert _is_empty_input(math.nan) is True
