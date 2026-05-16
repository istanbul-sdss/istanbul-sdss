"""
H3 regression: DataFrame content-based cache key.

Önceki davranış `id(df)` kullanıyordu — GC sonrası adres yeniden
kullanım nedeniyle teorik olarak yanlış cache hit'i mümkündü.
İçerik tabanlı hash bu sınıfın hatasını ortadan kaldırır.

Test odakları:
  1. Aynı içerik → aynı hash (cache hit)
  2. Tek hücre değişikliği → farklı hash (cache miss; tutucu doğru)
  3. Farklı index ama aynı içerik → aynı hash (index agnostic)
  4. Boş DataFrame → kolon imzasına dayalı stabil hash
  5. `nonempty_signature` kategoriler arası deterministik
  6. Kategori değişimi → imza değişimi
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.utils import df_content_hash, nonempty_signature


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame({
        "Ad": ["Hastane A", "Eczane B", "Okul C"],
        "Enlem": [41.01, 41.02, 41.03],
        "Boylam": [29.05, 29.06, 29.07],
        "Mahalle": ["Caferağa", "Caferağa", "Fenerbahçe"],
    })


# ── 1. Equal content → equal hash ──────────────────────────────────────────
def test_same_content_yields_same_hash():
    df1 = _sample_df()
    df2 = _sample_df()
    assert df_content_hash(df1) == df_content_hash(df2)


# ── 2. Sensitivity: one-cell change must flip hash ─────────────────────────
def test_single_cell_change_flips_hash():
    df1 = _sample_df()
    df2 = _sample_df()
    df2.loc[0, "Ad"] = "Hastane X"   # one cell different
    assert df_content_hash(df1) != df_content_hash(df2)


def test_added_row_flips_hash():
    df1 = _sample_df()
    df2 = pd.concat([df1, pd.DataFrame([{
        "Ad": "Ek", "Enlem": 41.0, "Boylam": 29.0, "Mahalle": "X"
    }])], ignore_index=True)
    assert df_content_hash(df1) != df_content_hash(df2)


def test_added_column_flips_hash():
    df1 = _sample_df()
    df2 = df1.copy()
    df2["Kategori"] = "Sağlık"
    assert df_content_hash(df1) != df_content_hash(df2)


# ── 3. Index-agnostic ──────────────────────────────────────────────────────
def test_different_index_same_content_same_hash():
    df1 = _sample_df()
    df2 = _sample_df()
    df2.index = [10, 20, 30]   # re-indexed but same data
    assert df_content_hash(df1) == df_content_hash(df2)


# ── 4. Empty DataFrame ─────────────────────────────────────────────────────
def test_empty_df_stable_hash():
    e1 = pd.DataFrame(columns=["a", "b"])
    e2 = pd.DataFrame(columns=["a", "b"])
    assert df_content_hash(e1) == df_content_hash(e2)


def test_empty_df_different_columns_different_hash():
    e1 = pd.DataFrame(columns=["a", "b"])
    e2 = pd.DataFrame(columns=["a", "c"])
    assert df_content_hash(e1) != df_content_hash(e2)


def test_none_dataframe_safe():
    """None girdi crash etmemeli; ayırt edici sabit dönmeli."""
    assert df_content_hash(None) == 0


# ── 5. nonempty_signature determinism & sensitivity ────────────────────────
def test_signature_deterministic_across_dict_order():
    """
    Python 3.7+ dict insertion order'ı korur ama kategori dict'imizin
    sıralama yolu (rule_code) signature'a katkısı önemli. sorted() içeride
    olduğu için insertion-order farklı olsa bile aynı imza üretilmeli.
    """
    df = _sample_df()
    a = {"health_hospital": {"df": df}, "education_school": {"df": df}}
    b = {"education_school": {"df": df}, "health_hospital": {"df": df}}
    assert nonempty_signature(a) == nonempty_signature(b)


def test_signature_changes_when_df_content_changes():
    df_orig = _sample_df()
    df_mut = _sample_df()
    df_mut.loc[0, "Ad"] = "Değişti"
    a = {"health_hospital": {"df": df_orig}}
    b = {"health_hospital": {"df": df_mut}}
    assert nonempty_signature(a) != nonempty_signature(b)


def test_signature_changes_when_category_changes():
    df = _sample_df()
    a = {"health_hospital": {"df": df}}
    b = {"health_pharmacy": {"df": df}}   # same data, different key
    assert nonempty_signature(a) != nonempty_signature(b)


# ── 6. GC-reuse scenario the old id(df) approach was vulnerable to ─────────
def test_distinct_df_objects_same_content_collide_safely():
    """
    Eski `id(df)` yaklaşımı: aynı içerikli iki farklı df → farklı id →
    farklı cache anahtarı → boşa rebuild. İçerik tabanlı hash bu boş
    rebuild'i de eler (aynı veriden tekrar Excel üretme gereği yok).
    """
    df1 = _sample_df()
    df2 = _sample_df()
    assert df1 is not df2   # farklı objeler
    assert df_content_hash(df1) == df_content_hash(df2)   # aynı içerik
