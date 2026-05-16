"""
components/cards.py — Reusable UI components.

Provides high-level, opinionated building blocks used across pages:
- hero()              — landing-page hero banner
- page_header()       — standard page title + subtitle
- feature_card()      — icon + title + text card (for Home page)
- kpi_card()          — KPI/metric box
- status_strip()      — compact pill row for context (district, category count, …)
- section_title()     — small section divider with title
- badge()             — inline status badge
- stepper()           — horizontal step indicator
- empty_state()       — empty-state placeholder
- footer()            — page footer

HTML escape policy (defense-in-depth):
    Tüm dinamik string parametreler (title/subtitle/label/value/text/...) bu
    bileşenlerden HTML olarak render ediliyor (Streamlit
    `unsafe_allow_html=True`). Folium popup'larında olduğu gibi UI tarafında
    da bilinçli **input sanitization** uyguluyoruz: kullanıcı yüklemesi,
    serbest text input ve OSM kaynaklı string'ler güvenle yansıtılabilsin.

    `_esc()` helper'ı `html.escape()`'i sarar; None / sayısal / Markup-safe
    girdiler için makul davranır. Sabit (geliştirici tarafından yazılmış)
    HTML parçaları — örn. eyebrow ikonları, paragraf yapısı — escape EDİLMEZ;
    bunlar tasarım sisteminin parçasıdır. Sadece DIŞARIDAN gelen string'ler
    escape edilir.

    Niye: aynı projede Folium katmanı `safe_field` ile escape ediyordu ama
    Streamlit kartları ham basıyordu — asimetrik savunma. Bu modül artık
    iki katmanı eşit standartta tutuyor.
"""

from __future__ import annotations

import html
from typing import Literal

import streamlit as st


def _esc(value) -> str:
    """
    Dinamik string parametreyi HTML-escape eder.

    None → "" (sessizce yutulur; çağırırken `if x:` koruması olabilir,
    olmasa bile crash etmez).

    Numeric (int/float) doğrudan str() — `:,` formatlama caller'ın
    sorumluluğu; biz sadece güvenliği garantileriz.

    Markup'a izin verilmiş string için bu helper'ı KULLANMAYIN; yerine
    sabit HTML literal'i yazın (örn. eyebrow ikonu).
    """
    if value is None:
        return ""
    return html.escape(str(value))


# ─────────────────────────────────────────────────────────────────────────────
# HERO
# ─────────────────────────────────────────────────────────────────────────────
def hero(
    title: str,
    subtitle: str,
    eyebrow: str | None = None,
) -> None:
    eyebrow_html = f'<div class="hero-eyebrow">{_esc(eyebrow)}</div>' if eyebrow else ""
    st.markdown(
        f"""
        <div class="hero">
            {eyebrow_html}
            <div class="hero-title">{_esc(title)}</div>
            <div class="hero-subtitle">{_esc(subtitle)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# PAGE HEADER
# ─────────────────────────────────────────────────────────────────────────────
def page_header(
    title: str,
    subtitle: str | None = None,
    eyebrow: str | None = None,
) -> None:
    parts = ['<div class="page-header">']
    if eyebrow:
        parts.append(f'<div class="page-header-eyebrow">{_esc(eyebrow)}</div>')
    parts.append(f'<div class="page-header-title">{_esc(title)}</div>')
    if subtitle:
        parts.append(f'<div class="page-header-sub">{_esc(subtitle)}</div>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE CARD
# ─────────────────────────────────────────────────────────────────────────────
def feature_card(icon: str, title: str, text: str) -> None:
    # Not: `icon` çoğunlukla emoji string'i (sabit, geliştirici tarafından
    # yazılmış). Yine de defansif olarak escape ediyoruz — emoji etkilenmez.
    st.markdown(
        f"""
        <div class="card">
            <div class="card-icon">{_esc(icon)}</div>
            <div class="card-title">{_esc(title)}</div>
            <div class="card-text">{_esc(text)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# KPI CARD
# ─────────────────────────────────────────────────────────────────────────────
def kpi_card(
    label: str,
    value: str | int | float,
    delta: str | None = None,
    accent: bool = True,
) -> None:
    accent_bar = '<div class="kpi-accent"></div>' if accent else ""
    delta_html = f'<div class="kpi-delta">{_esc(delta)}</div>' if delta else ""

    # Format numbers with thousands separator
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value_fmt = f"{value:,}" if float(value).is_integer() else f"{value:,.1f}"
    else:
        value_fmt = _esc(value)   # caller string verirse escape; sayısal zaten güvenli

    st.markdown(
        f"""
        <div class="kpi">
            {accent_bar}
            <div class="kpi-label">{_esc(label)}</div>
            <div class="kpi-value">{value_fmt}</div>
            {delta_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# STATUS STRIP (row of pills)
# ─────────────────────────────────────────────────────────────────────────────
def status_strip(items: list[dict]) -> None:
    """
    items: list of {"label": str, "value": str, "tone": "ok"|"warn"|"error"|None}

    `label` ve `value` dinamik (kullanıcı verisinden gelebilir: dosya adı,
    ilçe seçimi, sayım sonucu, vs.) → html.escape uygulanır.
    """
    pills = []
    for it in items:
        tone = it.get("tone")
        cls = "status-pill"
        if tone == "ok":
            cls += " status-pill-ok"
        elif tone == "warn":
            cls += " status-pill-warn"
        elif tone == "error":
            cls += " status-pill-error"
        pills.append(
            f'<div class="{cls}"><span class="status-pill-dot"></span>'
            f'<span style="color:#475569">{_esc(it.get("label"))}</span>'
            f'<strong style="color:#0F172A">{_esc(it.get("value"))}</strong></div>'
        )
    st.markdown(
        f'<div class="status-strip">{"".join(pills)}</div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# SECTION TITLE / DIVIDER
# ─────────────────────────────────────────────────────────────────────────────
def section_title(title: str, subtitle: str | None = None) -> None:
    sub = (
        f'<div style="color:#64748B;font-size:0.875rem;margin-top:2px">{_esc(subtitle)}</div>'
        if subtitle else ""
    )
    st.markdown(
        f"""
        <div style="margin:1.5rem 0 0.75rem 0">
            <div style="font-size:1.125rem;font-weight:600;color:#0F172A">{_esc(title)}</div>
            {sub}
        </div>
        """,
        unsafe_allow_html=True,
    )


def divider() -> None:
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# BADGE
# ─────────────────────────────────────────────────────────────────────────────
Tone = Literal["success", "warning", "danger", "info", "neutral"]


def badge(text: str, tone: Tone = "neutral") -> str:
    """Return HTML string (inline use inside other markdown).

    `text` escape edilir; `tone` Literal — geliştirici-kontrollü.
    """
    return f'<span class="badge badge-{tone}">{_esc(text)}</span>'


def render_badge(text: str, tone: Tone = "neutral") -> None:
    st.markdown(badge(text, tone), unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# STATUS BANNER
# ─────────────────────────────────────────────────────────────────────────────
BannerTone = Literal["success", "warning", "error", "info"]

# Tone → (background, foreground) renk çiftleri. Tailwind-uyumlu pastel arka plan +
# yoğun foreground (~7:1 kontrast). Excel exporter ve translations modülündeki
# renk seçimleriyle senkron — UI/Excel arası tutarlı semantic palette.
_BANNER_COLORS: dict[str, tuple[str, str]] = {
    "success": ("#D1FAE5", "#065F46"),
    "warning": ("#FEF3C7", "#92400E"),
    "error":   ("#FEE2E2", "#991B1B"),
    "info":    ("#DBEAFE", "#1E40AF"),
}

# Tone → varsayılan icon. Caller `icon=""` ile bastırabilir veya kendi emoji'sini
# `icon="🚀"` ile geçebilir; metin içinde manuel prefix yerine bu yolu tercih edin.
_BANNER_DEFAULT_ICON: dict[str, str] = {
    "success": "✅",
    "warning": "⚠️",
    "error":   "❌",
    "info":    "ℹ️",
}


def status_banner(
    text: str,
    tone: BannerTone = "info",
    *,
    icon: str | None = None,
) -> str:
    """
    Return an HTML banner string suitable for `st.markdown(..., unsafe_allow_html=True)`
    or `placeholder.markdown(...)` (status_ph pattern).

    `text` is html-escaped — safe to pass user-derived strings, counts, file
    names. If you need HTML inside the banner, render it yourself; this helper
    optimises for the dominant "plain message + emoji" case.

    `icon=None` → tone-specific default (✅/⚠️/❌/ℹ️). Pass `icon=""` to suppress.

    Returns HTML; mirrors `badge()` pattern. Use `render_status_banner()` to
    render directly into the main panel; for `status_ph.markdown(...)` keep using
    the returned string.
    """
    bg, fg = _BANNER_COLORS.get(tone, _BANNER_COLORS["info"])
    glyph = _BANNER_DEFAULT_ICON.get(tone, "") if icon is None else icon
    # icon defansif olarak escape edilir — emoji etkilenmez ama "<" gibi sembol
    # injection'ı engellenir.
    prefix = f"{_esc(glyph)} " if glyph else ""
    return (
        f'<div style="background:{bg};color:{fg};padding:12px 16px;'
        f'border-radius:10px;font-weight:500">'
        f'{prefix}{_esc(text)}</div>'
    )


def render_status_banner(
    text: str,
    tone: BannerTone = "info",
    *,
    icon: str | None = None,
) -> None:
    """Convenience: render banner directly via st.markdown."""
    st.markdown(status_banner(text, tone, icon=icon), unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# STEPPER
# ─────────────────────────────────────────────────────────────────────────────
def stepper(steps: list[str], current: int = 0) -> None:
    """
    steps:   list of step labels (escape edilir — caller'dan gelen string'ler)
    current: 0-indexed active step (items before it are "done")
    """
    items = []
    for i, label in enumerate(steps):
        cls = "step"
        if i < current:
            cls += " step-done"
        elif i == current:
            cls += " step-active"
        items.append(
            f'<div class="{cls}"><span class="step-num">{i+1}</span>{_esc(label)}</div>'
        )
    st.markdown(f'<div class="stepper">{"".join(items)}</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# EMPTY STATE
# ─────────────────────────────────────────────────────────────────────────────
def empty_state(
    title: str,
    text: str,
    icon: str = "📭",
    cta: str | None = None,
    cta_target: str | None = None,
) -> None:
    cta_html = ""
    if cta and cta_target:
        # cta_target ham URL — geliştirici tarafından sabit veriliyor. Yine de
        # `javascript:` gibi enjeksiyonu önlemek için `_esc` uygula
        # (URL'leri html.escape "&" → "&amp;" yapar ama doğru render edilir).
        cta_html = (
            f'<a href="{_esc(cta_target)}" target="_self" '
            f'style="display:inline-block;margin-top:1rem;padding:0.55rem 1.25rem;'
            f'background:#2563EB;color:white;border-radius:8px;text-decoration:none;'
            f'font-weight:500;font-size:0.875rem">{_esc(cta)}</a>'
        )
    st.markdown(
        f"""
        <div style="background:#FFFFFF;border:1px dashed #CBD5E1;border-radius:12px;
                    padding:3rem 2rem;text-align:center">
            <div style="font-size:2.25rem;margin-bottom:0.75rem">{_esc(icon)}</div>
            <div style="font-size:1.125rem;font-weight:600;color:#0F172A;margin-bottom:0.35rem">{_esc(title)}</div>
            <div style="font-size:0.9375rem;color:#64748B;max-width:420px;margin:0 auto">{_esc(text)}</div>
            {cta_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────────────────────────
def footer() -> None:
    st.markdown(
        """
        <div class="app-footer">
            <div><strong>Istanbul Spatial Decision Support System</strong></div>
            <div style="margin-top:4px">
                Data source: <a href="https://www.openstreetmap.org" target="_blank">OpenStreetMap</a>
                · Overpass API · © OSM Contributors, ODbL
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR BRAND
# ─────────────────────────────────────────────────────────────────────────────
def sidebar_brand() -> None:
    """Consistent sidebar header used across pages."""
    st.sidebar.markdown(
        """
        <div class="sidebar-brand">
            <div class="sidebar-brand-title">🗺️ Istanbul SDSS</div>
            <div class="sidebar-brand-sub">Spatial Decision Support</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
