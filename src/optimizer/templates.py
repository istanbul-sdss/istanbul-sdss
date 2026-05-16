"""
src/optimizer/templates.py

Kullanıcının kendi Excel dosyasını hazırlayabilmesi için indirilebilir
şablonlar üretir. İki şablon:

  1. Bina + toplanma alanı Excel workbook (3 sheet: Buildings + Assembly + README)
  2. TÜİK mahalle nüfus Excel workbook (TUIK_Population + README)

Tüm şablonlar `build_styled_workbook` ile aynı stil katmanından geçer:
brand-renkli header satırı, autofilter, freeze pane, kolon-genişlik
otomatik ayarı. Bu hocaların talep ettiği "pivot table benzeri tablo
görünümü"nü karşılar — açıldığında profesyonel tablo izlenimi verir.
"""
from __future__ import annotations

import pandas as pd

from src.services.excel_utils import build_styled_workbook

# ── Şablon satır içerikleri (örnek satır kullanıcıya format kanıtı) ───────
_BINA_TEMPLATE_ROW = {
    "Enlem":      40.9923,
    "Boylam":     29.0249,
    "Mahalle":    "Caferağa",
    "Ad":         "(opsiyonel) bina adı / yapı adı",
    "Alan (m²)":  220.0,
    "Kat Sayısı": 5,
    "OSM ID":     "(opsiyonel) stabil kimlik için",
}

_TOPLANMA_TEMPLATE_ROW = {
    "Enlem":     40.9856,
    "Boylam":    29.0285,
    "Ad":        "Caferağa Parkı",
    "Alan (m²)": 4500.0,
    "Mahalle":   "(opsiyonel) bulunduğu mahalle",
}

_TUIK_TEMPLATE_ROWS = [
    {"mahalle_adi": "Caferağa",         "nufus": 21350},
    {"mahalle_adi": "Fenerbahçe",       "nufus":  9800},
    {"mahalle_adi": "Göztepe Mahallesi","nufus": 36000},
    {"mahalle_adi": "Acıbadem",         "nufus": 28600},
    {"mahalle_adi": "19 Mayıs",         "nufus": 31864},
]

_DATA_GUIDE_ROWS = [
    {"Field": "Enlem / Boylam",
     "Required": "Yes",
     "Notes": "WGS84 (EPSG:4326) ondalık derece. İstanbul aralığında olmalı."},
    {"Field": "Mahalle",
     "Required": "Buildings: yes (uniform mode için kritik); Assembly: optional",
     "Notes": "TÜİK eşleşmesi için kullanılır."},
    {"Field": "Alan (m²)",
     "Required": "Recommended",
     "Notes": "Buildings: footprint-based nüfus tahmininde gerekli. "
              "Assembly: kapasite (AFAD 1.5 m²/kişi) için gerekli."},
    {"Field": "Kat Sayısı",
     "Required": "Recommended (Buildings only)",
     "Notes": "Boş bırakılırsa varsayılan 4 kat kullanılır."},
    {"Field": "Ad",
     "Required": "Optional (Buildings) / Recommended (Assembly)",
     "Notes": "Raporlarda etiket olarak kullanılır."},
    {"Field": "OSM ID",
     "Required": "Optional",
     "Notes": "Aynı veriyi tekrar yüklemede stabil kimlik."},
]

_TUIK_GUIDE_ROWS = [
    {"Field": "mahalle_adi",
     "Required": "Yes",
     "Notes": "TÜİK kayıtlı mahalle adı. 'Mahallesi' / 'Mh.' suffix'leri "
              "otomatik tolere edilir; tipografik farklar (Zühtüpaşa vs "
              "Zühütpaşa) fuzzy eşleşme ile yakalanır (threshold 85)."},
    {"Field": "nufus",
     "Required": "Yes",
     "Notes": "Pozitif tam sayı. Sıfır veya boş satırlar dağıtımda "
              "kullanılmaz, ilgili mahalle binaları weight=NaN alır."},
]


def build_data_template_xlsx() -> bytes:
    """
    Bina + toplanma alanı Excel şablonu (.xlsx) — styled workbook.

    Üç sheet:
      • "Buildings"   — bina noktası başına bir satır (1 örnek)
      • "Assembly"    — toplanma alanı başına bir satır (1 örnek)
      • "README"      — alan açıklamaları + zorunluluk durumları

    Excel açıldığında brand-renkli header satırı, autofilter, freeze
    pane görünür — tablo görünümünde profesyonel sunumu sağlar.
    """
    def _write(writer: pd.ExcelWriter) -> None:
        pd.DataFrame([_BINA_TEMPLATE_ROW]).to_excel(
            writer, sheet_name="Buildings", index=False,
        )
        pd.DataFrame([_TOPLANMA_TEMPLATE_ROW]).to_excel(
            writer, sheet_name="Assembly", index=False,
        )
        pd.DataFrame(_DATA_GUIDE_ROWS).to_excel(
            writer, sheet_name="README", index=False,
        )

    return build_styled_workbook(_write)


def build_tuik_template_xlsx() -> bytes:
    """
    TÜİK mahalle nüfus Excel şablonu (.xlsx) — styled workbook.

    İki sheet:
      • "TUIK_Population" — mahalle_adi + nufus, 5 örnek satır
      • "README"          — alan açıklamaları

    Kullanıcı kendi ilçesinin TÜİK verisiyle örnek satırları değiştirir.
    Excel açıldığında stil katmanı (header, autofilter, freeze) sayesinde
    pivot-table benzeri okunabilir tablo izlenimi verir.
    """
    def _write(writer: pd.ExcelWriter) -> None:
        pd.DataFrame(_TUIK_TEMPLATE_ROWS).to_excel(
            writer, sheet_name="TUIK_Population", index=False,
        )
        pd.DataFrame(_TUIK_GUIDE_ROWS).to_excel(
            writer, sheet_name="README", index=False,
        )

    return build_styled_workbook(_write)
