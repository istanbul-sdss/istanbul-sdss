"""
pages/2_Map_Visualization.py — Interactive spatial exploration.

Renders a full-width Folium map with category-colored clusters, layer
toggles, light/dark themes, and a filtered results table below.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from components import cards
from components.map_builder import build_map, legend_data, render_legend
from components.state import get_boundary, get_district, get_nonempty_results, has_data, init_state
from components.styles import configure_page
from components.translations import to_english, translate_category_label

# ── Folium harita cache ────────────────────────────────────────────────────
# `folium.Map` pickle edilemediği için @st.cache_data çalışmaz. Süreç-içi
# bounded dict cache. Key: kullanıcının haritayı etkileyebilen TÜM seçenekleri
# kapsar. Boundary GeoDataFrame'i extraction sırasında üretildiği için
# id() üzerinden değişimi yakalarız (yeni extraction → yeni id → cache miss).
_MAP_CACHE: dict[tuple, object] = {}
_MAP_CACHE_MAX = 4


def _get_or_build_map(
    filtered: dict,
    district: str,
    boundary,
    theme_key: str,
    selected_cats: tuple,
    selected_mahs: tuple,
):
    # Cache key ÖNEMLİ NOTLARI:
    # • `filtered` her rerun'da yeniden inşa ediliyor (df slice'ları yeni
    #   objeler) → id(df) kullanırsak cache HEP miss. Bunun yerine kullanıcı
    #   girdilerini (selected_cats, selected_mahs, theme, district) anahtar
    #   yapıyoruz: aynı girdiler → aynı filtered içerik → aynı harita.
    # • `boundary` ile `nonempty` extraction sırasında üretiliyor; yeni
    #   extraction yeni objeler verir → id() değişir → cache invalidate.
    #   Boundary'nin id'si sentinel olarak yeterli (nonempty değişti mi?
    #   evet, çünkü ikisi de aynı pipeline result dict'inden geliyor).
    key = (
        district,
        theme_key,
        id(boundary) if boundary is not None else 0,
        selected_cats,
        selected_mahs,
    )
    cached = _MAP_CACHE.get(key)
    if cached is not None:
        return cached

    m = build_map(
        nonempty=filtered,
        district=district,
        boundary_gdf=boundary,
        theme=theme_key,
    )
    if len(_MAP_CACHE) >= _MAP_CACHE_MAX:
        _MAP_CACHE.pop(next(iter(_MAP_CACHE)))
    _MAP_CACHE[key] = m
    return m

# ════════════════════════════════════════════════════════════════════════════
# PAGE SETUP
# ════════════════════════════════════════════════════════════════════════════
configure_page(title="Map Visualization", icon="🗺️")
init_state()

cards.sidebar_brand()

cards.page_header(
    eyebrow="Workflow · Step 3 of 4",
    title="Map Visualization",
    subtitle="Interactively explore extracted data across the selected district.",
)

# ════════════════════════════════════════════════════════════════════════════
# GUARD: no data yet
# ════════════════════════════════════════════════════════════════════════════
if not has_data():
    cards.empty_state(
        title="No data to visualize",
        text="Run an extraction first on the Data Extraction page. "
             "Once results are ready, you can explore them here.",
        icon="🗺️",
    )
    cards.footer()
    st.stop()

nonempty = get_nonempty_results()
district = get_district() or "Istanbul"
boundary = get_boundary()

# ════════════════════════════════════════════════════════════════════════════
# SIDEBAR — map controls
# ════════════════════════════════════════════════════════════════════════════
st.sidebar.markdown("### Map controls")

theme = st.sidebar.radio(
    "Map theme",
    ["Light", "Dark"],
    index=0,
    horizontal=True,
)
theme_key = "dark" if theme == "Dark" else "light"

st.sidebar.markdown("---")
st.sidebar.markdown("### Category layers")
# Top-level category filter (one checkbox per top-level key present in data)
# DÜZELTME: Canonical `category_group` değerlerini kullan (palette ile uyumlu).
# Fallback olarak eski `kat.split("/")[0]` mantığı korunuyor.
all_cat_keys = sorted({
    (res.get("category_group")
     or (kat.split("_")[0] if "_" in kat else (kat.split("/")[0] if "/" in kat else kat)))
    for kat, res in nonempty.items()
})
selected_cats = []
for ck in all_cat_keys:
    if st.sidebar.checkbox(
        ck.replace("_", " ").title(),
        value=True,
        key=f"map_cat_{ck}",
    ):
        selected_cats.append(ck)

st.sidebar.markdown("---")

# All-neighborhoods list (from data)
all_df_tr = pd.concat([v["df"] for v in nonempty.values()], ignore_index=True)
all_df_en = to_english(all_df_tr)

mahalleler = sorted(all_df_en["Neighborhood"].dropna().unique().tolist()) \
    if "Neighborhood" in all_df_en.columns else []

st.sidebar.markdown("### Neighborhood filter")
selected_mahs = st.sidebar.multiselect(
    "Neighborhoods",
    mahalleler,
    default=[],
    placeholder="All neighborhoods",
    label_visibility="collapsed",
)

# ════════════════════════════════════════════════════════════════════════════
# APPLY FILTERS
# ════════════════════════════════════════════════════════════════════════════
filtered = {}
for kat, res in nonempty.items():
    cat_key = (
        res.get("category_group")
        or (kat.split("_")[0] if "_" in kat else (kat.split("/")[0] if "/" in kat else kat))
    )
    if cat_key not in selected_cats:
        continue
    df = res["df"]
    if selected_mahs:
        # `selected_mahs` İngilizce ("Neighborhood") üstünden geliyor; DF ise
        # Türkçe ("Mahalle") sütunu içeriyor. Filtre için Türkçe sütun adı
        # kullanılır — çeviri 1:1 (to_english yalnızca kolon adını değiştirir).
        neigh_col = (
            "Mahalle" if "Mahalle" in df.columns
            else ("Neighborhood" if "Neighborhood" in df.columns else None)
        )
        if neigh_col is not None:
            df = df[df[neigh_col].isin(selected_mahs)]
            if df.empty:
                continue
    filtered[kat] = {
        "df":             df,
        "gdf":            res.get("gdf"),
        "label_tr":       res.get("label_tr"),
        "category_group": res.get("category_group"),
        "rule_code":      res.get("rule_code"),
    }


# ════════════════════════════════════════════════════════════════════════════
# TOP METRICS
# ════════════════════════════════════════════════════════════════════════════
total_points = sum(len(v["df"]) for v in filtered.values())

cards.status_strip([
    {"label": "📍 District:",
     "value": district,
     "tone": "ok"},
    {"label": "🎨 Layers:",
     "value": f"{len(selected_cats)} / {len(all_cat_keys)}",
     "tone": None},
    {"label": "🏘 Neighborhoods:",
     "value": (f"{len(selected_mahs)} selected" if selected_mahs else "All"),
     "tone": None},
    {"label": "📊 Points:",
     "value": f"{total_points:,}",
     "tone": "ok"},
])


# ════════════════════════════════════════════════════════════════════════════
# MAP
# ════════════════════════════════════════════════════════════════════════════
if not filtered:
    cards.empty_state(
        title="No points match your filters",
        text="Try enabling more category layers or clearing the neighborhood filter.",
        icon="🔍",
    )
else:
    # Legend (above the map)
    cards.section_title(
        f"{district} — {total_points:,} points across {len(filtered)} categories"
    )
    legend = legend_data(filtered)
    render_legend(legend, cols_per_row=5)

    # Render map — process-local cache: aynı filtre/tema kombinasyonu için
    # Folium yeniden inşa edilmez. Streamlit her widget tıklamasında script'i
    # baştan çalıştırdığından (kullanıcı tablodaki arama kutusuna her harf
    # yazdığında bile) folium ağacı her seferinde sıfırdan oluşuyordu →
    # ~7000 marker'lık ilçelerde 2-5 saniye gecikme. Filtre durumu key'ine
    # göre cache hit'te haritayı O(1) döndürürüz.
    try:
        from streamlit_folium import st_folium
        m = _get_or_build_map(
            filtered=filtered,
            district=district,
            boundary=boundary,
            theme_key=theme_key,
            selected_cats=tuple(sorted(selected_cats)),
            selected_mahs=tuple(sorted(selected_mahs)),
        )
        st_folium(m, width="100%", height=620, returned_objects=[])
    except ImportError:
        st.error(
            "Folium and streamlit-folium are required. "
            "Install with: `pip install folium streamlit-folium`"
        )


# ════════════════════════════════════════════════════════════════════════════
# FILTERED RECORD TABLE
# ════════════════════════════════════════════════════════════════════════════
cards.divider()
cards.section_title(
    "Points in view",
    "All records matching the current filters, with coordinates."
)

if filtered:
    show_df = pd.concat(
        [to_english(v["df"]) for v in filtered.values()],
        ignore_index=True,
    )
    # Keep only display columns
    display_cols = [c for c in
                    ["Name", "Category", "Neighborhood", "Latitude", "Longitude", "Confidence"]
                    if c in show_df.columns]
    # Category column: translate values
    if "Category" in show_df.columns:
        show_df["Category"] = show_df["Category"].map(
            lambda v: translate_category_label(v) if pd.notna(v) else v
        )

    left, right = st.columns([3, 1], gap="medium")
    with left:
        query = st.text_input(
            "Search",
            placeholder="Search by name, neighborhood, category…",
            label_visibility="collapsed",
        )
        if query:
            # P2.1 düzeltmesi: regex=False — kullanıcı '[' gibi geçersiz regex
            # karakteri yazınca pandas re.error fırlatıp sayfayı kırıyordu.
            # Plain substring araması güvenli ve daha hızlı.
            patt = query.strip().lower()
            mask = show_df.apply(
                lambda c: c.astype(str).str.lower().str.contains(
                    patt, na=False, regex=False
                )
            ).any(axis=1)
            show_df = show_df[mask]
        st.dataframe(
            show_df[display_cols] if display_cols else show_df,
            width="stretch",
            height=360,
            hide_index=True,
        )
        st.caption(f"{len(show_df):,} records")

    with right:
        if "Category" in show_df.columns:
            st.markdown("**By category**")
            cat_counts = show_df["Category"].value_counts().reset_index()
            cat_counts.columns = ["Category", "Count"]
            st.dataframe(cat_counts, width="stretch", height=360, hide_index=True)


cards.footer()
