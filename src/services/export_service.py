from __future__ import annotations

import json
from datetime import datetime

import geopandas as gpd
import pandas as pd

from src.utils import get_output_path


def prepare_gdf_for_file_export(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    GeoJSON export öncesi ek geometry kolonlarını güvenli hale getirir.
    Ana geometry kolonu korunur, diğer geometry kolonları WKT'ye çevrilir.
    """
    result = gdf.copy()

    if result.empty:
        return result

    active_geometry_name = result.geometry.name

    for col in result.columns:
        if col == active_geometry_name:
            continue

        series = result[col]

        # GeoSeries veya geometry dtype benzeri kolonları stringe çevir
        try:
            if isinstance(series, gpd.GeoSeries) or hasattr(series, "geom_type"):
                result[col] = series.to_wkt()
        except Exception:
            pass

    return result


def prepare_df_for_csv_export(df: pd.DataFrame) -> pd.DataFrame:
    """
    CSV export öncesi geometry benzeri kolonları WKT'ye çevirir.
    """
    result = df.copy()

    for col in result.columns:
        series = result[col]
        try:
            if isinstance(series, gpd.GeoSeries) or hasattr(series, "geom_type"):
                result[col] = series.to_wkt()
        except Exception:
            pass

    return result


def export_geojson(
    gdf: gpd.GeoDataFrame,
    filename: str,
    prefix: str = "",
) -> str:
    if gdf.empty:
        return ""

    path = get_output_path(filename, prefix, "geojson")
    export_gdf = prepare_gdf_for_file_export(gdf)
    export_gdf.to_file(path, driver="GeoJSON")

    return path


def export_csv(
    df: pd.DataFrame,
    filename: str,
    prefix: str = "",
) -> str:
    if df.empty:
        return ""

    path = get_output_path(filename, prefix, "csv")
    export_df = prepare_df_for_csv_export(df)
    export_df.to_csv(path, index=False, encoding="utf-8-sig")

    return path


def export_classification_results(
    classified_df: pd.DataFrame,
    resolved_df: pd.DataFrame,
    unresolved_df: pd.DataFrame,
    prefix: str,
) -> dict:
    outputs = {}

    outputs["classified_geojson"] = export_geojson(
        classified_df,
        "classified",
        prefix,
    )
    outputs["resolved_geojson"] = export_geojson(
        resolved_df,
        "resolved",
        prefix,
    )
    outputs["unresolved_geojson"] = export_geojson(
        unresolved_df,
        "unresolved",
        prefix,
    )

    outputs["classified_csv"] = export_csv(
        classified_df,
        "classified",
        prefix,
    )
    outputs["resolved_csv"] = export_csv(
        resolved_df,
        "resolved",
        prefix,
    )
    outputs["unresolved_csv"] = export_csv(
        unresolved_df,
        "unresolved",
        prefix,
    )

    return outputs


def export_layer(
    gdf: gpd.GeoDataFrame,
    layer_name: str,
    prefix: str,
) -> dict:
    return {
        "geojson": export_geojson(gdf, layer_name, prefix),
        "csv": export_csv(gdf, layer_name, prefix),
    }


def generate_summary_report(
    summary: dict,
    outputs: dict,
    prefix: str,
    extra_info: dict | None = None,
) -> str:
    report_path = get_output_path("report", prefix, "txt")

    lines = []
    lines.append("=== OSM EXTRACTION REPORT ===\n")
    lines.append(f"Tarih: {datetime.now()}\n")

    lines.append("\n--- SUMMARY ---\n")
    for key, value in summary.items():
        lines.append(f"{key}: {value}\n")

    if extra_info:
        lines.append("\n--- EXTRA INFO ---\n")
        for key, value in extra_info.items():
            lines.append(f"{key}: {value}\n")

    lines.append("\n--- OUTPUT FILES ---\n")
    for key, value in outputs.items():
        lines.append(f"{key}: {value}\n")

    with open(report_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return report_path


def export_summary_json(
    summary: dict,
    prefix: str,
) -> str:
    path = get_output_path("summary", prefix, "json")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return path
