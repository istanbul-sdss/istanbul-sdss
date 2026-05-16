"""
Regresyon (P2.2): Folium popup ve legend render'ı kullanıcı/OSM verisini
HTML escape etmeli. Aksi halde OSM 'name' tag'inde HTML/JS varsa popup'a
enjekte olabilir (yerel araç için düşük risk; paylaşımlı deploy edilirse
kritik).
"""
from __future__ import annotations

import pandas as pd

from components.map_builder import _popup_html, _safe_hex_color


def test_popup_escapes_html_in_osm_name():
    row = pd.Series({
        "Ad":            "<script>alert(1)</script>",
        "Mahalle":       "Caferağa",
        "Kategori (TR)": "Cami",
    })
    out = _popup_html(row, color="#1B4F72", title="OSM POI")
    assert "<script>alert(1)</script>" not in out, (
        "REGRESYON: OSM 'name' ham olarak popup HTML'ine basılmış. "
        "html.escape ile kaçırılmalı."
    )
    # Kaçırılmış hali bulunmalı
    assert "&lt;script&gt;" in out


def test_popup_escapes_title():
    row = pd.Series({"Ad": "Cami"})
    out = _popup_html(row, color="#1B4F72", title='" onclick="alert(1)')
    # Ham title HTML'e enjekte edilmemiş olmalı
    assert 'onclick=' not in out or '&quot;' in out, (
        "REGRESYON: title HTML escape edilmedi → CSS/JS enjeksiyon riski."
    )


def test_safe_hex_color_accepts_valid_hex():
    assert _safe_hex_color("#1B4F72") == "#1B4F72"
    assert _safe_hex_color("#abc") == "#abc"
    assert _safe_hex_color("#AABBCC") == "#AABBCC"


def test_safe_hex_color_rejects_css_injection():
    """CSS injection denenirse default'a düşmeli."""
    bad = "red;background-image:url(javascript:alert(1))"
    out = _safe_hex_color(bad)
    assert out != bad, (
        "REGRESYON: _safe_hex_color CSS literal validation yapmıyor → "
        "popup arka planı keyfi CSS payload'u taşıyabilir."
    )
    assert out.startswith("#")


def test_safe_hex_color_rejects_non_string():
    """None / int gibi değerler güvenli default'a düşer."""
    assert _safe_hex_color(None).startswith("#")
    assert _safe_hex_color(123).startswith("#")


def test_marker_tooltip_escapes_osm_name():
    """
    REGRESYON: build_map içinde marker tooltip'i `Ad` (OSM name) değerini
    almakta. Folium tooltip'i string'i HTML olarak render ediyor; escape
    edilmezse popup escape'i yapılmış olsa bile XSS yüzeyi açık kalır.
    """
    import geopandas as gpd
    from shapely.geometry import Point

    from components.map_builder import build_map

    df = pd.DataFrame({
        "Ad":     ["<script>alert(1)</script>"],
        "Enlem":  [41.015],
        "Boylam": [28.979],
    })
    gdf = gpd.GeoDataFrame(df, geometry=[Point(28.979, 41.015)], crs="EPSG:4326")
    nonempty = {"health_hospital": {
        "df": df, "gdf": gdf,
        "label_tr": "Hastane", "category_group": "health",
    }}
    m = build_map(nonempty, district="Test", boundary_gdf=None)
    rendered = m.get_root().render()
    assert "<script>alert(1)</script>" not in rendered, (
        "REGRESYON: marker tooltip OSM name'i ham basıyor — XSS yüzeyi."
    )
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
