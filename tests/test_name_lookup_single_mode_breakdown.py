"""
tests/test_name_lookup_single_mode_breakdown.py

Single mode (match_names) için row-preserving + decomposition sözleşmesi.
Mixed mode ile aynı garantileri verdiğini doğrular: Input Row, Skor: İsim,
Skor: Jaccard, Skor: Tag, Skor: Mahalle, Eşleşme Açıklaması.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.config.name_lookup_rules import tokenize_for_match
from src.services.name_lookup_service import (
    PreparedPools,
    _Candidate,
    match_names,
)

_RULE_CODE = "health_pharmacy"


def _mk_t1_candidate(name: str, mahalle: str, osm_id: int) -> _Candidate:
    """Tier 1 (rule-aware) candidate — pipeline çıktısını simüle eder."""
    toks = set(tokenize_for_match(name, _RULE_CODE))
    canonical = " ".join(sorted(toks))
    payload = {
        "Ad":           name,
        "OSM ID":       osm_id,
        "OSM Tipi":     "Nokta",
        "Mahalle":      mahalle,
        "Sınır Durumu": "ilçe_içi",
        "Kategori":     "health",
        "Alt Kategori": "pharmacy",
    }
    return _Candidate(
        tokens=toks, canonical=canonical,
        variants=[(toks, canonical)] if toks else [],
        payload=payload,
    )


@pytest.fixture
def pools() -> PreparedPools:
    return PreparedPools(
        rule_code=_RULE_CODE,
        cat_key="health",
        sub_key="pharmacy",
        ilce="Kadıköy",
        tier1_candidates=[
            _mk_t1_candidate("Şifa Eczanesi", "Caferağa Mahallesi", 101),
            _mk_t1_candidate("Aile Eczanesi", "Caferağa Mahallesi", 102),
            _mk_t1_candidate("Aile Eczanesi", "Fenerbahçe Mahallesi", 103),
        ],
        tier2_candidates=[],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Row-preserving + Input Row in single mode
# ─────────────────────────────────────────────────────────────────────────────
def test_input_row_column_present_in_single_mode(pools):
    res = match_names(pools, names=["Şifa Eczanesi"])
    assert "Input Row" in res.df.columns
    assert res.df["Input Row"].iloc[0] == 0


def test_duplicate_input_yields_one_row_each(pools):
    """
    Single mode'da dedup mahalle parametresine sahip değil; aynı isim 2
    kez verilirse iç skor cache'lenir AMA çıktıda iki satır olur.
    """
    res = match_names(pools, names=["Şifa Eczanesi", "Şifa Eczanesi"])
    assert len(res.df) == 2
    assert res.df["Input Row"].tolist() == [0, 1]


def test_empty_input_skipped_preserves_row_index(pools):
    """Boş hücre filtrelenir; kalan satırların Input Row değeri orijinal."""
    res = match_names(pools, names=["", "Şifa Eczanesi", "nan"])
    assert res.df["Input Row"].tolist() == [1]


# ─────────────────────────────────────────────────────────────────────────────
# Decomposition columns
# ─────────────────────────────────────────────────────────────────────────────
def test_breakdown_columns_present(pools):
    res = match_names(pools, names=["Şifa Eczanesi"])
    expected = {
        "Skor: İsim", "Skor: Jaccard", "Skor: Tag",
        "Skor: Mahalle", "Eşleşme Açıklaması",
    }
    assert expected.issubset(set(res.df.columns)), \
        f"Eksik kolonlar: {expected - set(res.df.columns)}"


def test_perfect_match_yields_high_name_score(pools):
    res = match_names(pools, names=["Şifa Eczanesi"])
    # token_set_ratio "şifa" ↔ "şifa" = 100, "eczanesi" stopword olabilir
    name_s = res.df["Skor: İsim"].iloc[0]
    assert name_s >= 90.0


def test_tier1_match_sets_tag_score_to_match(pools):
    """
    Tier 1 candidate'lar pipeline'dan strict-tag uyumlu olarak gelir →
    compat_raw="match" → Skor: Tag = 100.
    """
    res = match_names(pools, names=["Şifa Eczanesi"])
    assert res.df["Skor: Tag"].iloc[0] == 100.0


def test_mahalle_score_is_none_in_single_mode(pools):
    """Single mode mahalle filtresi YOK — Skor: Mahalle her zaman None."""
    res = match_names(pools, names=["Şifa Eczanesi"])
    assert pd.isna(res.df["Skor: Mahalle"].iloc[0])


def test_explanation_mentions_common_tokens_or_tag(pools):
    res = match_names(pools, names=["Şifa Eczanesi"])
    expl = str(res.df["Eşleşme Açıklaması"].iloc[0]).lower()
    # English ("common tokens" / "tag aligned") with TR fallback retained.
    assert (
        "common tokens" in expl or "tag aligned" in expl
        or "ortak token" in expl or "tag uyumlu" in expl
    )


def test_not_found_row_has_safe_breakdown_defaults(pools):
    """Eşleşme bulunamadığında breakdown alanları None / '—' olmalı, çökmemeli."""
    res = match_names(pools, names=["Tamamen Olmayan Bir İsim XYZ123"])
    assert len(res.df) == 1
    row = res.df.iloc[0]
    # Skor: İsim ya None ya 0; her durumda exception atmamış
    assert pd.isna(row["Skor: İsim"]) or row["Skor: İsim"] in (None, 0.0)
    assert row["Eşleşme Durumu"] in ("Not found", "Possible match")


# ─────────────────────────────────────────────────────────────────────────────
# Single mode hâlâ tier'lar arası geçişi doğru rapor ediyor
# ─────────────────────────────────────────────────────────────────────────────
def test_match_count_scales_with_input_count(pools):
    """
    Aynı (norm_name) iç dedup grubuna giden 3 input → 3 sayım, 1 değil.
    """
    res = match_names(pools, names=["Şifa Eczanesi", "Şifa Eczanesi", "Şifa Eczanesi"])
    assert res.tier1_count == 3
    assert len(res.df) == 3
