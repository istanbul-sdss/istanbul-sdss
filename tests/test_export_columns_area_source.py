"""
Regresyon: `area_source` kolonu export'a gitmeli. Aksi halde kullanıcı
Excel'de 500 m² gören bir default kaydı gerçek ölçümden ayırt edemez
(reviewer bulgu #2 ruhu: sessiz tahmin yok).
"""
from __future__ import annotations

from src.config.output_columns import (
    BUILDING_OUTPUT_COLUMNS,
    LANDUSE_OUTPUT_COLUMNS,
    POI_OUTPUT_COLUMNS,
    SPATIAL_COLUMNS,
    get_export_columns,
)


def test_area_source_in_spatial_columns():
    assert "area_source" in SPATIAL_COLUMNS, (
        "area_source SPATIAL_COLUMNS'a eklenmeli — aksi halde provenance "
        "Excel'e gitmez ve 500 m² default'u ölçümden ayırt edilemez."
    )


def test_area_source_flows_to_building_poi_landuse_exports():
    """
    footprint_m2'nin bulunduğu her family, area_source'u da taşımalı.
    """
    for family_name, cols in [
        ("building", BUILDING_OUTPUT_COLUMNS),
        ("poi",      POI_OUTPUT_COLUMNS),
        ("landuse",  LANDUSE_OUTPUT_COLUMNS),
    ]:
        assert "footprint_m2" in cols, f"{family_name} export'unda footprint_m2 yok"
        assert "area_source" in cols, (
            f"{family_name} export'unda area_source yok — footprint_m2 "
            f"eşliğinde provenance gitmeli"
        )


def test_assembly_point_family_uses_poi_columns():
    """
    assembly_point export_family='poi'; dolayısıyla area_source buradan
    Excel'e düşmeli — Kadıköy'deki 'tanzim' / 'Ahmet Taner Kışlalı Parkı'
    Point kayıtları için provenance kesinlikle görünür olacak.
    """
    cols = get_export_columns("poi")
    assert "area_source" in cols
    assert "footprint_m2" in cols
