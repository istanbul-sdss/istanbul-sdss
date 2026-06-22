"""
Regresyon: Kapasite ön-fizibilite kontrolü.

Audit bulgusu: Kullanıcı kapasite < talep durumunda saniyelerce ILP çalıştırıp
"Heuristic'e düştü, neden bilmiyorum" mesajıyla karşılaşıyordu. Çözüm: çözüm
başlamadan önce hızlı bir ön-tarama yap, fizibilite_uyarisi alanına yaz.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from src.optimizer.p_median import _check_capacity_feasibility, coz


def _make_test_data(n_bina=10, n_alan=3, weight=10.0, kapasite=5.0):
    """Basit test fixture'ı: binalar + alanlar + OD matrisi."""
    binalar = gpd.GeoDataFrame(
        {
            "weight": [weight] * n_bina,
            "mahalle": ["Test"] * n_bina,
            "alan_m2": [100.0] * n_bina,
            "levels": [3] * n_bina,
            "bina_etiketi": [f"B{i}" for i in range(n_bina)],
            "geometry": [Point(29.0 + i * 0.001, 41.0) for i in range(n_bina)],
        },
        crs="EPSG:4326",
    )
    alanlar = gpd.GeoDataFrame(
        {
            "ad": [f"Alan{j}" for j in range(n_alan)],
            "kapasite": [kapasite] * n_alan,
            "geometry": [Point(29.0 + j * 0.005, 41.001) for j in range(n_alan)],
        },
        crs="EPSG:4326",
    )
    od = np.full((n_bina, n_alan), 5.0, dtype=np.float32)  # her şey 5 dk
    return od, binalar, alanlar


def test_capacity_shortage_triggers_warning():
    """
    Toplam talep > seçilebilir p alanın toplam kapasitesi → uyarı dönmeli.
    Talep = 10 bina × 10 ağırlık = 100 kişi.
    p=2 ile en yüksek 2 alan kapasitesi = 5+5 = 10 kişi → açıkça yetersiz.
    """
    od, binalar, alanlar = _make_test_data(n_bina=10, weight=10.0, kapasite=5.0)
    msg = _check_capacity_feasibility(
        od, binalar, alanlar, p=2, kapasite=True, max_sure_dk=None,
        cb=lambda m: None,
    )
    assert msg is not None
    msg_low = msg.lower()
    # English warning: "Insufficient capacity..." (TR fallback retained for compat)
    assert (
        "insufficient" in msg_low or "capacity" in msg_low
        or "yetersiz" in msg_low or "kapasite" in msg_low
    )
    assert "100" in msg   # total demand


def test_capacity_sufficient_no_warning():
    """Kapasite yeterli olduğunda uyarı dönmemeli."""
    od, binalar, alanlar = _make_test_data(n_bina=10, weight=1.0, kapasite=100.0)
    msg = _check_capacity_feasibility(
        od, binalar, alanlar, p=2, kapasite=True, max_sure_dk=None,
        cb=lambda m: None,
    )
    assert msg is None


def test_unreachable_buildings_warning():
    """
    max_sure_dk altında bazı binalar ulaşılamaz → ulaşılamazlık uyarısı.
    """
    od, binalar, alanlar = _make_test_data(n_bina=10, weight=1.0, kapasite=100.0)
    od[0:3, :] = np.inf   # ilk 3 bina ulaşılamaz

    msg = _check_capacity_feasibility(
        od, binalar, alanlar, p=2, kapasite=True, max_sure_dk=10.0,
        cb=lambda m: None,
    )
    assert msg is not None
    msg_low = msg.lower()
    # English: "...cannot reach any area..." (TR fallback retained)
    assert (
        "reach" in msg_low or "3" in msg
        or "ulaş" in msg_low
    )


def test_capacity_off_no_warning():
    """Kapasite kısıtı kapalıysa hiç ön-tarama yapılmamalı."""
    od, binalar, alanlar = _make_test_data(n_bina=10, weight=10.0, kapasite=5.0)
    msg = _check_capacity_feasibility(
        od, binalar, alanlar, p=2, kapasite=False, max_sure_dk=None,
        cb=lambda m: None,
    )
    assert msg is None


def test_coz_propagates_feasibility_warning_to_result():
    """
    coz() ön-tarama uyarısını PMedianResult.fizibilite_uyarisi alanına
    yazmalı — UI bu metni gösterebilsin.
    """
    od, binalar, alanlar = _make_test_data(n_bina=10, weight=10.0, kapasite=5.0)
    result = coz(od, binalar, alanlar, p=2, kapasite=True, amac="min_sum")
    assert result.fizibilite_uyarisi is not None
    msg_low = result.fizibilite_uyarisi.lower()
    # Pre-screen warning text now in English ("insufficient capacity").
    # Keep TR tokens as fallback in case message is reverted.
    assert (
        "insufficient" in msg_low or "capacity" in msg_low
        or "yetersiz" in msg_low or "kapasite" in msg_low
    )


def test_coz_rejects_zero_buildings():
    """n_bina=0 ValueError vermeli, np.argmin patlamasından önce."""
    import pytest
    binalar = gpd.GeoDataFrame(
        {"weight": [], "mahalle": [], "alan_m2": [], "levels": [],
         "bina_etiketi": [], "geometry": []},
        geometry="geometry", crs="EPSG:4326",
    )
    alanlar = gpd.GeoDataFrame(
        {"ad": ["A"], "kapasite": [100.0], "geometry": [Point(29.0, 41.0)]},
        crs="EPSG:4326",
    )
    od = np.empty((0, 1), dtype=np.float32)
    with pytest.raises(ValueError, match="No buildings"):
        coz(od, binalar, alanlar, p=1)


def test_coz_rejects_zero_alanlar():
    import pytest
    od, binalar, _ = _make_test_data()
    alanlar = gpd.GeoDataFrame(
        {"ad": [], "kapasite": [], "geometry": []},
        geometry="geometry", crs="EPSG:4326",
    )
    od_empty = np.empty((10, 0), dtype=np.float32)
    with pytest.raises(ValueError, match="No assembly areas"):
        coz(od_empty, binalar, alanlar, p=1)


def test_coz_rejects_negative_p():
    import pytest
    od, binalar, alanlar = _make_test_data()
    with pytest.raises(ValueError, match="p="):
        coz(od, binalar, alanlar, p=0)
