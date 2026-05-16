"""
components/styles.py — Global design system and CSS.

Provides McKinsey/BCG-style professional aesthetics:
- Clean typography (Inter)
- Card-based layout with subtle shadows
- Corporate navy + blue palette
- Consistent spacing grid (8px)
"""

from __future__ import annotations

import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# DESIGN TOKENS (single source of truth)
# ─────────────────────────────────────────────────────────────────────────────
TOKENS = {
    # Brand
    "primary":      "#0F2A44",   # navy (headers, sidebar)
    "accent":       "#2563EB",   # professional blue (CTAs, highlights)
    "accent_soft":  "#DBEAFE",   # blue tint (hover, badges)
    "accent_dark":  "#1D4ED8",   # darker blue (active states)

    # Surface
    "bg":           "#F8FAFC",   # page background
    "surface":      "#FFFFFF",   # card background
    "surface_alt":  "#F1F5F9",   # muted surface

    # Text
    "text":         "#0F172A",   # primary text
    "text_muted":   "#475569",   # secondary text
    "text_subtle":  "#94A3B8",   # captions, small text

    # Border
    "border":       "#E2E8F0",
    "border_soft":  "#F1F5F9",

    # Semantic
    "success":      "#10B981",
    "success_bg":   "#D1FAE5",
    "warning":      "#F59E0B",
    "warning_bg":   "#FEF3C7",
    "danger":       "#EF4444",
    "danger_bg":    "#FEE2E2",
    "info":         "#3B82F6",
    "info_bg":      "#DBEAFE",

    # Category palette (consistent across maps/charts)
    "cat_buildings":      "#3B82F6",
    "cat_health":         "#EF4444",
    "cat_education":      "#10B981",
    "cat_green_area":     "#059669",
    "cat_transport":      "#F59E0B",
    "cat_commerce":       "#8B5CF6",
    "cat_infrastructure": "#64748B",
    "cat_culture":        "#EC4899",
}


# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL CSS
# ─────────────────────────────────────────────────────────────────────────────
def _global_css() -> str:
    t = TOKENS
    return f"""
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">

<style>
/* ═══════════════════════════════════════════════════════════════════════════
   BASE
═══════════════════════════════════════════════════════════════════════════ */
html, body, [class*="css"], .stApp {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    -webkit-font-smoothing: antialiased;
    color: {t["text"]};
}}

.stApp {{
    background: {t["bg"]};
}}

.block-container {{
    padding-top: 2rem;
    padding-bottom: 3rem;
    max-width: 1400px;
}}

/* Hide Streamlit chrome */
#MainMenu {{ visibility: hidden; }}
footer {{ visibility: hidden; }}
header[data-testid="stHeader"] {{
    background: transparent;
    height: 0;
}}

/* ═══════════════════════════════════════════════════════════════════════════
   TYPOGRAPHY
═══════════════════════════════════════════════════════════════════════════ */
h1 {{
    font-weight: 700 !important;
    letter-spacing: -0.02em !important;
    color: {t["text"]} !important;
    font-size: 2rem !important;
    line-height: 1.2 !important;
    margin-bottom: 0.5rem !important;
}}

h2 {{
    font-weight: 600 !important;
    letter-spacing: -0.01em !important;
    color: {t["text"]} !important;
    font-size: 1.375rem !important;
    margin-top: 1.5rem !important;
    margin-bottom: 0.75rem !important;
}}

h3 {{
    font-weight: 600 !important;
    color: {t["text"]} !important;
    font-size: 1.125rem !important;
}}

p, span, label, div {{
    color: {t["text"]};
}}

small, .caption {{
    color: {t["text_subtle"]};
    font-size: 0.8125rem;
}}

/* ═══════════════════════════════════════════════════════════════════════════
   SIDEBAR
═══════════════════════════════════════════════════════════════════════════ */
[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, {t["primary"]} 0%, #0B1F33 100%);
    border-right: 1px solid {t["primary"]};
}}

[data-testid="stSidebar"] * {{
    color: #E2E8F0 !important;
}}

[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] h4 {{
    color: #FFFFFF !important;
    font-weight: 600 !important;
}}

[data-testid="stSidebar"] hr {{
    border-color: rgba(255,255,255,0.08) !important;
    margin: 1rem 0 !important;
}}

[data-testid="stSidebar"] .stSelectbox > div > div,
[data-testid="stSidebar"] .stTextInput > div > div > input,
[data-testid="stSidebar"] .stMultiSelect > div > div {{
    background-color: rgba(255,255,255,0.06) !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    color: #FFFFFF !important;
    border-radius: 8px !important;
}}

[data-testid="stSidebar"] .stRadio label,
[data-testid="stSidebar"] .stCheckbox label {{
    color: #CBD5E1 !important;
}}

/* Sidebar brand block */
.sidebar-brand {{
    padding: 0.5rem 0 1.25rem 0;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    margin-bottom: 1rem;
}}
.sidebar-brand-title {{
    font-size: 1.05rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    color: #FFFFFF;
}}
.sidebar-brand-sub {{
    font-size: 0.75rem;
    color: #94A3B8;
    margin-top: 2px;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}}

/* ═══════════════════════════════════════════════════════════════════════════
   BUTTONS
═══════════════════════════════════════════════════════════════════════════ */
.stButton > button,
.stDownloadButton > button,
.stFormSubmitButton > button {{
    height: 40px !important;
    border-radius: 8px !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.875rem !important;
    letter-spacing: -0.005em !important;
    padding: 0 1.1rem !important;
    line-height: 1 !important;
    transition: background-color 0.15s ease,
                border-color 0.15s ease,
                box-shadow 0.15s ease,
                color 0.15s ease !important;
    box-shadow: 0 1px 2px rgba(15,23,42,0.04) !important;
    cursor: pointer !important;
}}

/* Secondary (default) */
.stButton > button,
.stDownloadButton > button {{
    background: #F8FAFC !important;
    border: 1px solid {t["border"]} !important;
    color: {t["text"]} !important;
}}

.stButton > button:hover,
.stDownloadButton > button:hover {{
    background: {t["accent_soft"]} !important;
    border-color: {t["accent"]} !important;
    color: {t["accent_dark"]} !important;
    box-shadow: 0 2px 6px rgba(15,23,42,0.06) !important;
}}

.stButton > button:active,
.stDownloadButton > button:active,
.stFormSubmitButton > button:active {{
    transform: translateY(1px);
    box-shadow: inset 0 1px 2px rgba(15,23,42,0.08) !important;
}}

/* Primary */
.stButton > button[kind="primary"],
.stFormSubmitButton > button {{
    background: {t["accent"]} !important;
    border: 1px solid {t["accent"]} !important;
    color: #FFFFFF !important;
    box-shadow: 0 1px 2px rgba(37,99,235,0.20) !important;
}}

.stButton > button[kind="primary"]:hover,
.stFormSubmitButton > button:hover {{
    background: {t["accent_dark"]} !important;
    border-color: {t["accent_dark"]} !important;
    color: #FFFFFF !important;
    box-shadow: 0 4px 10px rgba(37,99,235,0.25) !important;
}}

/* Tertiary — link-style */
.stButton > button[kind="tertiary"] {{
    background: transparent !important;
    border: 1px solid transparent !important;
    color: {t["accent_dark"]} !important;
    box-shadow: none !important;
}}
.stButton > button[kind="tertiary"]:hover {{
    background: {t["accent_soft"]} !important;
    border-color: transparent !important;
}}

/* Keyboard focus ring */
.stButton > button:focus-visible,
.stDownloadButton > button:focus-visible,
.stFormSubmitButton > button:focus-visible {{
    outline: none !important;
    box-shadow: 0 0 0 3px {t["accent_soft"]},
                0 0 0 4px {t["accent"]} !important;
}}

/* Disabled */
.stButton > button:disabled,
.stDownloadButton > button:disabled,
.stFormSubmitButton > button:disabled {{
    background: {t["surface_alt"]} !important;
    border-color: {t["border"]} !important;
    color: {t["text_subtle"]} !important;
    cursor: not-allowed !important;
    box-shadow: none !important;
    opacity: 0.7;
}}
.stButton > button:disabled:hover,
.stDownloadButton > button:disabled:hover {{
    background: {t["surface_alt"]} !important;
    border-color: {t["border"]} !important;
    color: {t["text_subtle"]} !important;
    transform: none !important;
}}

/* Sidebar overrides — readable on dark navy */
[data-testid="stSidebar"] .stButton > button,
[data-testid="stSidebar"] .stDownloadButton > button {{
    background: rgba(255,255,255,0.06) !important;
    border: 1px solid rgba(255,255,255,0.14) !important;
    color: #FFFFFF !important;
}}
[data-testid="stSidebar"] .stButton > button:hover,
[data-testid="stSidebar"] .stDownloadButton > button:hover {{
    background: rgba(255,255,255,0.12) !important;
    border-color: rgba(255,255,255,0.28) !important;
    color: #FFFFFF !important;
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
    background: {t["accent"]} !important;
    border-color: {t["accent"]} !important;
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {{
    background: {t["accent_dark"]} !important;
    border-color: {t["accent_dark"]} !important;
}}

/* ═══════════════════════════════════════════════════════════════════════════
   INPUTS
═══════════════════════════════════════════════════════════════════════════ */
.stTextInput > div > div > input,
.stSelectbox > div > div,
.stNumberInput > div > div > input {{
    border-radius: 8px !important;
    border: 1px solid {t["border"]} !important;
    font-family: 'Inter', sans-serif !important;
}}

.stTextInput > div > div > input:focus,
.stSelectbox > div > div:focus-within {{
    border-color: {t["accent"]} !important;
    box-shadow: 0 0 0 3px {t["accent_soft"]} !important;
}}

/* ═══════════════════════════════════════════════════════════════════════════
   METRICS
═══════════════════════════════════════════════════════════════════════════ */
[data-testid="stMetric"] {{
    background: {t["surface"]};
    border: 1px solid {t["border"]};
    border-radius: 12px;
    padding: 1.25rem 1.25rem;
    box-shadow: 0 1px 3px rgba(15,23,42,0.04), 0 1px 2px rgba(15,23,42,0.03);
    transition: all 0.15s ease;
}}

[data-testid="stMetric"]:hover {{
    border-color: {t["accent"]};
    box-shadow: 0 4px 16px rgba(15,23,42,0.06);
}}

[data-testid="stMetricLabel"] {{
    font-size: 0.8125rem !important;
    color: {t["text_muted"]} !important;
    font-weight: 500 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.04em !important;
}}

[data-testid="stMetricValue"] {{
    font-size: 1.75rem !important;
    font-weight: 700 !important;
    color: {t["text"]} !important;
    letter-spacing: -0.02em !important;
}}

[data-testid="stMetricDelta"] {{
    font-size: 0.8125rem !important;
}}

/* ═══════════════════════════════════════════════════════════════════════════
   TABS
═══════════════════════════════════════════════════════════════════════════ */
.stTabs [data-baseweb="tab-list"] {{
    gap: 4px;
    background: {t["surface_alt"]};
    padding: 4px;
    border-radius: 10px;
    border: 1px solid {t["border"]};
}}

.stTabs [data-baseweb="tab"] {{
    border-radius: 7px !important;
    padding: 0.5rem 1rem !important;
    color: {t["text_muted"]} !important;
    background: transparent !important;
    font-weight: 500 !important;
    border: none !important;
}}

.stTabs [aria-selected="true"] {{
    background: {t["surface"]} !important;
    color: {t["accent_dark"]} !important;
    box-shadow: 0 1px 3px rgba(15,23,42,0.06) !important;
}}

/* ═══════════════════════════════════════════════════════════════════════════
   DATAFRAME
═══════════════════════════════════════════════════════════════════════════ */
[data-testid="stDataFrame"] {{
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid {t["border"]};
}}

/* ═══════════════════════════════════════════════════════════════════════════
   EXPANDER
═══════════════════════════════════════════════════════════════════════════ */
[data-testid="stExpander"] {{
    border: 1px solid {t["border"]} !important;
    border-radius: 10px !important;
    background: {t["surface"]} !important;
    box-shadow: 0 1px 2px rgba(15,23,42,0.03) !important;
    overflow: hidden;
}}

[data-testid="stExpander"] summary,
[data-testid="stExpander"] details > summary {{
    padding: 0.65rem 0.9rem !important;
    font-weight: 600 !important;
    font-size: 0.875rem !important;
    color: {t["text"]} !important;
    border-radius: 10px !important;
    transition: background-color 0.15s ease !important;
}}
[data-testid="stExpander"] summary:hover {{
    background: {t["surface_alt"]} !important;
}}
[data-testid="stExpander"] svg {{
    color: {t["text_muted"]} !important;
    fill: currentColor !important;
}}

/* Sidebar expander — koyu navy zeminde okunabilir */
[data-testid="stSidebar"] [data-testid="stExpander"] {{
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
    box-shadow: none !important;
}}
[data-testid="stSidebar"] [data-testid="stExpander"] summary {{
    color: #FFFFFF !important;
    font-weight: 600 !important;
}}
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {{
    background: rgba(255,255,255,0.08) !important;
}}
[data-testid="stSidebar"] [data-testid="stExpander"] svg {{
    color: #CBD5E1 !important;
}}
[data-testid="stSidebar"] [data-testid="stExpander"] p,
[data-testid="stSidebar"] [data-testid="stExpander"] span,
[data-testid="stSidebar"] [data-testid="stExpander"] label {{
    color: #E2E8F0 !important;
}}

/* ═══════════════════════════════════════════════════════════════════════════
   ALERTS
═══════════════════════════════════════════════════════════════════════════ */
.stAlert {{
    border-radius: 10px !important;
    border: 1px solid transparent !important;
}}

/* ═══════════════════════════════════════════════════════════════════════════
   PROGRESS BAR
═══════════════════════════════════════════════════════════════════════════ */
.stProgress > div > div > div {{
    background: linear-gradient(90deg, {t["accent"]}, {t["accent_dark"]}) !important;
    border-radius: 999px !important;
}}

/* ═══════════════════════════════════════════════════════════════════════════
   CUSTOM COMPONENTS
═══════════════════════════════════════════════════════════════════════════ */

/* Hero section */
.hero {{
    background: linear-gradient(135deg, {t["primary"]} 0%, #163959 60%, {t["accent_dark"]} 100%);
    border-radius: 16px;
    padding: 3rem 3rem;
    color: #FFFFFF;
    position: relative;
    overflow: hidden;
    margin-bottom: 1.5rem;
    box-shadow: 0 10px 40px rgba(15,42,68,0.15);
}}
.hero::before {{
    content: "";
    position: absolute;
    top: -50%;
    right: -10%;
    width: 500px;
    height: 500px;
    background: radial-gradient(circle, rgba(59,130,246,0.25), transparent 70%);
    border-radius: 50%;
    pointer-events: none;
}}
.hero-eyebrow {{
    display: inline-block;
    padding: 5px 12px;
    background: rgba(255,255,255,0.1);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #BFDBFE;
    margin-bottom: 1rem;
}}
.hero-title {{
    font-size: 2.5rem;
    font-weight: 700;
    letter-spacing: -0.03em;
    color: #FFFFFF;
    line-height: 1.1;
    margin-bottom: 0.75rem;
    position: relative;
}}
.hero-subtitle {{
    font-size: 1.0625rem;
    color: #CBD5E1;
    max-width: 720px;
    line-height: 1.55;
    position: relative;
}}

/* Page header */
.page-header {{
    margin-bottom: 1.5rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid {t["border"]};
}}
.page-header-eyebrow {{
    color: {t["accent"]};
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-bottom: 0.25rem;
}}
.page-header-title {{
    font-size: 1.75rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: {t["text"]};
    margin: 0;
}}
.page-header-sub {{
    color: {t["text_muted"]};
    font-size: 0.9375rem;
    margin-top: 0.25rem;
}}

/* Card */
.card {{
    background: {t["surface"]};
    border: 1px solid {t["border"]};
    border-radius: 12px;
    padding: 1.5rem;
    box-shadow: 0 1px 3px rgba(15,23,42,0.04);
    transition: all 0.15s ease;
    height: 100%;
}}
.card:hover {{
    border-color: {t["accent"]};
    box-shadow: 0 8px 24px rgba(15,23,42,0.06);
    transform: translateY(-2px);
}}
.card-icon {{
    width: 44px;
    height: 44px;
    border-radius: 10px;
    background: {t["accent_soft"]};
    color: {t["accent_dark"]};
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.25rem;
    margin-bottom: 1rem;
}}
.card-title {{
    font-size: 1rem;
    font-weight: 600;
    color: {t["text"]};
    margin-bottom: 0.35rem;
}}
.card-text {{
    font-size: 0.875rem;
    color: {t["text_muted"]};
    line-height: 1.5;
}}

/* KPI box */
.kpi {{
    background: {t["surface"]};
    border: 1px solid {t["border"]};
    border-radius: 12px;
    padding: 1.25rem 1.25rem;
    box-shadow: 0 1px 3px rgba(15,23,42,0.04);
    position: relative;
    overflow: hidden;
}}
.kpi-label {{
    font-size: 0.75rem;
    color: {t["text_muted"]};
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 600;
    margin-bottom: 0.35rem;
}}
.kpi-value {{
    font-size: 1.875rem;
    font-weight: 700;
    color: {t["text"]};
    letter-spacing: -0.025em;
    line-height: 1.1;
}}
.kpi-delta {{
    font-size: 0.8125rem;
    margin-top: 0.25rem;
    color: {t["text_subtle"]};
}}
.kpi-accent {{
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 3px;
    background: {t["accent"]};
}}

/* Status badges */
.badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 500;
    letter-spacing: 0.01em;
}}
.badge-success {{ background: {t["success_bg"]}; color: #065F46; }}
.badge-warning {{ background: {t["warning_bg"]}; color: #92400E; }}
.badge-danger  {{ background: {t["danger_bg"]};  color: #991B1B; }}
.badge-info    {{ background: {t["info_bg"]};    color: #1E40AF; }}
.badge-neutral {{ background: {t["surface_alt"]}; color: {t["text_muted"]}; }}

/* Section divider */
.section-divider {{
    height: 1px;
    background: {t["border"]};
    margin: 2rem 0 1.5rem 0;
}}

/* Status strip (bottom of hero / top of content) */
.status-strip {{
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 1rem;
}}
.status-pill {{
    background: {t["surface"]};
    border: 1px solid {t["border"]};
    border-radius: 999px;
    padding: 6px 14px;
    font-size: 0.8125rem;
    color: {t["text_muted"]};
    display: inline-flex;
    align-items: center;
    gap: 6px;
}}
.status-pill-dot {{
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: {t["accent"]};
}}
.status-pill-ok .status-pill-dot    {{ background: {t["success"]}; }}
.status-pill-warn .status-pill-dot  {{ background: {t["warning"]}; }}
.status-pill-error .status-pill-dot {{ background: {t["danger"]}; }}

/* Footer */
.app-footer {{
    text-align: center;
    color: {t["text_subtle"]};
    font-size: 0.75rem;
    padding: 2rem 0 0.5rem 0;
    border-top: 1px solid {t["border_soft"]};
    margin-top: 3rem;
}}
.app-footer a {{
    color: {t["accent"]};
    text-decoration: none;
}}

/* Step indicator */
.stepper {{
    display: flex;
    gap: 8px;
    margin-bottom: 1.5rem;
}}
.step {{
    flex: 1;
    padding: 12px 16px;
    background: {t["surface"]};
    border: 1px solid {t["border"]};
    border-radius: 10px;
    font-size: 0.875rem;
    color: {t["text_muted"]};
    position: relative;
}}
.step-num {{
    display: inline-block;
    width: 22px;
    height: 22px;
    line-height: 22px;
    text-align: center;
    background: {t["surface_alt"]};
    border-radius: 50%;
    font-size: 0.75rem;
    font-weight: 600;
    margin-right: 8px;
    color: {t["text_muted"]};
}}
.step-active {{
    border-color: {t["accent"]};
    background: {t["accent_soft"]};
    color: {t["accent_dark"]};
}}
.step-active .step-num {{
    background: {t["accent"]};
    color: #FFFFFF;
}}
.step-done {{
    border-color: {t["success"]};
    background: {t["success_bg"]};
    color: #065F46;
}}
.step-done .step-num {{
    background: {t["success"]};
    color: #FFFFFF;
}}
</style>
"""


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────
def apply_global_styles() -> None:
    """Inject global CSS. Call once at the top of every page."""
    st.markdown(_global_css(), unsafe_allow_html=True)


def configure_page(
    title: str,
    icon: str = "🗺️",
    layout: str = "wide",
    sidebar: str = "expanded",
) -> None:
    """Standard page config wrapper used across all pages."""
    st.set_page_config(
        page_title=f"{title} · Istanbul SDSS",
        page_icon=icon,
        layout=layout,
        initial_sidebar_state=sidebar,
        menu_items={
            "About": "Istanbul Spatial Decision Support System — "
                     "OpenStreetMap-based urban data extraction and analysis."
        },
    )
    apply_global_styles()
