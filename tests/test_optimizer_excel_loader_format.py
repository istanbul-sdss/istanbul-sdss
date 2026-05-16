"""
Regresyon (P1.2): Optimizer Excel loader hem Türkçe disk-export'unu (header=1)
hem İngilizce indirilebilir workbook'u (header=0) okuyabilmeli; özet
sayfaları her iki dilde de filtre listesinden çıkarılmalı.

Audit bulgusu:
  • list_excel_sheets() skip listesi sadece Türkçe ('Özet', 'Mahalle', 'Veri Kal') →
    EN workbook'taki 'Summary', 'Neighborhood Pivot', 'Data Quality' sayfaları
    bina/toplanma seçeneği olarak gösteriliyordu.
  • load_from_excel() her zaman header=1 deniyordu; İngilizce workbook header=0
    yazıyor → ilk veri satırı kolon başlığı olur, kayıt kaybı.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from src.optimizer.data_loader import list_excel_sheets, load_from_excel


def _build_tr_workbook(path: Path):
    """ExcelExporter formatını taklit eder: kategori sheet'leri header=1
    (1. satır birleşik başlık)."""
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        # özet sayfaları
        pd.DataFrame({"x": [1, 2]}).to_excel(w, sheet_name="📊 Özet", index=False)
        pd.DataFrame({"x": [1]}).to_excel(w, sheet_name="🗺️ Mahalle Özeti", index=False)
        pd.DataFrame({"x": [1]}).to_excel(w, sheet_name="🔍 Veri Kalitesi", index=False)

        # Bina sheet'i: 1. satır başlık (boş row), 2. satır header
        df = pd.DataFrame({
            "Ad":          ["Bina A", "Bina B"],
            "Enlem":       [41.01, 41.02],
            "Boylam":      [29.01, 29.02],
            "Mahalle":     ["M1", "M2"],
            "Alan (m²)":   [100, 200],
            "Kat Sayısı":  [3, 5],
        })
        # Manuel olarak 1. satıra başlık koyalım
        df.to_excel(w, sheet_name="📍 Konut", index=False, startrow=1)

        df_top = pd.DataFrame({
            "Ad":        ["Park 1"],
            "Enlem":     [41.0],
            "Boylam":    [29.0],
            "Alan (m²)": [5000],
        })
        df_top.to_excel(w, sheet_name="📍 Toplanma", index=False, startrow=1)


def _build_en_workbook(path: Path):
    """Data Extraction İngilizce download formatını taklit eder: header=0."""
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        pd.DataFrame({"Category": ["a"], "Records": [10]}).to_excel(w, sheet_name="Summary", index=False)
        pd.DataFrame({"x": [1]}).to_excel(w, sheet_name="Neighborhood Pivot", index=False)
        pd.DataFrame({"Category": ["a"]}).to_excel(w, sheet_name="Data Quality", index=False)

        # Kategori sheet'leri header=0 (default)
        pd.DataFrame({
            "Name":         ["Bina A", "Bina B"],
            "Latitude":     [41.01, 41.02],
            "Longitude":    [29.01, 29.02],
            "Neighborhood": ["M1", "M2"],
            "Area (m²)":    [100, 200],
            "Floors":       [3, 5],
        }).to_excel(w, sheet_name="Residential", index=False)

        pd.DataFrame({
            "Name":      ["Park 1"],
            "Latitude":  [41.0],
            "Longitude": [29.0],
            "Area (m²)": [5000],
        }).to_excel(w, sheet_name="Park", index=False)


def test_list_excel_sheets_filters_turkish_summary():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "tr.xlsx"
        _build_tr_workbook(p)
        sheets = list_excel_sheets(p)
        assert sheets == ["📍 Konut", "📍 Toplanma"], (
            f"TR özet sayfaları filtrelenmedi: {sheets}"
        )


def test_list_excel_sheets_filters_english_summary():
    """İngilizce workbook için Summary/Neighborhood Pivot/Data Quality atılmalı."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "en.xlsx"
        _build_en_workbook(p)
        sheets = list_excel_sheets(p)
        forbidden = {"Summary", "Neighborhood Pivot", "Data Quality"}
        assert not (set(sheets) & forbidden), (
            f"REGRESYON: EN özet sayfaları kategori seçenek listesinde "
            f"görünüyor: {sheets}. Bu Excel optimizer'a geri yüklenirse "
            f"kullanıcı 'Summary' sheet'ini bina seçeneği olarak görür."
        )
        assert "Residential" in sheets and "Park" in sheets


def test_load_from_excel_handles_turkish_header_row_1():
    """TR workbook (header=1) bina sayısı doğru — ilk satır başlık olarak yorumlanmasın."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "tr.xlsx"
        _build_tr_workbook(p)
        b, t = load_from_excel(p, "📍 Konut", "📍 Toplanma")
    assert len(b) == 2, f"TR bina sayısı {len(b)} (beklenen 2)"
    assert len(t) == 1, f"TR toplanma sayısı {len(t)} (beklenen 1)"


def test_load_from_excel_handles_english_header_row_0():
    """
    EN workbook (header=0) bina sayısı doğru — ilk veri satırı başlığa
    çevrilmesin. Önceki davranış: header=1 zorla → A satırı header olur,
    kayıt kaybı.
    """
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "en.xlsx"
        _build_en_workbook(p)
        b, t = load_from_excel(p, "Residential", "Park")
    assert len(b) == 2, (
        f"REGRESYON: EN workbook'tan {len(b)} bina okundu (beklenen 2). "
        f"header=0 algılanmıyor; ilk satır kolon başlığı yapılmış olabilir."
    )
    assert len(t) == 1
