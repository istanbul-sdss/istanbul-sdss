"""
Regresyon (P2.2): OSM Overpass network hatası "veri yok" sonucundan ayrılmalı.

Audit bulgusu: fetch_union_features_within_boundary her tag için
`except Exception: log.warning` yapıp boş GDF döndürüyordu. DNS/SSL/timeout/
tüm-mirror-down durumlarında kullanıcı "bu ilçede veri yok" görüyor — gerçekte
veri kaynağı erişilemiyor. Karar destek raporlarına eksik veri sessizce sızar.

Çözüm: OverpassNetworkError exception sınıfı; tüm tag'ler bu hatayla düşerse
fetch fonksiyonu raise eder. Kısmi hatalar `gdf.attrs` ile işaretlenir.
"""
from __future__ import annotations

import geopandas as gpd
import pytest

from src.services.osm_service import (
    OverpassNetworkError,
    fetch_union_features_within_boundary,
)


def test_overpass_network_error_class_exists():
    """Network hatası özel exception ile temsil edilmeli."""
    assert issubclass(OverpassNetworkError, Exception)


def test_all_network_failures_raise_not_silently_empty(monkeypatch):
    """
    Tüm tag sorguları network hatası ile düşerse fonksiyon RAISE etmeli —
    sessiz boş GDF döndürmemeli (kullanıcı outage'i 'veri yok' sanmamalı).
    """
    from src.services import osm_service as svc

    def _explode(*args, **kwargs):
        raise OverpassNetworkError("simulated DNS/SSL/timeout outage")

    monkeypatch.setattr(svc, "fetch_features_from_polygon", _explode)

    boundary = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy([29.0], [41.0]).buffer(0.01),
        crs="EPSG:4326",
    )
    with pytest.raises(OverpassNetworkError):
        fetch_union_features_within_boundary(
            boundary,
            query_tags_list=[{"amenity": "hospital"}, {"building": "hospital"}],
        )


def test_partial_network_failure_marks_attrs(monkeypatch):
    """
    Bazı tag'ler network hatası, bazıları başarılı (boş veya dolu) → fetch
    devam eder ama gdf.attrs ile partial_failure işaretlenir.
    """
    from src.services import osm_service as svc

    call_count = {"n": 0}
    def _mixed(*args, **kwargs):
        call_count["n"] += 1
        # İlk çağrı network hatası, diğerleri normal boş döner
        if call_count["n"] == 1:
            raise OverpassNetworkError("transient timeout on first tag")
        return svc.EMPTY_GDF.copy()

    monkeypatch.setattr(svc, "fetch_features_from_polygon", _mixed)

    boundary = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy([29.0], [41.0]).buffer(0.01),
        crs="EPSG:4326",
    )
    out = fetch_union_features_within_boundary(
        boundary,
        query_tags_list=[{"amenity": "hospital"}, {"building": "hospital"}],
    )
    assert isinstance(out, gpd.GeoDataFrame)
    # Veri 0 olabilir (ikincisi boş döndü) ama partial_failure flag set olmalı
    assert out.attrs.get("partial_failure") is True, (
        f"REGRESYON: 1/2 tag network hatası — partial_failure işareti yok. "
        f"attrs={out.attrs}"
    )
    assert out.attrs.get("failed_tags"), "failed_tags listesi boş"


def test_no_failures_no_partial_flag(monkeypatch):
    """Her şey yolundaysa partial_failure flag'i False/eksik kalmalı."""
    from src.services import osm_service as svc

    monkeypatch.setattr(
        svc, "fetch_features_from_polygon",
        lambda *a, **k: svc.EMPTY_GDF.copy(),
    )
    boundary = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy([29.0], [41.0]).buffer(0.01),
        crs="EPSG:4326",
    )
    out = fetch_union_features_within_boundary(
        boundary, query_tags_list=[{"amenity": "school"}],
    )
    assert not out.attrs.get("partial_failure"), (
        f"Tüm sorgular başarılı ama partial_failure True işaretlenmiş: {out.attrs}"
    )


def test_empty_query_tags_returns_empty_no_raise(monkeypatch):
    """query_tags_list boş ise hata değil, boş GDF dönmeli (geriye uyum)."""
    boundary = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy([29.0], [41.0]).buffer(0.01),
        crs="EPSG:4326",
    )
    out = fetch_union_features_within_boundary(boundary, query_tags_list=[])
    assert isinstance(out, gpd.GeoDataFrame)
    assert out.empty
