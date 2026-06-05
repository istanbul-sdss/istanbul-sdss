"""
Spatial_Data_Collection_Tool.py — Istanbul Spatial Decision Support System (Home page)

A professional, multi-page Streamlit application for OpenStreetMap-based
urban data extraction, analysis, and decision support for Istanbul.

Run:
    streamlit run Spatial_Data_Collection_Tool.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent))

# ── Registry / Rule compatibility check (kept from legacy app) ──────────────
from src.config.category_registry import CATEGORY_REGISTRY
from src.config.tag_rules import TAG_RULES

_missing = [
    f"{ck}/{s['key']} → {s['code']}"
    for ck, cv in CATEGORY_REGISTRY.items()
    for s in cv.get("subcategories", [])
    if s.get("code") not in TAG_RULES
]
if _missing:
    raise RuntimeError("Missing TAG_RULES entries:\n" + "\n".join(_missing))

# ── Project imports ─────────────────────────────────────────────────────────
from components import cards
from components.state import get_district, get_nonempty_results, has_data, init_state
from components.styles import configure_page
from components.translations import get_main_category_options_en
from src.config.settings import ISTANBUL_ILCELER

# ════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ════════════════════════════════════════════════════════════════════════════
configure_page(title="Home", icon="🏠")
init_state()


# ════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════════════════════
cards.sidebar_brand()
st.sidebar.markdown("### Quick guide")
st.sidebar.markdown(
    """
    Navigate via the **list above**. Typical workflow:
    1. 📊 **Data Extraction** — fetch OSM data
    2. 🗺️ **Map Visualization** — explore on a map
    3. 📈 **Analytics Dashboard** — KPIs & distribution
    4. 🔍 **Name Lookup** *(optional)* — match by name list
    5. 🔄 **Neighborhood Sync** *(maintenance)* — refresh boundaries
    """
)
st.sidebar.markdown("---")
st.sidebar.markdown("### Quick Facts")
st.sidebar.markdown(
    f"""
    <div style="font-size:0.875rem;color:#CBD5E1;line-height:1.7">
      • <b>{len(ISTANBUL_ILCELER)}</b> Istanbul districts<br>
      • <b>{sum(1 for k in CATEGORY_REGISTRY if k != "admin_boundaries")}</b> data categories<br>
      • Data source: OpenStreetMap
    </div>
    """,
    unsafe_allow_html=True,
)

st.sidebar.markdown("---")
st.sidebar.markdown(
    """
    <div style="font-size:0.75rem;color:#64748B;line-height:1.5">
    Data: OpenStreetMap · Overpass API<br>
    © OSM Contributors, ODbL
    </div>
    """,
    unsafe_allow_html=True,
)


# ════════════════════════════════════════════════════════════════════════════
# HERO
# ════════════════════════════════════════════════════════════════════════════
cards.hero(
    eyebrow="Istanbul Spatial Decision Support System",
    title="Urban intelligence, powered by open spatial data.",
    subtitle=(
        "Extract, process, and analyze fine-grained geographic data for any Istanbul "
        "district — buildings, hospitals, schools, parks, transport, and more — "
        "sourced from OpenStreetMap and delivered as decision-ready datasets."
    ),
)

# Session status strip
if has_data():
    nonempty = get_nonempty_results()
    total = sum(len(v["df"]) for v in nonempty.values())
    cards.status_strip([
        {"label": "Active district:", "value": get_district() or "—", "tone": "ok"},
        {"label": "Records loaded:",  "value": f"{total:,}",          "tone": "ok"},
        {"label": "Categories:",      "value": str(len(nonempty)),    "tone": "ok"},
    ])
else:
    cards.status_strip([
        {"label": "Status:", "value": "No data loaded yet", "tone": "warn"},
        {"label": "Next step:", "value": "Open Data Extraction →", "tone": None},
    ])


# ════════════════════════════════════════════════════════════════════════════
# WHAT THE SYSTEM DOES
# ════════════════════════════════════════════════════════════════════════════
cards.section_title(
    "What the system does",
    "Four focused capabilities that turn raw OSM data into decisions.",
)

c1, c2, c3, c4 = st.columns(4, gap="medium")

with c1:
    cards.feature_card(
        icon="🎯",
        title="Targeted extraction",
        text="Pick any of Istanbul's 39 districts and select from 8 data categories. "
             "Only fetch what you need.",
    )
with c2:
    cards.feature_card(
        icon="🧹",
        title="Clean & matched",
        text="Each record is deduplicated, geocoded, quality-scored, and matched to its "
             "neighbourhood — so downstream analysis starts clean.",
    )
with c3:
    cards.feature_card(
        icon="🗺️",
        title="Interactive maps",
        text="Explore results on clustered, theme-aware Leaflet maps with layer toggles, "
             "popups, and boundary overlays.",
    )
with c4:
    cards.feature_card(
        icon="📥",
        title="Decision-ready outputs",
        text="Export multi-sheet Excel workbooks, tidy CSVs, or GeoJSON — all in English, "
             "ready for reports or GIS pipelines.",
    )


# ════════════════════════════════════════════════════════════════════════════
# WORKFLOW
# ════════════════════════════════════════════════════════════════════════════
cards.section_title("How it works", "A simple four-step workflow.")

s1, s2, s3, s4 = st.columns(4, gap="medium")
workflow = [
    ("1", "Select district",  "Choose any of the 39 districts of Istanbul."),
    ("2", "Pick categories",  "Buildings, health, education, green areas, transport …"),
    ("3", "Run extraction",   "Overpass API fetches and our pipeline cleans."),
    ("4", "Analyze & export", "Explore on maps, review KPIs, download outputs."),
]
for col, (n, t, txt) in zip([s1, s2, s3, s4], workflow):
    with col:
        st.markdown(
            f"""
            <div class="card">
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:0.75rem">
                    <div style="width:32px;height:32px;border-radius:8px;background:#0F2A44;
                                color:white;display:flex;align-items:center;justify-content:center;
                                font-weight:700;font-size:0.875rem">{n}</div>
                    <div class="card-title" style="margin:0">{t}</div>
                </div>
                <div class="card-text">{txt}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ════════════════════════════════════════════════════════════════════════════
# DATA CATEGORIES PREVIEW
# ════════════════════════════════════════════════════════════════════════════
cards.section_title(
    "Available data categories",
    "All categories come with high-quality OSM tag rules and quality scoring.",
)

cat_opts = [c for c in get_main_category_options_en() if c["key"] != "admin_boundaries"]
cols = st.columns(4, gap="small")
for i, cat in enumerate(cat_opts):
    n_subs = len(CATEGORY_REGISTRY[cat["key"]]["subcategories"])
    with cols[i % 4]:
        st.markdown(
            f"""
            <div class="card" style="padding:1rem 1.1rem">
                <div style="font-size:1.5rem;margin-bottom:0.25rem">{cat["icon"]}</div>
                <div style="font-size:0.9375rem;font-weight:600;color:#0F172A">
                    {cat["label"].replace(cat["icon"], "").strip()}
                </div>
                <div style="font-size:0.8125rem;color:#64748B;margin-top:2px">
                    {n_subs} sub-categories
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ════════════════════════════════════════════════════════════════════════════
# CALL-TO-ACTION
# ════════════════════════════════════════════════════════════════════════════
cards.divider()

cta1, cta2 = st.columns([2, 1], gap="large")
with cta1:
    st.markdown(
        """
        <div style="background:linear-gradient(135deg,#DBEAFE 0%,#EFF6FF 100%);
                    border:1px solid #BFDBFE;border-radius:14px;padding:2rem;
                    height:100%">
            <div style="color:#1E40AF;font-size:0.75rem;font-weight:600;
                        letter-spacing:0.08em;text-transform:uppercase">
                Get started
            </div>
            <div style="font-size:1.5rem;font-weight:700;color:#0F172A;
                        letter-spacing:-0.02em;margin:0.35rem 0 0.5rem 0">
                Extract your first dataset in under a minute.
            </div>
            <div style="color:#475569;font-size:0.9375rem;line-height:1.55;
                        max-width:560px">
                Head over to the Data Extraction page, pick a district and a few
                categories, and hit <em>Run Extraction</em>. Results land in the
                session and every other page updates automatically.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with cta2:
    # B2 düzeltmesi: terminal komutu (`streamlit run ...`) son kullanıcı
    # için yabancı bir geliştirici talimatı görünümündeydi. Yerine bir
    # "uygulama bağlantısı" görünümü — kullanıcı bir terminal açmaya
    # zorlanmadan ürün-içi referansı görür. Optimizer ayrı bir Streamlit
    # uygulaması olduğu için tıklanır bir route'u yok; bağlantı görünümlü
    # bir info-card en doğru çözüm.
    st.markdown(
        """
        <div style="background:linear-gradient(135deg,#D1FAE5 0%,#ECFDF5 100%);
                    border:1px solid #A7F3D0;border-radius:14px;padding:2rem;
                    height:100%;display:flex;flex-direction:column">
            <div style="display:flex;align-items:center;gap:0.5rem;
                        color:#047857;font-size:0.75rem;font-weight:700;
                        letter-spacing:0.08em;text-transform:uppercase">
                <span style="display:inline-flex;align-items:center;
                             background:#10B981;color:white;width:18px;height:18px;
                             border-radius:50%;justify-content:center;
                             font-size:0.65rem;letter-spacing:0">✓</span>
                Available
            </div>
            <div style="font-size:1.25rem;font-weight:700;color:#064E3B;
                        letter-spacing:-0.01em;margin:0.6rem 0 0.5rem 0">
                Earthquake assembly optimization
            </div>
            <div style="color:#065F46;font-size:0.875rem;line-height:1.55;
                        margin-bottom:1rem">
                Capacity-aware building-to-assembly-area assignment.
                Ships as a separate Streamlit application.
            </div>
            <div style="background:#0F172A;border-radius:8px;
                        padding:0.7rem 0.9rem;font-family:'SFMono-Regular',
                        Consolas,Menlo,monospace;font-size:0.8125rem;
                        line-height:1.7;margin-top:auto">
                <div style="color:#94A3B8;font-size:0.7rem;font-weight:600;
                            letter-spacing:0.05em;margin-bottom:0.4rem;
                            font-family:Inter,sans-serif;text-transform:uppercase">
                    How to launch
                </div>
                <div>
                    <span style="color:#FBBF24">run_optimizer.bat</span>
                    <span style="color:#64748B"> &nbsp;# Windows</span>
                </div>
                <div>
                    <span style="color:#FBBF24">./run_optimizer.sh</span>
                    <span style="color:#64748B"> &nbsp;# macOS / Linux</span>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ════════════════════════════════════════════════════════════════════════════
# FOOTER
# ════════════════════════════════════════════════════════════════════════════
cards.footer()
