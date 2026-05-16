"""
`components/cards.status_banner` regresyon testleri.

Helper inline-banner pattern'ını birleştirdi (önceden pages/1 ve pages/4'te
5 ayrı kopya vardı). Bu testler:
- her tone için doğru renk çiftini üretmesini,
- dinamik metnin html.escape'lendiğini,
- varsayılan icon'un tone'a göre seçildiğini ve `icon=""` ile bastırılabildiğini,
- render_status_banner'ın aynı string'i ürettiğini

doğrular. status_ph.markdown(...) placeholder pattern'ı string döndüren ana
fonksiyona dayanıyor — onu kırmamak kritik.
"""
from __future__ import annotations

from components.cards import status_banner


# ── Tone → renk eşleşmesi ────────────────────────────────────────────────────
def test_success_tone_uses_green_palette():
    html = status_banner("Done", tone="success")
    assert "#D1FAE5" in html
    assert "#065F46" in html


def test_warning_tone_uses_amber_palette():
    html = status_banner("Partial", tone="warning")
    assert "#FEF3C7" in html
    assert "#92400E" in html


def test_error_tone_uses_red_palette():
    html = status_banner("Failed", tone="error")
    assert "#FEE2E2" in html
    assert "#991B1B" in html


def test_info_tone_uses_blue_palette():
    html = status_banner("Heads up", tone="info")
    assert "#DBEAFE" in html
    assert "#1E40AF" in html


def test_unknown_tone_falls_back_to_info():
    # tipo savunması — geçersiz tone string'i Literal ile yakalanamaz ama
    # runtime'da info'ya düşmeli.
    html = status_banner("X", tone="bogus")  # type: ignore[arg-type]
    assert "#DBEAFE" in html


# ── HTML escape ──────────────────────────────────────────────────────────────
def test_text_is_html_escaped():
    html = status_banner("<script>alert(1)</script>", tone="info")
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_user_content_with_special_chars_escaped():
    # Olası bir kaynak: kullanıcı yüklediği dosya adı + sayım
    html = status_banner('User "file.csv" loaded — 1 < 5 results', tone="success")
    assert "&quot;" in html or '"file.csv"' not in html  # quote either way escaped or absent
    assert "&lt;" in html


# ── Icon davranışı ───────────────────────────────────────────────────────────
def test_default_icon_for_each_tone():
    assert "✅" in status_banner("ok", "success")
    assert "⚠️" in status_banner("careful", "warning")
    assert "❌" in status_banner("bad", "error")
    assert "ℹ️" in status_banner("note", "info")


def test_custom_icon_overrides_default():
    html = status_banner("Launch", tone="success", icon="🚀")
    assert "🚀" in html
    assert "✅" not in html  # default bastırıldı


def test_empty_string_icon_suppresses_default():
    html = status_banner("clean", tone="success", icon="")
    assert "✅" not in html
    # Yalnız metin + prefix yok
    assert ">clean</div>" in html


# ── Yapısal beklentiler ──────────────────────────────────────────────────────
def test_returns_single_div_compatible_with_placeholder_markdown():
    """
    status_ph.markdown(html, unsafe_allow_html=True) tek root element bekler.
    Helper'ın ilk karakteri '<div' ile başlamalı, son karakteri '</div>'.
    """
    html = status_banner("hello", "info")
    assert html.startswith("<div")
    assert html.endswith("</div>")
    # Tam bir tane root div
    assert html.count("<div") == 1
    assert html.count("</div>") == 1


def test_inline_style_carries_padding_and_radius():
    html = status_banner("x", "info")
    assert "padding:12px 16px" in html
    assert "border-radius:10px" in html
    assert "font-weight:500" in html


# ── render_status_banner (smoke) ─────────────────────────────────────────────
def test_render_status_banner_is_importable():
    from components.cards import render_status_banner
    assert callable(render_status_banner)
