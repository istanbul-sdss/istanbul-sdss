"""
src/optimizer/templates.py

Generates the downloadable blank templates that let a user prepare their own
input files. Two templates:

  1. Buildings + Assembly Excel workbook (3 sheets: Buildings + Assembly + README)
  2. TÜİK neighbourhood-population Excel workbook (TUIK_Population + README)

All templates pass through `build_styled_workbook`: brand-coloured header row,
autofilter, freeze pane and automatic column widths — so the file opens with a
clean, professional, pivot-like table view.

Column headers are English and match the (bilingual) loader in
`src/optimizer/data_loader.py`, so a filled-in template can be uploaded back to
the tool and parsed without any renaming.
"""
from __future__ import annotations

import pandas as pd

from src.services.excel_utils import build_styled_workbook

# ── Template example rows (one example row = proof of the expected format) ────
_BUILDING_TEMPLATE_ROW = {
    "Latitude":      40.9923,
    "Longitude":     29.0249,
    "Neighbourhood": "Caferağa",
    "Name":          "(optional) building / structure name",
    "Area (m²)":     220.0,
    "Floors":        5,
    "OSM ID":        "(optional) stable id for re-uploads",
}

_ASSEMBLY_TEMPLATE_ROW = {
    "Latitude":      40.9856,
    "Longitude":     29.0285,
    "Name":          "Caferağa Park",
    "Area (m²)":     4500.0,
    "Neighbourhood": "(optional) neighbourhood it belongs to",
}

_TUIK_TEMPLATE_ROWS = [
    {"neighbourhood_name": "Caferağa",          "population": 21350},
    {"neighbourhood_name": "Fenerbahçe",        "population":  9800},
    {"neighbourhood_name": "Göztepe Mahallesi", "population": 36000},
    {"neighbourhood_name": "Acıbadem",          "population": 28600},
    {"neighbourhood_name": "19 Mayıs",          "population": 31864},
]

_DATA_GUIDE_ROWS = [
    {"Field": "Latitude / Longitude",
     "Required": "Yes",
     "Notes": "WGS84 (EPSG:4326) decimal degrees. Must lie within Istanbul."},
    {"Field": "Neighbourhood",
     "Required": "Buildings: yes (critical for Uniform mode); Assembly: optional",
     "Notes": "Used to match the TÜİK neighbourhood population table."},
    {"Field": "Area (m²)",
     "Required": "Recommended",
     "Notes": "Buildings: needed for the footprint-based population estimate. "
              "Assembly: needed for capacity (AFAD 1.5 m²/person)."},
    {"Field": "Floors",
     "Required": "Recommended (Buildings only)",
     "Notes": "If left blank, a default of 4 floors is assumed."},
    {"Field": "Name",
     "Required": "Optional (Buildings) / Recommended (Assembly)",
     "Notes": "Used as a label in the reports."},
    {"Field": "OSM ID",
     "Required": "Optional",
     "Notes": "Stable identity when re-uploading the same data."},
]

_TUIK_GUIDE_ROWS = [
    {"Field": "neighbourhood_name",
     "Required": "Yes",
     "Notes": "Official TÜİK neighbourhood name. 'Mahallesi' / 'Mh.' suffixes "
              "are tolerated automatically; typographic differences (Zühtüpaşa "
              "vs Zühütpaşa) are caught by fuzzy matching (threshold 85)."},
    {"Field": "population",
     "Required": "Yes",
     "Notes": "Positive integer. Zero or empty rows are not used in the "
              "distribution; buildings of that neighbourhood receive weight=NaN."},
]


def build_data_template_xlsx() -> bytes:
    """
    Buildings + assembly Excel template (.xlsx) — styled workbook.

    Three sheets:
      • "Buildings"   — one row per building point (1 example)
      • "Assembly"    — one row per assembly area (1 example)
      • "README"      — field descriptions + required/optional status

    When opened in Excel, the brand-coloured header row, autofilter and freeze
    pane give a clean, professional table presentation.
    """
    def _write(writer: pd.ExcelWriter) -> None:
        pd.DataFrame([_BUILDING_TEMPLATE_ROW]).to_excel(
            writer, sheet_name="Buildings", index=False,
        )
        pd.DataFrame([_ASSEMBLY_TEMPLATE_ROW]).to_excel(
            writer, sheet_name="Assembly", index=False,
        )
        pd.DataFrame(_DATA_GUIDE_ROWS).to_excel(
            writer, sheet_name="README", index=False,
        )

    return build_styled_workbook(_write)


def build_tuik_template_xlsx() -> bytes:
    """
    TÜİK neighbourhood-population Excel template (.xlsx) — styled workbook.

    Two sheets:
      • "TUIK_Population" — neighbourhood_name + population, 5 example rows
      • "README"          — field descriptions

    The user replaces the example rows with their own district's TÜİK figures.
    The styling layer (header, autofilter, freeze) gives a readable, pivot-like
    table view when opened.
    """
    def _write(writer: pd.ExcelWriter) -> None:
        pd.DataFrame(_TUIK_TEMPLATE_ROWS).to_excel(
            writer, sheet_name="TUIK_Population", index=False,
        )
        pd.DataFrame(_TUIK_GUIDE_ROWS).to_excel(
            writer, sheet_name="README", index=False,
        )

    return build_styled_workbook(_write)
