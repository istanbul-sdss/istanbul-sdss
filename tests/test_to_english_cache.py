"""
`to_english()` cache güvenliği testleri (P2 bug fix regresyon koruması).

Eski davranış: cache anahtarı `id(df)`, dönen değer cached referans.
İki risk:
  1. Caller cache'ten dönen df'i mutate ederse cache'teki orijinal de
     mutate olur → sonraki çağrı "bayat" / mutate edilmiş veri döner.
  2. Python GC `id`'leri yeniden kullanır → farklı içerikli iki df aynı
     cache anahtarına denk gelebilir.

Düzeltme: içerik-hash bazlı anahtar + caller'a daima `.copy()`.
"""
from __future__ import annotations

import gc

import pandas as pd

from components.translations import _TO_ENGLISH_CACHE, to_english


def _clear_cache():
    _TO_ENGLISH_CACHE.clear()


def _sample_tr_df() -> pd.DataFrame:
    return pd.DataFrame({
        "Ad":            ["Hastane A", "Eczane B"],
        "Mahalle":       ["Caferağa", "Fenerbahçe"],
        "Güven":         ["Yüksek", "Düşük"],
        "Sınır Durumu":  ["ilçe_içi", "ilçe_dışı"],
    })


# ── 1. Aynı içerik → aynı çıktı (cache hit doğru çalışıyor) ───────────────
def test_repeated_call_same_content_returns_same_values():
    _clear_cache()
    df = _sample_tr_df()
    a = to_english(df)
    b = to_english(df)
    pd.testing.assert_frame_equal(a, b)


# ── 2. Cache hit dönen df, cache'teki orijinali ifşa ETMEMELİ ─────────────
def test_cache_hit_returns_independent_copy():
    """
    Cache'ten gelen DataFrame caller tarafından mutate edilirse,
    bir sonraki çağrı bayat / mutate edilmiş veri DÖNDÜRMEMELİ.
    """
    _clear_cache()
    df = _sample_tr_df()
    first = to_english(df)

    # Caller dönen df'i mutate ediyor
    first.loc[0, "Confidence"] = "MUTATED"

    # İkinci çağrı temiz veri vermeli
    second = to_english(df)
    assert second.loc[0, "Confidence"] == "High", (
        f"Cache mutation kaçırıldı: {second.loc[0, 'Confidence']!r} "
        "(beklenen: 'High' — cache return'üne mutation sızdı)"
    )


# ── 3. id-reuse senaryosu: aynı id, farklı içerik ─────────────────────────
def test_same_id_different_content_does_not_collide():
    """
    Eski `id(df)` yaklaşımı GC reuse'a karşı savunmasızdı. İçerik-bazlı
    anahtarda iki farklı df asla aynı cache slot'una girmemeli.
    """
    _clear_cache()
    df1 = _sample_tr_df()
    out1 = to_english(df1)
    assert out1.loc[0, "Confidence"] == "High"

    # df1'i bırak, GC potansiyel olarak id'sini yeniden kullansın
    del df1, out1
    gc.collect()

    # Tamamen farklı içerikli bir df
    df2 = pd.DataFrame({
        "Ad": ["X"],
        "Güven": ["Düşük"],  # ← farklı confidence
    })
    out2 = to_english(df2)
    assert out2.loc[0, "Confidence"] == "Low", (
        "id-reuse cache hit'i farklı içeriği eski sonuca eşledi"
    )


# ── 4. İçerik değişikliği yeni cache anahtarı üretir ──────────────────────
def test_changed_content_yields_fresh_translation():
    """
    Aynı df nesnesinin İÇERİĞİ değiştirilirse `to_english` taze çeviri
    döndürmeli (bayat cache hit yok). Bu, raporun açıkça yakaladığı
    "Güven=Yüksek → Confidence=High; sonra Güven=Düşük yapılınca hâlâ
    Confidence=High" senaryosudur.
    """
    _clear_cache()
    df = _sample_tr_df()
    first = to_english(df)
    assert first.loc[0, "Confidence"] == "High"

    # df içeriğini değiştir
    df.loc[0, "Güven"] = "Düşük"

    second = to_english(df)
    assert second.loc[0, "Confidence"] == "Low", (
        f"İçerik değişti ama eski çeviri döndü: {second.loc[0, 'Confidence']!r}"
    )


# ── 5. Boş / None df cache'i etkilemez ────────────────────────────────────
def test_empty_df_passthrough():
    _clear_cache()
    empty = pd.DataFrame()
    out = to_english(empty)
    assert out.empty
    # Cache'e girmemiş olmalı
    assert len(_TO_ENGLISH_CACHE) == 0


def test_none_input_returns_none():
    _clear_cache()
    assert to_english(None) is None


# ── 6. translate_values=False de aynı güvenliği taşır ─────────────────────
def test_translate_values_false_still_cache_safe():
    _clear_cache()
    df = _sample_tr_df()
    first = to_english(df, translate_values=False)
    # Kolon rename oldu ama değer çeviri yok
    assert "Confidence" in first.columns
    assert first.loc[0, "Confidence"] == "Yüksek"   # değer çevrilmedi

    # Mutate
    first.loc[0, "Confidence"] = "MUTATED"
    second = to_english(df, translate_values=False)
    assert second.loc[0, "Confidence"] == "Yüksek", (
        "translate_values=False yolunda da cache mutation kaçırıldı"
    )
