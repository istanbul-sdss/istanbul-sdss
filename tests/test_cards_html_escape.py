"""
`components/cards.py` HTML escape regresyon testleri.

Bulgu (UI review P1): Folium katmanı `safe_field` ile kullanıcı/dış-veri
kaynaklı string'leri escape ediyor ama `cards.py` ham basıyordu — asimetrik
savunma. Yüklenen dosya adı, serbest text district ve OSM-kaynaklı label'lar
HTML olarak yorumlanabiliyordu (layout kırılması + teorik XSS).

Düzeltme: `cards._esc()` merkezi helper + tüm bileşenlerde dinamik
parametre escape'i. Bu testler `<script>`, `<b>` ve özel karakter
içeren girdilerin **HTML tag olarak değil, metin olarak** render edildiğini
doğrular.

Test stratejisi: bileşenler `st.markdown(..., unsafe_allow_html=True)`
çağırdığı için doğrudan üretilen HTML stringini test edemeyiz; bunun
yerine streamlit `AppTest` ile sayfa renderını koşturup çıktıda
ham tag bulunmamasını kontrol ederiz. Daha pratik: helper fonksiyonu
(`_esc`) doğrudan test edilir + entegrasyon için bir AppTest senaryosu.
"""
from __future__ import annotations

import streamlit as st
from streamlit.testing.v1 import AppTest

from components.cards import _esc


# ── 1. _esc helper — birim seviyesi ───────────────────────────────────────
def test_esc_escapes_script_tag():
    assert _esc("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_esc_escapes_html_tags():
    assert _esc("<b>bold</b>") == "&lt;b&gt;bold&lt;/b&gt;"


def test_esc_preserves_plain_text():
    assert _esc("Kadıköy") == "Kadıköy"
    assert _esc("Caferağa Mh.") == "Caferağa Mh."


def test_esc_handles_special_characters():
    # &, <, >, ', " — tümü escape edilmeli
    out = _esc('A & B "quoted" <tag> \'apos\'')
    assert "&amp;" in out
    assert "&lt;" in out
    assert "&gt;" in out
    assert "&quot;" in out or "&#x27;" in out or "&#39;" in out


def test_esc_handles_none():
    """None girdisi crash etmemeli; boş string dönmeli."""
    assert _esc(None) == ""


def test_esc_handles_numeric():
    """Sayısal değerler str()'e dökülür, escape gereği yok ama hata vermemeli."""
    assert _esc(42) == "42"
    assert _esc(3.14) == "3.14"


def test_esc_handles_empty_string():
    assert _esc("") == ""


# ── 2. AppTest entegrasyon — kötü-niyetli girdiler tag olarak görünmez ───
def _write_test_app(injection: str) -> str:
    """
    AppTest için inline bir uygulama yazar — components.cards bileşenleri
    `injection` string'i ile çağrılır. Çıktıda ham HTML tag görünmemeli.
    """
    return f"""
import sys
from pathlib import Path
sys.path.insert(0, r"{str(__import__('pathlib').Path(__file__).resolve().parent.parent)}")

from components import cards

INJECTION = {injection!r}

cards.hero(title=INJECTION, subtitle=INJECTION, eyebrow=INJECTION)
cards.page_header(title=INJECTION, subtitle=INJECTION, eyebrow=INJECTION)
cards.feature_card(icon="🛡️", title=INJECTION, text=INJECTION)
cards.kpi_card(label=INJECTION, value=INJECTION, delta=INJECTION)
cards.status_strip([
    {{"label": INJECTION, "value": INJECTION, "tone": "ok"}},
])
cards.section_title(title=INJECTION, subtitle=INJECTION)
cards.empty_state(title=INJECTION, text=INJECTION, icon=INJECTION, cta=INJECTION, cta_target="/")
"""


def _markdown_collected_text(app: AppTest) -> str:
    """AppTest'in topladığı tüm markdown bloklarını birleştirir."""
    return "\n".join(m.value for m in app.markdown if hasattr(m, "value"))


def test_script_tag_injection_renders_as_text_not_tag(tmp_path):
    """
    Kötü-niyetli `<script>` içeren bir başlık/değer, render edilen
    HTML'de **escape edilmiş** olmalı. Aksi halde tarayıcı tag olarak
    yorumlar (XSS yüzeyi).
    """
    injection = '<script>alert("XSS")</script>'
    script = _write_test_app(injection)
    p = tmp_path / "_inject.py"
    p.write_text(script, encoding="utf-8")

    app = AppTest.from_file(str(p), default_timeout=15)
    app.run()
    assert not app.exception, f"Render hatası: {app.exception}"

    rendered = _markdown_collected_text(app)
    # Ham tag olmamalı
    assert "<script>" not in rendered, (
        "INJECTION sızdı: cards bileşenleri ham <script> tag'i basıyor"
    )
    assert "</script>" not in rendered
    # Escape edilmiş haliyle görünmeli
    assert "&lt;script&gt;" in rendered, (
        "Escape edilmiş <script> render'da bulunamadı — fonksiyon "
        "bypass mı edildi?"
    )


def test_bold_tag_injection_renders_as_text(tmp_path):
    """
    `<b>` içeren bir dosya adı / başlık, **bold** olarak değil metin
    olarak görünmeli. Bu, kullanıcının yüklediği dosyanın layout'u
    bozmamasını garantiler.
    """
    injection = "rapor<b>kırıcı</b>.xlsx"
    script = _write_test_app(injection)
    p = tmp_path / "_inject_b.py"
    p.write_text(script, encoding="utf-8")

    app = AppTest.from_file(str(p), default_timeout=15)
    app.run()
    assert not app.exception

    rendered = _markdown_collected_text(app)
    assert "<b>kırıcı</b>" not in rendered
    assert "&lt;b&gt;kırıcı&lt;/b&gt;" in rendered


def test_quote_injection_does_not_break_attributes(tmp_path):
    """
    Çift tırnak içeren bir değerin HTML attribute'ları (style="...")
    kırmamasını garantile. Eski davranışta `value` ham basılıyordu →
    `value='">..."'` saldırısı style'ı bozabilirdi.
    """
    injection = 'normal"><img src=x>'
    script = _write_test_app(injection)
    p = tmp_path / "_inject_q.py"
    p.write_text(script, encoding="utf-8")

    app = AppTest.from_file(str(p), default_timeout=15)
    app.run()
    assert not app.exception

    rendered = _markdown_collected_text(app)
    # Ham `<img` tag'i sızmamalı
    assert "<img " not in rendered
    assert "<img src=x>" not in rendered


# ── 3. Plain Türkçe içerik bozulmamalı ────────────────────────────────────
def test_turkish_content_unchanged_through_escape(tmp_path):
    """
    Düzeltme, Türkçe karakterleri / normal metni BOZMAMALI — yalnızca
    HTML-special karakterleri kaçırır.
    """
    benign = "Caferağa Mahallesi — 6.665 bina, p=10"
    script = _write_test_app(benign)
    p = tmp_path / "_benign.py"
    p.write_text(script, encoding="utf-8")

    app = AppTest.from_file(str(p), default_timeout=15)
    app.run()
    assert not app.exception

    rendered = _markdown_collected_text(app)
    # Türkçe karakter, em-dash, sayı, eşittir hepsi olduğu gibi
    assert "Caferağa Mahallesi" in rendered
    assert "—" in rendered
    assert "6.665 bina" in rendered
    assert "p=10" in rendered
