"""
Regresyon (P2.1): Optimizer haritası popup/tooltip/legend dış kaynaklı
string'leri html.escape ile kaçırmalı.

Audit bulgusu: src/optimizer/map_renderer.py içinde bina_etiketi, alan_adi,
atama_ozeti, mahalle, legend adları HTML'e ham basılıyordu. components/
map_builder.py'a uyguladığımız escape buraya taşımamış → ana harita ile
optimizer harita arasında güvenlik tutarsızlığı vardı.
"""
from __future__ import annotations

import pandas as pd

from src.optimizer.map_renderer import _esc, _safe_color


def test_esc_escapes_html():
    assert _esc("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_esc_handles_none_and_nan():
    assert _esc(None) == ""
    assert _esc(float("nan")) == ""
    import pandas as pd
    assert _esc(pd.NA) == ""


def test_esc_handles_normal_strings():
    assert _esc("Caferağa Mh.") == "Caferağa Mh."
    assert _esc("Park 'A'") == "Park &#x27;A&#x27;"


def test_safe_color_accepts_hex():
    assert _safe_color("#1B4F72") == "#1B4F72"
    assert _safe_color("#abc") == "#abc"


def test_safe_color_rejects_css_payload():
    bad = "red;background:url(javascript:alert(1))"
    assert _safe_color(bad) != bad
    assert _safe_color(bad).startswith("#")
    assert _safe_color(None).startswith("#")


def test_render_atama_haritasi_escapes_name_in_popup(monkeypatch):
    """End-to-end: rendered HTML'de OSM <script> ham olarak görünmemeli."""
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import Point

    from src.optimizer import map_renderer
    from src.optimizer.p_median import PMedianResult

    binalar = gpd.GeoDataFrame(
        {
            "weight":       [1.0],
            "mahalle":      ["<script>alert(1)</script>"],
            "bina_etiketi": ["<img onerror=alert(2)>"],
        },
        geometry=[Point(29.0, 41.0)],
        crs="EPSG:4326",
    )
    toplanma = gpd.GeoDataFrame(
        {"ad": ["<svg onload=alert(3)>"], "kapasite": [100]},
        geometry=[Point(29.001, 41.001)],
        crs="EPSG:4326",
    )
    sonuc = PMedianResult(
        atamalar=pd.DataFrame({
            "bina_idx": [0],
            "alan_idx": [0],
            "sure_dk":  [5.0],
            "agirlik":  [1.0],
            "alan_adi": ["<svg onload=alert(3)>"],
            "atama_ozeti": ["<b>x</b>"],
            "erisim_kalitesi": ["İyi"],
            "sure_araligi": ["0-5"],
            "mahalle": ["<script>alert(1)</script>"],
        }),
        acik_alanlar=[0],
        acik_alan_adlari=["<svg onload=alert(3)>"],
        toplam_agirlikli_sure=5.0,
        ort_sure_dk=5.0,
        agirlikli_ort_sure_dk=5.0,
        max_sure_dk=5.0,
        p95_sure_dk=5.0,
        kapsama_5dk_pct=100.0,
        kapsama_10dk_pct=100.0,
        kapsama_30dk_pct=100.0,
        nufus_kapsama_5dk_pct=100.0,
        nufus_kapsama_10dk_pct=100.0,
        nufus_kapsama_30dk_pct=100.0,
        ulasilamaz_sayisi=0,
        ulasilamaz_nufus=0.0,
        yontem="Heuristic",
        amac="min_sum",
    )

    fmap = map_renderer.render_atama_haritasi(sonuc, binalar, toplanma)
    rendered = fmap.get_root().render()

    # Hiçbiri ham geçmemeli
    assert "<script>alert(1)</script>" not in rendered
    assert "<img onerror=alert(2)>" not in rendered
    assert "<svg onload=alert(3)>" not in rendered
    # Escape edilmiş hâlleri olmalı
    assert "&lt;script&gt;" in rendered
