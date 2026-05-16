"""
Regresyon (P1.1): run_pipeline() sonuç dict'inde çalıştırıldığı ilçenin
adını taşımalı.

Audit bulgusu: components/state.get_district() önce
`pipeline_result["ilce"]` ariyor, yoksa session'daki seçili ilçeye düşüyor.
Pipeline `ilce` döndürmediği için, kullanıcı veriyi çektikten sonra sidebar'dan
başka ilçe seçip sayfa değiştirirse Map/Analytics sayfaları ESKİ veriyi YENİ
ilçe etiketiyle gösteriyordu. Karar destek bağlamında yanıltıcı.
"""
from __future__ import annotations

import inspect

from src.pipelines import pipeline as pl


def test_run_pipeline_signature_documents_ilce():
    """run_pipeline `ilce` parametresi alıyor (sanity check)."""
    sig = inspect.signature(pl.run_pipeline)
    assert "ilce" in sig.parameters


def test_pipeline_result_carries_ilce_field(monkeypatch):
    """
    Pipeline'ı sahte boundary/mahalle ile koşturup return dict'inde
    `ilce` anahtarının olduğunu doğrula. Real fetch yapılmaz.
    """
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import Polygon

    fake_boundary = gpd.GeoDataFrame(
        geometry=[Polygon([(29.0, 41.0), (29.1, 41.0), (29.1, 41.1), (29.0, 41.1)])],
        crs="EPSG:4326",
    )
    fake_mah = gpd.GeoDataFrame(
        {"neighbourhood_name": ["Merkez"]},
        geometry=[Polygon([(29.0, 41.0), (29.1, 41.0), (29.1, 41.1), (29.0, 41.1)])],
        crs="EPSG:4326",
    )

    monkeypatch.setattr(pl, "fetch_boundary", lambda place: fake_boundary)
    monkeypatch.setattr(pl, "load_mahalleleri", lambda *a, **kw: fake_mah)
    # Boş seçim listesi → run_rule çağrılmaz; sadece ilçe bayrağını test ediyoruz.
    result = pl.run_pipeline(ilce="Beykoz", secimler=[])

    assert "ilce" in result, (
        "REGRESYON: pipeline result `ilce` alanı taşımıyor. "
        "components.state.get_district() bu yüzden stale session değerine "
        "düşüyor; karar destek raporları yanlış ilçe etiketiyle çıkıyor."
    )
    assert result["ilce"] == "Beykoz"


def test_state_get_district_prefers_pipeline_ilce(monkeypatch):
    """
    components.state.get_district() pipeline_result["ilce"]'yi session'a
    tercih etmeli — kullanıcı sidebar'dan başka ilçe seçince stale veri
    yeni etiket altında gösterilmesin.
    """
    import sys
    # st.session_state simülasyonu (Streamlit yüklü değilse atla)
    try:
        import streamlit as st
    except ImportError:
        import pytest
        pytest.skip("streamlit not installed in test env")

    from components import state as state_module

    pipeline_result = {"ilce": "Kadıköy", "results": {}}
    monkeypatch.setitem(st.session_state, state_module.KEY_PIPELINE_RESULT, pipeline_result)
    monkeypatch.setitem(st.session_state, state_module.KEY_SELECTED_DISTRICT, "Beykoz")

    assert state_module.get_district() == "Kadıköy", (
        "REGRESYON: get_district() pipeline_result['ilce'] yerine session'daki "
        "(yeni seçilen) Beykoz'u döndürdü. Kullanıcı stale Kadıköy verisini "
        "Beykoz etiketiyle görür."
    )
