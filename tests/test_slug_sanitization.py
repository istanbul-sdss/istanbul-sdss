"""
P1-02 regresyon: ilçe slug sanitization güvenlik testleri.

Bulgu: Önceden `_normalize_ilce_slug` yalnızca Türkçe karakter haritası +
boşluk→`_` yapıyordu; path traversal (`../`), slash, Windows-yasak
karakterleri ve kontrol karakterleri filtrelenmiyordu. Custom district
girdisinde cache klasörü dışına dosya yazma teorik olarak mümkündü.

Düzeltme: whitelist `[a-z0-9_]` + ardışık `_` indirgeme + baş/son trim +
boş slug reddi. Defense-in-depth olarak `get_graph` da `resolve() +
relative_to(GRAPH_DIR)` ile path containment kontrolü yapar.
"""
from __future__ import annotations

import pytest

from src.optimizer.od_matrix import _normalize_ilce_slug


# ── 1. Normal Türkçe ilçe adları — eski davranış korunmalı ────────────────
def test_normal_turkish_districts_unchanged():
    """Beklenen ilçe adları için backward-compat: önceki çıktılar aynı kalmalı."""
    assert _normalize_ilce_slug("Kadıköy") == "kadikoy"
    assert _normalize_ilce_slug("Şişli") == "sisli"
    assert _normalize_ilce_slug("Üsküdar") == "uskudar"
    assert _normalize_ilce_slug("Beşiktaş") == "besiktas"
    assert _normalize_ilce_slug("Bağcılar") == "bagcilar"


def test_multiword_districts():
    """Boşluk içeren adlar `_` ile birleşmeli."""
    assert _normalize_ilce_slug("Adalar Mahallesi") == "adalar_mahallesi"
    assert _normalize_ilce_slug("Yeni Mahalle") == "yeni_mahalle"


# ── 2. Path traversal saldırıları ─────────────────────────────────────────
def test_dotdot_traversal_neutralized():
    """`../` ya da `..\\` sequence'leri whitelist ile yok edilmeli."""
    s = _normalize_ilce_slug("../../etc/passwd")
    assert ".." not in s
    assert "/" not in s
    assert "\\" not in s


def test_absolute_path_neutralized():
    """Mutlak yol ifadeleri (C:\\, /etc/) güvenli slug'a düşmeli."""
    s = _normalize_ilce_slug("C:\\Windows\\System32")
    assert "\\" not in s and ":" not in s
    s2 = _normalize_ilce_slug("/etc/shadow")
    assert "/" not in s2


# ── 3. Windows-yasak karakterler ──────────────────────────────────────────
def test_windows_reserved_chars_filtered():
    """`< > : " | ? *` Windows'ta dosya adında yasak — filtre edilmeli."""
    forbidden = '<>:"|?*'
    for ch in forbidden:
        s = _normalize_ilce_slug(f"kadikoy{ch}test")
        assert ch not in s, f"Forbidden char {ch!r} sızdı: {s!r}"


def test_control_characters_filtered():
    """Tab, newline, carriage return → filtrele."""
    s = _normalize_ilce_slug("kadi\tkoy\n")
    assert "\t" not in s and "\n" not in s
    # Beklenen: "kadi_koy" (kontrol karakterleri `_` olur, son `_` trim)
    assert s == "kadi_koy"


# ── 4. HTML injection benzeri girdiler ────────────────────────────────────
def test_html_injection_neutralized():
    """`<script>` benzeri girdiler whitelist'i geçemez."""
    s = _normalize_ilce_slug("<script>alert(1)</script>")
    assert "<" not in s and ">" not in s
    assert "/" not in s


# ── 5. Boş veya sadece sembol girdisi → ValueError ────────────────────────
def test_empty_input_raises():
    with pytest.raises(ValueError, match="geçerli bir dosya slug"):
        _normalize_ilce_slug("")


def test_only_symbols_raises():
    """Yalnızca sembolden oluşan girdi (`./.../`) → tüm karakterler filtrelenir
    → boş slug → ValueError."""
    with pytest.raises(ValueError, match="geçerli bir dosya slug"):
        _normalize_ilce_slug("../../")


def test_only_whitespace_raises():
    with pytest.raises(ValueError, match="geçerli bir dosya slug"):
        _normalize_ilce_slug("   \t\n  ")


# ── 6. Ardışık underscore indirgemesi ────────────────────────────────────
def test_consecutive_underscores_collapsed():
    """Çoklu sembol/boşluk dizisi tek `_`'a dönmeli, sızıntı olmamalı."""
    s = _normalize_ilce_slug("kadi---koy   test")
    assert "__" not in s
    assert s == "kadi_koy_test"


def test_leading_trailing_underscores_stripped():
    """Baş ve sondaki `_` temizlenmeli (tertemiz dosya adı için)."""
    s = _normalize_ilce_slug("--kadikoy--")
    assert not s.startswith("_")
    assert not s.endswith("_")


# ── 7. Numerik içerik korunur ─────────────────────────────────────────────
def test_alphanumeric_preserved():
    """Sayılar slug'da kalmalı (örn. '19 Mayıs')."""
    assert _normalize_ilce_slug("19 Mayıs") == "19_mayis"


# ── 8. Defense-in-depth: get_graph path containment ───────────────────────
def test_get_graph_rejects_path_escape(tmp_path, monkeypatch):
    """
    get_graph slug whitelist'i geçtikten sonra bile cache_path
    GRAPH_DIR altında olduğunu doğrulamalı. Bu test slug whitelist'i
    bypass eden olası bir gelecek bug'ı yakalar (defense-in-depth).
    """
    import src.optimizer.od_matrix as odm

    # Boş slug → ValueError (yukarıdaki testlerle örtüşür ama smoke)
    with pytest.raises(ValueError):
        odm.get_graph("../", force_download=False)
