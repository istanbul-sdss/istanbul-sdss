"""
tests/test_name_lookup_row_preserving.py

Mixed mode'da aynı ismin farklı mahallelerde geçen iki satırının
SİLİNMEDİĞİNİ ve her input satırının çıktıda 1-1 temsil edildiğini
doğrular. Bu, kullanıcının raporladığı "boş hücre + dedup" bug'ının
ana doğrulamasıdır.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.config.name_lookup_rules import tokenize_lite
from src.services.name_lookup_service import (
    UniversalPool,
    _UniversalCandidate,
    match_mixed_list,
)


def _mk_candidate(name: str, mahalle: str, **tags) -> _UniversalCandidate:
    raw_variants = [name]
    toks = set(tokenize_lite(name))
    payload = {
        "Ad":           name,
        "OSM ID":       hash(name + mahalle) & 0xFFFFFFFF,
        "OSM Tipi":     "Nokta",
        "Mahalle":      mahalle,
        "Sınır Durumu": "ilçe_içi",
    }
    payload.update(tags)
    return _UniversalCandidate(
        lite_variants=[(toks, " ".join(sorted(toks)))],
        raw_name_variants=raw_variants,
        payload=payload,
    )


@pytest.fixture
def pharmacy_pool() -> UniversalPool:
    cands = [
        _mk_candidate("Aile Eczanesi", "Caferağa Mahallesi", amenity="pharmacy"),
        _mk_candidate("Aile Eczanesi", "Fenerbahçe Mahallesi", amenity="pharmacy"),
        _mk_candidate("Şifa Eczanesi", "Caferağa Mahallesi", amenity="pharmacy"),
    ]
    return UniversalPool(
        ilce="Kadıköy", candidates=cands,
        rule_token_cache={}, place_stopwords=set(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Core bug: same name, different mahalle — must NOT collapse
# ─────────────────────────────────────────────────────────────────────────────
def test_same_name_different_mahalle_kept_separately(pharmacy_pool):
    """
    Bug: dedup anahtarı sadece normalize_tr(n) idi. "Aile Eczanesi" iki
    mahallede gelirse ikinci satır siliniyordu. Düzeltme: anahtar
    (name, mahalle) çifti.
    """
    res = match_mixed_list(
        pharmacy_pool,
        names=["Aile Eczanesi", "Aile Eczanesi"],
        neighborhoods=["Caferağa", "Fenerbahçe"],
    )
    assert len(res.df) == 2, "Aynı isim farklı mahalle → 2 satır olmalı"
    assert set(res.df["Mahalle (Girdi)"].tolist()) == {"Caferağa", "Fenerbahçe"}
    assert sorted(res.df["Input Row"].tolist()) == [0, 1]


def test_truly_duplicate_input_yields_one_row_per_input(pharmacy_pool):
    """
    Aynı (isim, mahalle) çifti 2 kez gelirse iç skor cache'lenir AMA
    çıktıda yine 2 satır olur — kullanıcının orijinal listesine 1-1
    karşılık gelmesi için.
    """
    res = match_mixed_list(
        pharmacy_pool,
        names=["Aile Eczanesi", "Aile Eczanesi"],
        neighborhoods=["Caferağa", "Caferağa"],
    )
    assert len(res.df) == 2
    assert res.df["Input Row"].tolist() == [0, 1]
    # İki satır da aynı OSM ID'ye işaret etmeli (skor cache çalıştı)
    assert res.df["OSM ID"].nunique() == 1


# ─────────────────────────────────────────────────────────────────────────────
# Output ordering matches input order (deterministic audit trail)
# ─────────────────────────────────────────────────────────────────────────────
def test_output_order_matches_input_order(pharmacy_pool):
    """
    Çıktı Input Row'a göre sırada olmalı; iç gruplama input sırasını
    bozmamalı (denetlenebilirlik için kritik).
    """
    res = match_mixed_list(
        pharmacy_pool,
        names=["Şifa Eczanesi", "Aile Eczanesi", "Aile Eczanesi"],
        neighborhoods=["Caferağa", "Fenerbahçe", "Caferağa"],
    )
    assert res.df["Input Row"].tolist() == [0, 1, 2]


def test_input_row_is_zero_indexed(pharmacy_pool):
    res = match_mixed_list(
        pharmacy_pool,
        names=["Şifa Eczanesi"],
        neighborhoods=[None],
    )
    assert res.df["Input Row"].iloc[0] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Empty input filtering preserves index alignment
# ─────────────────────────────────────────────────────────────────────────────
def test_empty_inputs_skip_but_preserve_remaining_indices(pharmacy_pool):
    """
    Boş hücreler arama girdisi sayılmaz AMA dolu hücrelerin Input Row
    değerleri orijinal pozisyonu yansıtmalı (kullanıcı satır 5 boş, satır
    6 dolu görmek istiyor; çıktıda satır 6 = Input Row 5 olmalı, 0 değil).
    """
    res = match_mixed_list(
        pharmacy_pool,
        names=["", "Aile Eczanesi", None, "Şifa Eczanesi", "  "],
        neighborhoods=[None, "Caferağa", None, "Caferağa", None],
    )
    # Input pozisyonları: 0=boş, 1=Aile, 2=None, 3=Şifa, 4=whitespace
    # → çıktıda Input Row [1, 3] görmeli
    assert res.df["Input Row"].tolist() == [1, 3]
    assert res.df["Girdi Ad"].tolist() == ["Aile Eczanesi", "Şifa Eczanesi"]


# ─────────────────────────────────────────────────────────────────────────────
# Counters scale with input_id count, not unique groups
# ─────────────────────────────────────────────────────────────────────────────
def test_match_counter_counts_inputs_not_groups(pharmacy_pool):
    """
    matched_count input satır sayısına göre artmalı, grup sayısına göre
    değil. Aksi halde "2 input verdim ama matched=1 görüyorum" olur.
    """
    res = match_mixed_list(
        pharmacy_pool,
        names=["Aile Eczanesi", "Aile Eczanesi"],
        neighborhoods=["Caferağa", "Caferağa"],  # AYNI çift
    )
    assert res.matched_count == 2  # 2 input → 2 sayım
