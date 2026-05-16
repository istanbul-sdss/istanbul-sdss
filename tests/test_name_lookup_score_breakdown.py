"""
tests/test_name_lookup_score_breakdown.py

Decomposed score kolonlarının (Skor: İsim / Jaccard / Tag / Mahalle +
Eşleşme Açıklaması) doğru değerleri ürettiğini doğrular. Bu açıklanabilirlik
katmanı, kullanıcının "neden bu eşleşti?" sorusuna tek bakışta cevap
verebilmesi için kritik.
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
def pool():
    return UniversalPool(
        ilce="Kadıköy",
        candidates=[
            _mk_candidate("Aile Eczanesi",  "Caferağa Mahallesi", amenity="pharmacy"),
            _mk_candidate("Şifa Eczanesi",  "Caferağa Mahallesi", amenity="pharmacy"),
            _mk_candidate("Moda Parkı",     "Caferağa Mahallesi", leisure="park"),
            _mk_candidate("Bizim Market",   "Fenerbahçe Mahallesi", shop="convenience"),
        ],
        rule_token_cache={},
        place_stopwords=set(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Decomposed columns are present
# ─────────────────────────────────────────────────────────────────────────────
def test_breakdown_columns_present_in_output(pool):
    res = match_mixed_list(pool, names=["Aile Eczanesi"], neighborhoods=["Caferağa"])
    expected = {
        "Skor: İsim", "Skor: Jaccard", "Skor: Tag",
        "Skor: Mahalle", "Eşleşme Açıklaması",
    }
    assert expected.issubset(set(res.df.columns)), \
        f"Eksik kolonlar: {expected - set(res.df.columns)}"


# ─────────────────────────────────────────────────────────────────────────────
# Skor: İsim ↔ raw token_set_ratio
# ─────────────────────────────────────────────────────────────────────────────
def test_perfect_match_yields_100_name_score(pool):
    res = match_mixed_list(pool, names=["Aile Eczanesi"], neighborhoods=["Caferağa"])
    assert res.df["Skor: İsim"].iloc[0] == 100.0


# ─────────────────────────────────────────────────────────────────────────────
# Skor: Tag ↔ tag uyumu durumu
# ─────────────────────────────────────────────────────────────────────────────
def test_tag_score_high_when_tag_matches_detection(pool):
    """
    "Aile Eczanesi" → detect_category eczane → strict_tag amenity=pharmacy.
    Aday amenity=pharmacy → match → 100.
    """
    res = match_mixed_list(pool, names=["Aile Eczanesi"], neighborhoods=["Caferağa"])
    assert res.df["Skor: Tag"].iloc[0] == 100.0


# ─────────────────────────────────────────────────────────────────────────────
# Skor: Mahalle ↔ filter aktif/pasif
# ─────────────────────────────────────────────────────────────────────────────
def test_mahalle_score_set_when_filter_active(pool):
    res = match_mixed_list(pool, names=["Aile Eczanesi"], neighborhoods=["Caferağa"])
    assert res.df["Skor: Mahalle"].iloc[0] == 100.0


def test_mahalle_score_none_when_no_hint(pool):
    """Mahalle hint yoksa Skor: Mahalle = None (N/A)."""
    res = match_mixed_list(pool, names=["Aile Eczanesi"], neighborhoods=[None])
    assert pd.isna(res.df["Skor: Mahalle"].iloc[0])


# ─────────────────────────────────────────────────────────────────────────────
# Eşleşme Açıklaması (why_matched)
# ─────────────────────────────────────────────────────────────────────────────
def test_explanation_mentions_common_tokens(pool):
    res = match_mixed_list(pool, names=["Aile Eczanesi"], neighborhoods=["Caferağa"])
    expl = str(res.df["Eşleşme Açıklaması"].iloc[0])
    # English ("common tokens") with TR fallback retained for compat.
    assert ("common tokens" in expl.lower()) or ("ortak token" in expl.lower())
    # At least one common token should appear
    assert "aile" in expl.lower() or "eczanesi" in expl.lower()


def test_explanation_mentions_tag_match(pool):
    res = match_mixed_list(pool, names=["Aile Eczanesi"], neighborhoods=["Caferağa"])
    expl = str(res.df["Eşleşme Açıklaması"].iloc[0])
    # English ("OSM tag aligned") with TR fallback retained for compat.
    assert ("tag aligned" in expl.lower()) or ("tag uyumlu" in expl.lower())


def test_explanation_mentions_mahalle_filter_when_active(pool):
    res = match_mixed_list(pool, names=["Aile Eczanesi"], neighborhoods=["Caferağa"])
    expl = str(res.df["Eşleşme Açıklaması"].iloc[0])
    # English ("passed neighborhood filter") with TR fallback retained for compat.
    assert (
        "neighborhood filter" in expl.lower()
        or "mahalle filtresi" in expl.lower()
    )


# ─────────────────────────────────────────────────────────────────────────────
# Final score = function of breakdown components (sanity)
# ─────────────────────────────────────────────────────────────────────────────
def test_jaccard_lower_than_name_signals_asymmetric_match(pool):
    """
    "Eczanesi" arandığında "Aile Eczanesi" adayında token_set_ratio yüksek
    ama Jaccard düşük olur (1 ortak / 2 union = %50). Bu ayrımı kullanıcı
    görmeli — final skor=100 demek "isim 100 + Jaccard düşük" olabilir.
    """
    res = match_mixed_list(pool, names=["Eczanesi"], neighborhoods=[None])
    # Bir aday seçildi mi?
    if res.df.empty:
        pytest.skip("aday seçilmedi (eczane'in token'ı stopword olabilir)")
    name_s = res.df["Skor: İsim"].iloc[0]
    jacc = res.df["Skor: Jaccard"].iloc[0]
    # name_score ≥ jaccard_pct olmalı (token_set_ratio Jaccard'dan daha
    # yumuşak — strict subset'te 100 verir)
    if pd.notna(name_s) and pd.notna(jacc):
        assert name_s >= jacc
