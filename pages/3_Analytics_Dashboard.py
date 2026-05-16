"""
pages/3_Analytics_Dashboard.py — KPI overview, distributions, and insights.

A decision-support-style dashboard with:
  • KPI row
  • Category distribution chart
  • Top neighborhoods chart
  • Confidence breakdown donut
  • Data quality table (completeness %)
  • Neighborhood × category heatmap
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from components import cards
from components.state import get_district, get_nonempty_results, has_data, init_state
from components.styles import TOKENS, configure_page
from components.translations import to_english, translate_category_label

# ════════════════════════════════════════════════════════════════════════════
# PAGE SETUP
# ════════════════════════════════════════════════════════════════════════════
configure_page(title="Analytics Dashboard", icon="📈")
init_state()

cards.sidebar_brand()

cards.page_header(
    eyebrow="Workflow · Step 4 of 4",
    title="Analytics Dashboard",
    subtitle="Aggregate insights and data-quality metrics at a glance.",
)


# ════════════════════════════════════════════════════════════════════════════
# GUARD
# ════════════════════════════════════════════════════════════════════════════
if not has_data():
    cards.empty_state(
        title="Nothing to analyze yet",
        text="Run an extraction on the Data Extraction page. "
             "Charts and KPIs will populate automatically.",
        icon="📈",
    )
    cards.footer()
    st.stop()

# Plotly (lazy import so the page loads even if not installed)
try:
    import plotly.express as px
    import plotly.graph_objects as go
    _PLOTLY = True
except ImportError:
    _PLOTLY = False


# ════════════════════════════════════════════════════════════════════════════
# DATA
# ════════════════════════════════════════════════════════════════════════════
nonempty = get_nonempty_results()
district = get_district() or "Istanbul"

# Translate all frames once
frames_en = {
    kat: to_english(res["df"])
    for kat, res in nonempty.items()
}
# ensure category label exists on each frame
for kat, df_en in frames_en.items():
    res_label = translate_category_label(
        nonempty[kat].get("label_tr") or kat
    )
    if "Category" not in df_en.columns or df_en["Category"].isna().all():
        df_en["Category"] = res_label
    else:
        # translate any remaining Turkish values (safety net)
        df_en["Category"] = df_en["Category"].map(
            lambda v: translate_category_label(v) if pd.notna(v) else v
        )

all_df_en = pd.concat(frames_en.values(), ignore_index=True)

# ════════════════════════════════════════════════════════════════════════════
# CONTEXT STRIP
# ════════════════════════════════════════════════════════════════════════════
cards.status_strip([
    {"label": "District:",      "value": district,                      "tone": "ok"},
    {"label": "Total records:", "value": f"{len(all_df_en):,}",         "tone": "ok"},
    {"label": "Categories:",    "value": str(len(nonempty)),            "tone": "ok"},
    {"label": "Neighborhoods:", "value": str(all_df_en["Neighborhood"].nunique())
        if "Neighborhood" in all_df_en.columns else "—", "tone": None},
])


# ════════════════════════════════════════════════════════════════════════════
# KPI ROW
# ════════════════════════════════════════════════════════════════════════════
cards.section_title("Key indicators")

k1, k2, k3, k4, k5 = st.columns(5, gap="small")
with k1:
    cards.kpi_card("Total records", len(all_df_en))
with k2:
    cards.kpi_card("Categories", len(nonempty))
with k3:
    cards.kpi_card(
        "Neighborhoods",
        all_df_en["Neighborhood"].nunique() if "Neighborhood" in all_df_en.columns else 0,
    )
with k4:
    coord_pct = (
        all_df_en["Latitude"].notna().mean() * 100
        if "Latitude" in all_df_en.columns else 0
    )
    cards.kpi_card("Coord. coverage", f"{coord_pct:.1f}%")
with k5:
    hi_pct = (
        (all_df_en["Confidence"] == "High").mean() * 100
        if "Confidence" in all_df_en.columns else 0
    )
    cards.kpi_card("High confidence", f"{hi_pct:.1f}%")


# ════════════════════════════════════════════════════════════════════════════
# CHART HELPERS
# ════════════════════════════════════════════════════════════════════════════
def _plotly_theme(fig):
    """Apply consistent corporate styling."""
    fig.update_layout(
        font=dict(family="Inter, sans-serif", color=TOKENS["text"], size=12),
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin=dict(l=20, r=20, t=40, b=20),
        title_font=dict(size=15, color=TOKENS["text"]),
        xaxis=dict(gridcolor=TOKENS["border_soft"], linecolor=TOKENS["border"]),
        yaxis=dict(gridcolor=TOKENS["border_soft"], linecolor=TOKENS["border"]),
        legend=dict(bgcolor="rgba(255,255,255,0)"),
    )
    return fig


# ════════════════════════════════════════════════════════════════════════════
# CHARTS ROW 1 — Category distribution + Confidence donut
# ════════════════════════════════════════════════════════════════════════════
cards.section_title("Distribution")

if _PLOTLY:
    c1, c2 = st.columns([2, 1], gap="medium")

    with c1:
        # Category distribution bar
        cat_counts = (
            all_df_en.groupby("Category").size()
            .reset_index(name="Count")
            .sort_values("Count", ascending=True)
        )
        fig = px.bar(
            cat_counts,
            x="Count",
            y="Category",
            orientation="h",
            title="Records by category",
            color="Count",
            color_continuous_scale=["#DBEAFE", "#2563EB", "#1E40AF"],
        )
        fig.update_layout(
            showlegend=False,
            coloraxis_showscale=False,
            height=420,
        )
        fig.update_traces(
            hovertemplate="<b>%{y}</b><br>%{x:,} records<extra></extra>",
        )
        _plotly_theme(fig)
        st.plotly_chart(fig, width="stretch")

    with c2:
        if "Confidence" in all_df_en.columns:
            conf = (
                all_df_en["Confidence"]
                .fillna("Unknown")
                .value_counts()
                .reset_index()
            )
            conf.columns = ["Confidence", "Count"]
            color_map = {
                "High": TOKENS["success"],
                "Medium": TOKENS["warning"],
                "Low": TOKENS["danger"],
                "Unknown": TOKENS["text_subtle"],
            }
            fig = px.pie(
                conf, names="Confidence", values="Count",
                hole=0.6,
                title="Confidence breakdown",
                color="Confidence",
                color_discrete_map=color_map,
            )
            fig.update_layout(height=420, legend=dict(orientation="h", y=-0.1))
            fig.update_traces(textposition="outside", textinfo="percent+label")
            _plotly_theme(fig)
            st.plotly_chart(fig, width="stretch")
        else:
            cards.empty_state(
                "Confidence data unavailable",
                "The current dataset has no confidence column.",
                icon="📊",
            )

else:
    st.warning("Plotly not installed — charts disabled. Install with: `pip install plotly`")


# ════════════════════════════════════════════════════════════════════════════
# CHARTS ROW 2 — Top neighborhoods + heatmap
# ════════════════════════════════════════════════════════════════════════════
cards.section_title("Neighborhood analysis")

if _PLOTLY and "Neighborhood" in all_df_en.columns:
    r1, r2 = st.columns([1, 1], gap="medium")

    # Top-N bar
    with r1:
        top_n = 15
        top_mah = (
            all_df_en.groupby("Neighborhood").size()
            .reset_index(name="Count")
            .sort_values("Count", ascending=True)
            .tail(top_n)
        )
        fig = px.bar(
            top_mah,
            x="Count", y="Neighborhood",
            orientation="h",
            title=f"Top {top_n} neighborhoods by record count",
            color="Count",
            color_continuous_scale=["#DBEAFE", "#2563EB", "#1E40AF"],
        )
        fig.update_layout(showlegend=False, coloraxis_showscale=False, height=460)
        fig.update_traces(hovertemplate="<b>%{y}</b><br>%{x:,} records<extra></extra>")
        _plotly_theme(fig)
        st.plotly_chart(fig, width="stretch")

    # Heatmap: neighborhood × category
    with r2:
        # B1 düzeltmesi: Heatmap tek kategori için anlamsız (tek dikey
        # şerit; gradient gerçek bir desen göstermez). En az 2 kategori
        # bekleniyor; aksi halde info kartı göster.
        n_categories = (
            all_df_en["Category"].nunique()
            if "Category" in all_df_en.columns else 0
        )
        if n_categories < 2:
            st.markdown(
                '<div style="background:#F1F5F9;border:1px solid #E2E8F0;'
                'border-radius:10px;padding:20px;min-height:440px;'
                'display:flex;flex-direction:column;align-items:center;'
                'justify-content:center;text-align:center">'
                '<div style="font-size:2rem;margin-bottom:8px">📊</div>'
                '<div style="font-weight:600;color:#0F172A;font-size:0.95rem;'
                'margin-bottom:4px">Neighborhood × Category heatmap</div>'
                '<div style="color:#64748B;font-size:0.825rem;max-width:340px">'
                'A heatmap needs at least <b>2 categories</b> — the gradient '
                'is only meaningful across different category densities. '
                'Go back to Data Extraction, select one more category and '
                're-run.</div>'
                '</div>',
                unsafe_allow_html=True,
            )
        else:
            pivot = (
                all_df_en.groupby(["Neighborhood", "Category"]).size()
                .unstack(fill_value=0)
            )
            # keep top 15 neighborhoods by total
            pivot["__total"] = pivot.sum(axis=1)
            pivot = pivot.sort_values("__total", ascending=False).head(15)
            pivot = pivot.drop(columns="__total")

            fig = go.Figure(data=go.Heatmap(
                z=pivot.values,
                x=list(pivot.columns),
                y=list(pivot.index),
                colorscale=[[0, "#F8FAFC"], [0.5, "#60A5FA"], [1, "#1E3A8A"]],
                hoverongaps=False,
                hovertemplate="<b>%{y}</b><br>%{x}: %{z:,}<extra></extra>",
            ))
            fig.update_layout(
                title="Neighborhood × Category density",
                height=460,
                xaxis=dict(tickangle=-30),
            )
            _plotly_theme(fig)
            st.plotly_chart(fig, width="stretch")


# ════════════════════════════════════════════════════════════════════════════
# DATA QUALITY TABLE
# ════════════════════════════════════════════════════════════════════════════
cards.section_title("Data quality", "Completeness per category across key fields.")

rows = []
for kat, df_en in frames_en.items():
    n = len(df_en)
    if n == 0:
        continue

    # B023: loop değişkeni df_en'i default-arg ile bağla (best practice).
    def pct(col, _df=df_en):
        return round(_df[col].notna().mean() * 100, 1) if col in _df.columns else 0.0

    mah_pct   = pct("Neighborhood")
    coord_pct = pct("Latitude")
    area_pct  = pct("Area (m²)")
    conf_high = round(
        (df_en["Confidence"] == "High").mean() * 100, 1
    ) if "Confidence" in df_en.columns else 0.0

    # A3 düzeltmesi: Overall %, kategori için anlamlı olan metriklerin
    # ortalamasıdır. Point-only kategoriler (Pharmacy, Bus Stop vb.) için
    # `Area (m²)` doğal olarak 0% — ham ortalamaya katılırsa Overall
    # yanıltıcı düşük çıkar. "Bu kategori için Area uygulanır mı?" testi:
    # Bina yapısal kategorilerinde area beklenir (>%5 dolu satır olur);
    # POI/Point kategorilerinde area_pct ≈ 0 → ortalamadan dışla.
    AREA_THRESHOLD = 5.0   # %5 altı dolu = bu kategori için area uygulanmaz
    if area_pct >= AREA_THRESHOLD:
        # Area metriği geçerli — 3 metriği ortala
        overall = round((mah_pct + coord_pct + area_pct) / 3, 1)
        area_display = area_pct
    else:
        # Area uygulanmaz (point geometry) — Overall sadece 2 geçerli metrik
        overall = round((mah_pct + coord_pct) / 2, 1)
        # Tablo görünürlüğü için: 0 yerine "N/A" diye işaretle (formatter
        # bu özel değeri renklendirme dışı tutsun). Şu an numeric tablo
        # kullanıyoruz; NaN olarak göster (boş hücre, kırmızı değil).
        area_display = float("nan")

    rows.append({
        "Category":          translate_category_label(nonempty[kat].get("label_tr") or kat),
        "Records":           n,
        "Neighborhood %":    mah_pct,
        "Coordinates %":     coord_pct,
        "Area %":            area_display,
        "High confidence %": conf_high,
        "Overall %":         overall,
    })

quality_df = pd.DataFrame(rows).sort_values("Records", ascending=False)

# Styled dataframe (coloring by percentage)
def _color_pct(val):
    if not isinstance(val, (int, float)):
        return ""
    # A3 düzeltmesi: Area% NaN ise (kategori için uygulanmaz) boş hücre,
    # renklendirme yok — "uygulanmaz" durumunda kırmızı yanıltıcıydı.
    if isinstance(val, float) and val != val:   # NaN check
        return "color:#94A3B8;font-style:italic"
    if val >= 80:
        return "background-color:#D1FAE5; color:#065F46"
    if val >= 50:
        return "background-color:#FEF3C7; color:#92400E"
    return "background-color:#FEE2E2; color:#991B1B"

# Styler.map replaces the deprecated/removed Styler.applymap (pandas ≥ 2.1)
_pct_cols = ["Neighborhood %", "Coordinates %", "Area %", "High confidence %", "Overall %"]
_style_map = getattr(quality_df.style, "map", None) or quality_df.style.applymap
# A3: Area % için NaN → "N/A" gösterimi ("uygulanmaz" semantiği)
def _fmt_pct_or_na(v) -> str:
    if isinstance(v, float) and v != v:    # NaN
        return "N/A"
    return f"{v:.1f}%"

styled = _style_map(_color_pct, subset=_pct_cols).format({
    "Records":            "{:,}",
    "Neighborhood %":     "{:.1f}%",
    "Coordinates %":      "{:.1f}%",
    "Area %":             _fmt_pct_or_na,
    "High confidence %":  "{:.1f}%",
    "Overall %":          "{:.1f}%",
})

st.dataframe(styled, width="stretch", hide_index=True, height=min(60 + 35 * len(quality_df), 420))


# ════════════════════════════════════════════════════════════════════════════
# INSIGHTS STRIP (auto-generated bullets)
# ════════════════════════════════════════════════════════════════════════════
cards.section_title("Automated insights")

insights = []

# Highest-volume category
top_cat = all_df_en.groupby("Category").size().idxmax()
top_cat_n = int(all_df_en.groupby("Category").size().max())
insights.append(
    f"🏆 Highest volume: **{top_cat}** with **{top_cat_n:,}** records "
    f"({top_cat_n/len(all_df_en)*100:.1f}% of total)."
)

# Densest neighborhood
if "Neighborhood" in all_df_en.columns and all_df_en["Neighborhood"].notna().any():
    top_mah = all_df_en["Neighborhood"].value_counts()
    insights.append(
        f"📍 Most data-rich neighborhood: **{top_mah.index[0]}** "
        f"with **{int(top_mah.iloc[0]):,}** records across categories."
    )

# Coordinate coverage
if "Latitude" in all_df_en.columns:
    c_pct = all_df_en["Latitude"].notna().mean() * 100
    tone = "🟢" if c_pct >= 90 else "🟡" if c_pct >= 70 else "🔴"
    insights.append(
        f"{tone} Coordinate coverage: **{c_pct:.1f}%** of records are geo-located."
    )

# Confidence
if "Confidence" in all_df_en.columns:
    hp = (all_df_en["Confidence"] == "High").mean() * 100
    tone = "🟢" if hp >= 70 else "🟡" if hp >= 40 else "🔴"
    insights.append(
        f"{tone} Quality: **{hp:.1f}%** of records are high-confidence."
    )

for line in insights:
    st.markdown(
        f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-left:3px solid #2563EB;'
        f'border-radius:8px;padding:12px 16px;margin-bottom:8px;font-size:0.9375rem">'
        f'{line}</div>',
        unsafe_allow_html=True,
    )


cards.footer()
