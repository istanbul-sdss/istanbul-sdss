"""
Regresyon (P2.3): osm_service.fetch_union_features_within_boundary'nin
attrs ile işaretlediği partial_failure bilgisi pipeline result dict'ine
taşınmalı; aksi halde gdf.empty kontrolünde kaybolur ve kullanıcı eksik
veriyi "tamamlandı" diye görür.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, Polygon

from src.pipelines import pipeline as pl


def _fake_boundary():
    return gpd.GeoDataFrame(
        geometry=[Polygon([(29.0, 41.0), (29.1, 41.0), (29.1, 41.1), (29.0, 41.1)])],
        crs="EPSG:4326",
    )


def test_partial_failure_in_attrs_propagates_to_run_rule_result(monkeypatch):
    """
    Sahte fetch fonksiyonu boş GDF + partial_failure attrs ile dönsün.
    run_rule sonucunda bu bilgi yer almalı.
    """
    fake_gdf = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    fake_gdf.attrs["partial_failure"] = True
    fake_gdf.attrs["failed_tags"] = [{"amenity": "hospital"}]
    fake_gdf.attrs["network_failed_count"] = 1

    monkeypatch.setattr(
        pl, "fetch_rule_based_features_with_boundary",
        lambda boundary_gdf, rule_code: fake_gdf,
    )

    result = pl.run_rule(
        boundary_gdf=_fake_boundary(),
        rule_code="hospital",
        mahalleleri=None,
    )
    assert result.get("partial_failure") is True, (
        "REGRESYON: pipeline result `partial_failure` taşımıyor; "
        f"keys={list(result.keys())}. UI bu bilgiyi kullanıcıya gösteremez."
    )
    assert result.get("failed_tags"), "failed_tags listesi boş"
    assert result.get("network_failed_count") == 1


def test_no_partial_failure_no_flag(monkeypatch):
    """Tüm sorgular başarılıysa partial_failure ESET edilmemeli."""
    fake_gdf = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    monkeypatch.setattr(
        pl, "fetch_rule_based_features_with_boundary",
        lambda boundary_gdf, rule_code: fake_gdf,
    )
    result = pl.run_rule(
        boundary_gdf=_fake_boundary(),
        rule_code="hospital",
        mahalleleri=None,
    )
    assert "partial_failure" not in result or result["partial_failure"] is False


# ── P2.4: Pipeline-level failure semantics ──────────────────────────────────


def test_run_pipeline_marks_all_failed_when_every_category_errors(monkeypatch):
    """
    REGRESYON (P2.4): run_pipeline tüm kategorilerde RuntimeError alırsa
    `all_failed=True` ve `error_count=requested_count` taşımalı; UI
    `Completed - 0 records` yeşil kutusunu yanlışlıkla göstermesin.
    """
    monkeypatch.setattr(
        pl, "fetch_boundary",
        lambda *_a, **_kw: _fake_boundary(),
    )
    monkeypatch.setattr(
        pl, "load_mahalleleri",
        lambda *_a, **_kw: gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"),
    )

    def boom(boundary_gdf, rule_code):
        raise RuntimeError("Overpass outage")

    monkeypatch.setattr(pl, "fetch_rule_based_features_with_boundary", boom)

    pr = pl.run_pipeline(
        ilce="Kadıköy",
        secimler=[("health", "hospital"), ("health", "pharmacy")],
    )
    assert pr["all_failed"] is True, (
        f"REGRESYON: tüm kategoriler fail → all_failed=True olmalı; got {pr.get('all_failed')!r}"
    )
    assert pr["error_count"] == 2
    assert pr["success_count"] == 0
    assert pr["requested_count"] == 2
    assert pr["results"] == {}
    failed = pr["failed_categories"]
    assert len(failed) == 2
    assert all(fc["error_type"] == "RuntimeError" for fc in failed)
    assert all("Overpass outage" in fc["message"] for fc in failed)


def test_run_pipeline_partial_failure_keeps_successes_and_reports_errors(monkeypatch):
    """
    Bir kategori OK, biri RuntimeError → success_count=1, error_count=1,
    all_failed=False. results sözlüğünde sadece OK olan kategori bulunmalı.
    """
    monkeypatch.setattr(
        pl, "fetch_boundary", lambda *_a, **_kw: _fake_boundary()
    )
    monkeypatch.setattr(
        pl, "load_mahalleleri",
        lambda *_a, **_kw: gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"),
    )

    ok_gdf = gpd.GeoDataFrame(
        {"name": ["X"]},
        geometry=[Point(29.05, 41.05)],
        crs="EPSG:4326",
    )

    def selective(boundary_gdf, rule_code):
        if rule_code == "pharmacy":
            raise RuntimeError("connection refused")
        return ok_gdf

    monkeypatch.setattr(pl, "fetch_rule_based_features_with_boundary", selective)

    pr = pl.run_pipeline(
        ilce="Kadıköy",
        secimler=[("health", "hospital"), ("health", "pharmacy")],
    )
    assert pr["all_failed"] is False
    assert pr["success_count"] == 1
    assert pr["error_count"] == 1
    assert "pharmacy" in {fc["sub_key"] for fc in pr["failed_categories"]}
