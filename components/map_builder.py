"""
components/map_builder.py — Folium map factory.

Builds interactive Leaflet maps with category-colored marker clusters,
popup details, district boundary, and light/dark themes. Reusable from
both the Map Visualization page and any embedded previews.
"""

from __future__ import annotations

import html
import re as _re

import pandas as pd
import streamlit as st

from components.translations import translate_category_label


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC ESCAPE HELPERS — folium popup/tooltip injection defense.
# ─────────────────────────────────────────────────────────────────────────────
# Tüm Folium popup/tooltip kodu (bu dosya, src/optimizer/map_renderer.py,
# Optimization_Tool.py) bu iki helper'ı kullanmalı. OSM `name`, kullanıcı
# yüklemesi ve serbest metin alanları doğrudan HTML/JS render edildiğinden
# tek noktadan kaçırma diçiplini güvenliğin temel garantisidir.
def safe_field(value) -> str:
    """OSM/kullanıcı kaynaklı string'i HTML-escape et. None/NaN → ''."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return html.escape(str(value))


def safe_hex_color(color: str, fallback: str = "#94A3B8") -> str:
    """CSS değerini hex literal'e zorla — style="" enjeksiyonunu engeller."""
    if isinstance(color, str) and _re.fullmatch(r"#[0-9A-Fa-f]{3,8}", color):
        return color
    return fallback


# ─────────────────────────────────────────────────────────────────────────────
# PALETTE — aligned with design-system tokens
# ─────────────────────────────────────────────────────────────────────────────
CATEGORY_COLORS: dict[str, str] = {
    "buildings":      "#3B82F6",
    "health":         "#EF4444",
    "education":      "#10B981",
    "green_area":     "#059669",
    "transport":      "#F59E0B",
    "commerce":       "#8B5CF6",
    "infrastructure": "#64748B",
    "culture":        "#EC4899",
}
DEFAULT_COLOR = "#94A3B8"

# Istanbul bounding box (sanity filter)
IST_LAT_MIN, IST_LAT_MAX = 40.5, 42.0
IST_LON_MIN, IST_LON_MAX = 28.0, 30.0


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _popup_html(row: pd.Series, color: str, title: str) -> str:
    """
    Folium popup HTML üretici.

    P2.2 düzeltmesi: OSM kaynaklı `name`, `Mahalle`, kategori vb. değerler
    artık html.escape ile kaçırılır. OSM dışsal/kontrol-edilmemiş veri
    kaynağıdır; ham basıldığında HTML/JS injection riski doğar (yerel araç
    için düşük risk; paylaşımlı deploy edilirse kritik).

    `color` ve `title` çağrı sahibi (kod sabitleri / kategori paleti) tarafından
    geliyor; kontrollü ama defansif olmak için `title`'ı da kaçırıyoruz.
    `color` hex literal olarak validate ediliyor (CSS'e enjeksiyon yok).
    """
    rows = []
    for tr_col, en_label in [
        ("Ad",            "Name"),
        ("Kategori (TR)", "Category"),
        ("Mahalle",       "Neighborhood"),
        ("Güven",         "Confidence"),
        ("Alan (m²)",     "Area (m²)"),
    ]:
        val = row.get(tr_col, "")
        if val is None or str(val).strip() == "" or str(val) == "nan":
            continue
        # translate confidence/category values
        if tr_col == "Güven":
            val = {"Yüksek": "High", "Orta": "Medium",
                   "Düşük": "Low", "Belirsiz": "Unknown"}.get(val, val)
        if tr_col == "Kategori (TR)":
            val = translate_category_label(str(val))
        # Kullanıcı/OSM verisi → merkezi safe_field zorunlu
        safe_val = safe_field(val)
        rows.append(
            f'<tr><td style="color:#64748B;padding:3px 10px 3px 0;font-size:12px">{en_label}</td>'
            f'<td style="font-weight:600;color:#0F172A;font-size:12px">{safe_val}</td></tr>'
        )

    safe_title = safe_field(title)
    safe_color = _safe_hex_color(color)
    return f"""
    <div style="font-family:Inter,sans-serif;min-width:200px">
      <div style="background:{safe_color};color:white;padding:8px 12px;
                  border-radius:6px 6px 0 0;font-weight:600;font-size:13px;
                  margin-bottom:8px">
        {safe_title}
      </div>
      <table style="border-collapse:collapse;width:100%">{''.join(rows)}</table>
    </div>
    """


def _safe_hex_color(color: str) -> str:
    """Geriye uyumluluk için ince sarmalayıcı; merkezi helper'a delege eder."""
    return safe_hex_color(color, fallback=DEFAULT_COLOR)


def _center_of(nonempty: dict) -> tuple[float, float] | None:
    lats, lons = [], []
    for res in nonempty.values():
        df = res["df"]
        if "Enlem" in df.columns and "Boylam" in df.columns:
            v = df[["Enlem", "Boylam"]].dropna()
            lats.extend(v["Enlem"].tolist())
            lons.extend(v["Boylam"].tolist())
    if not lats:
        return None
    return (sum(lats) / len(lats), sum(lons) / len(lons))


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC: build_map
# ─────────────────────────────────────────────────────────────────────────────
def build_map(
    nonempty: dict,
    district: str,
    boundary_gdf=None,
    theme: str = "light",
    category_filter: list[str] | None = None,
):
    """
    Return a folium.Map instance.

    Parameters
    ----------
    nonempty : dict
        {category_label: {"df": DataFrame, "gdf": GeoDataFrame, "label_tr": str}}
    district : str
        District name (for title/boundary labelling).
    boundary_gdf : GeoDataFrame | None
        District boundary polygon to overlay.
    theme : "light" | "dark"
    category_filter : list[str] | None
        Only include these top-level category keys (e.g. ["health", "education"]).
    """
    try:
        import folium
        from folium.plugins import MarkerCluster
    except ImportError as e:
        raise ImportError(
            "folium and streamlit-folium are required. "
            "Install with: pip install folium streamlit-folium"
        ) from e

    # Theme-dependent styling
    tile_url    = "CartoDB dark_matter" if theme == "dark" else "CartoDB positron"
    border_col  = "#FFFFFF" if theme == "dark" else "#0F172A"

    # Center
    center = _center_of(nonempty) or (41.015, 28.979)

    m = folium.Map(
        location=list(center),
        zoom_start=13,
        tiles=tile_url,
        control_scale=True,
    )

    # District boundary overlay
    if boundary_gdf is not None and not boundary_gdf.empty:
        try:
            b = boundary_gdf.to_crs("EPSG:4326")
            folium.GeoJson(
                b.__geo_interface__,
                name=f"{district} boundary",
                style_function=lambda _: {
                    "fillColor":   "transparent",
                    "color":       border_col,
                    "weight":      2.5,
                    "dashArray":   "6 4",
                    "fillOpacity": 0,
                },
                tooltip=f"{district} district boundary",
            ).add_to(m)
        except Exception:
            pass  # non-critical

    # Marker clusters per category
    for kat, res in nonempty.items():
        df = res["df"]
        if df.empty or "Enlem" not in df.columns or "Boylam" not in df.columns:
            continue

        # DÜZELTME: `kat` artık `rule_code` (ör. `health_hospital`) ya da
        # geriye uyumluluk için eski `label_tr`. Palette anahtarları canonical
        # `category_group` ("health", "buildings", ...) değerlerini bekliyor —
        # önce sözlükten al, yoksa rule_code'un ilk segmentine fallback yap.
        cat_key = (
            res.get("category_group")
            or (kat.split("_")[0] if "_" in kat else kat.split("/")[0])
        )
        # optional filter by top-level key
        if category_filter and cat_key not in category_filter:
            continue

        mdf = df.dropna(subset=["Enlem", "Boylam"])
        mdf = mdf[
            mdf["Enlem"].between(IST_LAT_MIN, IST_LAT_MAX) &
            mdf["Boylam"].between(IST_LON_MIN, IST_LON_MAX)
        ]
        if mdf.empty:
            continue

        color = CATEGORY_COLORS.get(cat_key, DEFAULT_COLOR)
        label = translate_category_label(res.get("label_tr") or kat)

        cluster = MarkerCluster(
            name=label,
            options={
                "maxClusterRadius": 50,
                "disableClusteringAtZoom": 16,
                "spiderfyOnMaxZoom": True,
            },
        )

        for _, row in mdf.iterrows():
            lat = row.get("Enlem")
            lon = row.get("Boylam")
            if lat is None or lon is None:
                continue

            popup = _popup_html(row, color, label)
            # P2.2: tooltip de OSM `name` (Ad) içerebilir; folium tooltip'i
            # string'i HTML olarak render eder → escape şart. Aksi halde
            # popup escape'i yapılmış olsa bile tooltip XSS yüzeyi açık kalır.
            tooltip_raw = row.get("Ad")
            tooltip_text = safe_field(tooltip_raw) or safe_field(label)
            folium.CircleMarker(
                location=[lat, lon],
                radius=7,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.85,
                weight=1.5,
                popup=folium.Popup(popup, max_width=280),
                tooltip=tooltip_text,
            ).add_to(cluster)

        cluster.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    return m


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC: legend_data
# ─────────────────────────────────────────────────────────────────────────────
def legend_data(nonempty: dict) -> list[dict]:
    """
    Build legend entries: [{"label": str, "color": str, "count": int}].
    """
    out = []
    for kat, res in nonempty.items():
        df = res["df"]
        if df.empty or "Enlem" not in df.columns or "Boylam" not in df.columns:
            continue
        mdf = df.dropna(subset=["Enlem", "Boylam"])
        mdf = mdf[
            mdf["Enlem"].between(IST_LAT_MIN, IST_LAT_MAX) &
            mdf["Boylam"].between(IST_LON_MIN, IST_LON_MAX)
        ]
        if mdf.empty:
            continue
        cat_key = (
            res.get("category_group")
            or (kat.split("_")[0] if "_" in kat else kat.split("/")[0])
        )
        out.append({
            "label": translate_category_label(res.get("label_tr") or kat),
            "color": CATEGORY_COLORS.get(cat_key, DEFAULT_COLOR),
            "count": len(mdf),
            "cat_key": cat_key,
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC: render_legend (Streamlit)
# ─────────────────────────────────────────────────────────────────────────────
def render_legend(items: list[dict], cols_per_row: int = 5) -> None:
    """
    Streamlit kategori legend renderer.

    P2.2: label kullanıcı/OSM kaynaklı olabilir → html.escape; color CSS'e
    enjeksiyonu engellemek için hex literal'e sınırlanır.
    """
    if not items:
        return
    cols = st.columns(min(len(items), cols_per_row))
    for i, it in enumerate(items):
        safe_color = _safe_hex_color(it.get("color", DEFAULT_COLOR))
        safe_label = safe_field(it.get("label", ""))
        count_int  = int(it.get("count", 0))
        cols[i % cols_per_row].markdown(
            f'<span style="display:inline-block;width:12px;height:12px;'
            f'background:{safe_color};border-radius:50%;'
            f'margin-right:8px;vertical-align:middle"></span>'
            f'<span style="font-weight:500;color:#0F172A">{safe_label}</span> '
            f'<span style="color:#94A3B8;font-size:0.8125rem">({count_int:,})</span>',
            unsafe_allow_html=True,
        )
