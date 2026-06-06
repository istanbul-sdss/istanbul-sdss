"""
test_boundary_local_offline.py — fetch_boundary must build the district
boundary from the LOCAL neighbourhood GeoJSON (union of mahalle polygons)
WITHOUT calling Nominatim, for any district that has a local file.

Regression guard for the Streamlit Cloud hang: ox.geocode_to_gdf (Nominatim)
rate-limits shared server IPs, so the pipeline used to stall at the
"fetching boundary" step. The local-first path removes that dependency.
"""
from __future__ import annotations

import geopandas as gpd

from src.services.osm_service import fetch_boundary


def test_boundary_built_from_local_without_nominatim(monkeypatch):
    # If the local path works, ox.geocode_to_gdf must NOT be called.
    import osmnx as ox

    def _boom(*a, **k):  # pragma: no cover - should never run
        raise AssertionError("Nominatim (geocode_to_gdf) should not be called "
                             "when local mahalle data exists")

    monkeypatch.setattr(ox, "geocode_to_gdf", _boom)

    gdf = fetch_boundary("Beşiktaş, İstanbul, Türkiye")

    assert isinstance(gdf, gpd.GeoDataFrame)
    assert not gdf.empty
    assert len(gdf) == 1
    assert str(gdf.crs).upper().endswith("4326")
    geom = gdf.geometry.iloc[0]
    assert geom.geom_type in ("Polygon", "MultiPolygon")
    assert not geom.is_empty
    assert geom.area > 0


def test_boundary_falls_back_to_nominatim_when_no_local(monkeypatch):
    # A district with no local file must fall back to Nominatim.
    import src.services.osm_service as osm

    monkeypatch.setattr(osm, "_boundary_from_local_mahalleleri", lambda ilce: None)

    called = {"n": 0}
    sample = gpd.GeoDataFrame(
        {"name": ["Nowhere"]},
        geometry=gpd.GeoSeries.from_wkt(["POLYGON((0 0,0 1,1 1,1 0,0 0))"]),
        crs="EPSG:4326",
    )

    def _fake_geocode(place_name):
        called["n"] += 1
        return sample

    monkeypatch.setattr(osm.ox, "geocode_to_gdf", _fake_geocode)

    gdf = fetch_boundary("Nowhereville, İstanbul, Türkiye")
    assert called["n"] == 1
    assert not gdf.empty
