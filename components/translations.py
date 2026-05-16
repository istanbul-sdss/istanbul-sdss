"""
components/translations.py — Turkish → English translation layer.

The backend pipeline produces DataFrames with Turkish column names
(Ad, Enlem, Boylam, Mahalle, ...). This module translates those to
English for UI display and English-language exports, without touching
the backend code.

Usage:
    from components.translations import to_english, translate_category_label

    df_en = to_english(df)                   # rename columns + translate values
    label = translate_category_label("Hastane")   # → "Hospital"
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

import pandas as pd

from src.config.category_registry import CATEGORY_REGISTRY

# ─────────────────────────────────────────────────────────────────────────────
# COLUMN MAP  (TR → EN)
# ─────────────────────────────────────────────────────────────────────────────
COLUMN_MAP_EN: dict[str, str] = {
    # Identity
    "Ad":               "Name",
    "OSM ID":           "OSM ID",
    "OSM Tipi":         "OSM Type",

    # Category columns — distinct targets to avoid collisions
    "Kategori (TR)":    "Category",          # human-readable category label
    "Kategori":         "Category Key",      # raw technical key
    "Alt Kategori":     "Subcategory",
    "Tür":              "Type",

    # Rule engine / classification metadata
    "Kural Kodu":       "Rule Code",
    "Eşleşme Nedeni":   "Match Reason",
    "Eşleşme":          "Match",
    "Güven":            "Confidence",
    "Kaynak":           "Source",

    # Location
    "Mahalle":          "Neighborhood",
    "Sınır Durumu":     "Boundary Status",
    "İlçe":             "District",
    "İl":               "Province",
    "Enlem":            "Latitude",
    "Boylam":           "Longitude",
    "Adres":            "Address",

    # Contact
    "Telefon":          "Phone",
    "Web":              "Website",
    "Website":          "Website",
    "Email":            "Email",
    "E-posta":          "Email",

    # Hours / ops
    "Açılış":           "Opening Hours",
    "Açılış Saati":     "Opening Hours",
    "Kapasite":         "Capacity",
    "Operatör":         "Operator",
    "Marka":            "Brand",

    # Dimensions
    "Alan (m²)":        "Area (m²)",
    "Alan Kaynağı":     "Area Source",
    "Çevre (m)":        "Perimeter (m)",
    "Uzunluk (m)":      "Length (m)",
    "Kat Sayısı":       "Floors",
    "Kat":              "Floors",
    "Yükseklik":        "Height",

    # Domain-specific (extra attribute columns surfaced by rule engine)
    "Tesis":            "Facility",
    "Sağlık Tipi":      "Health Type",
    "Sağlık Türü":      "Health Type",
    "Okul Tipi":        "School Type",
    "Okul Türü":        "School Type",
    "Bina Tipi":        "Building Type",
    "Bina Türü":        "Building Type",
    "Ulaşım Tipi":      "Transport Type",
    "Din":              "Religion",
    "Mezhep":           "Denomination",
    "Sahip":            "Owner",

    # Geometry / export
    "Geometri":         "Geometry",
    "Geometri Tipi":    "Geometry Type",

    # Generic
    "Notlar":           "Notes",
    "Açıklama":         "Description",
    "Etiket":           "Tag",
    "Etiketler":        "Tags",
    "Durum":            "Status",
    "Toplam":           "Total",
    "TOPLAM":           "TOTAL",

    # ── Optimizer (assembly-area / P-Median) columns ────────────────────────
    "bina_no":          "Building No",
    "bina_etiketi":     "Building Label",
    "bina_idx":         "Building ID",
    "alan_idx":         "Area ID",
    "alan_adi":         "Assembly Area",
    "atama_ozeti":      "Assignment",
    "sure_dk":          "Time (min)",
    "sure_araligi":     "Time Band",
    "erisim_kalitesi":  "Access Quality",
    "mahalle":          "Neighborhood",
    "agirlik":          "Weight",
    "bina_enlem":       "Building Latitude",
    "bina_boylam":      "Building Longitude",
    "alan_enlem":       "Area Latitude",
    "alan_boylam":      "Area Longitude",
    "alan_m2":          "Building Area (m²)",
    "kat_sayisi":       "Floors",
    "alternatif_1":     "Alternative 1",
    "alternatif_1_sure": "Alternative 1 Time (min)",
    "alternatif_2":     "Alternative 2",
    "alternatif_2_sure": "Alternative 2 Time (min)",
    "alternatif_3":     "Alternative 3",
    "alternatif_3_sure": "Alternative 3 Time (min)",
    "sebep":            "Reason",
    "Ağ. Ort. Süre (dk)":    "Weighted Avg Time (min)",
    # P95: artık iki ayrı kolon — etiketler hangi metriğin hangi ağırlık
    # mantığını kullandığını açıkça gösterir.
    "P95 Süre (dk)":                       "P95 Time (min)",
    "P95 Süre (dk, nüfus-ağırlıklı)":      "P95 Time (min, pop-weighted)",
    "P95 Süre (dk, bina-bazlı)":           "P95 Time (min, building-count)",
    "Nüfus Kapsama <5dk %":  "Pop Coverage <5min %",
    "Nüfus Kapsama <10dk %": "Pop Coverage <10min %",
    "Nüfus Kapsama <30dk %": "Pop Coverage <30min %",
    "Ulaşılamaz Bina":       "Unreachable Buildings",

    "Toplanma Alanı":   "Assembly Area",
    "Atanan Bina":      "Assigned Buildings",
    "Toplam Ağırlık":   "Total Weight",
    "Ort. Süre (dk)":   "Avg Time (min)",
    "Max Süre (dk)":    "Max Time (min)",
    "Maks. Süre (dk)":  "Max Time (min)",
    "Kapsama <5dk %":   "Coverage <5min %",
    "Kapsama <10dk %":  "Coverage <10min %",
    "Kapsama <30dk %":  "Coverage <30min %",
    "Uzak / Çok Uzak Bina": "Buildings >15min",
    "Toplam Ağırlıklı Süre": "Total Weighted Time",
    "Çözüm Süresi (sn)":  "Solve Time (s)",
    "Yöntem":            "Method",
    "Metrik":            "Metric",
    "Değer":             "Value",
}


# ─────────────────────────────────────────────────────────────────────────────
# CONFIDENCE MAP
# ─────────────────────────────────────────────────────────────────────────────
CONFIDENCE_MAP_EN: dict[str, str] = {
    "Yüksek":   "High",
    "Orta":     "Medium",
    "Düşük":    "Low",
    "Belirsiz": "Unknown",
}


STATUS_MAP_EN: dict[str, str] = {
    "✅ Tamam":   "✅ Complete",
    "⚠️ Veri Yok": "⚠️ No Data",
    "Tamam":      "Complete",
    "Veri Yok":   "No Data",
    "Eksik":      "Missing",
    "Mevcut":     "Available",
}

# Sınır Durumu (boundary_status) — assign_neighbourhoods çıktısı.
# to_english() bu kolonu da çevirir (Boundary Status değerleri için).
BOUNDARY_STATUS_MAP_EN: dict[str, str] = {
    "ilçe_içi":   "Inside district",
    "sınır_üstü": "On boundary",
    "ilçe_dışı":  "Outside district",
}


ACCESS_QUALITY_MAP_EN: dict[str, str] = {
    "Çok iyi": "Excellent",
    "İyi": "Good",
    "Kabul edilebilir": "Acceptable",
    "Uzak": "Far",
    "Çok uzak": "Very far",
}


# ─────────────────────────────────────────────────────────────────────────────
# CATEGORY TR → EN  (built from CATEGORY_REGISTRY)
# ─────────────────────────────────────────────────────────────────────────────
def _build_category_label_map() -> dict[str, str]:
    """Build {tr_label: en_label} from the registry subcategories."""
    m: dict[str, str] = {}
    for cat in CATEGORY_REGISTRY.values():
        # main category
        tr = cat.get("label_tr")
        en = cat.get("label_en")
        if tr and en:
            m[tr] = en
        # subcategories
        for sub in cat.get("subcategories", []):
            tr_sub = sub.get("label_tr")
            en_sub = sub.get("label_en")
            if tr_sub and en_sub:
                m[tr_sub] = en_sub
    return m


CATEGORY_LABEL_MAP_EN: dict[str, str] = _build_category_label_map()


@lru_cache(maxsize=512)
def translate_category_label(tr_label: str) -> str:
    """
    Translate a single category/subcategory Turkish label to English.

    LRU cached: aynı label rerun başına onlarca kez çağrılıyor (sidebar,
    chips, tab başlıkları, Excel sheet adları). Saf string→string lookup
    olduğu için cache her zaman güvenli.
    """
    if not tr_label:
        return tr_label
    return CATEGORY_LABEL_MAP_EN.get(tr_label, tr_label)


# ─────────────────────────────────────────────────────────────────────────────
# REGISTRY HELPERS (English)
# ─────────────────────────────────────────────────────────────────────────────
# Process-local cache: CATEGORY_REGISTRY çalışma zamanında değişmiyor → her
# rerun'da listenin yeniden inşa edilmesi gereksiz. Manual Select sidebar'ı
# her widget tıklamasında bu helper'ı çağırıyordu → 20+ kategori için tekrar
# tekrar dict comprehension. Cache'lenmiş çıktıyı tuple olarak tutup mutate
# edilemez yapıyoruz; çağrı sahibi listeye ihtiyaç duyuyorsa list() ile sarar.
@lru_cache(maxsize=1)
def _main_categories_cached() -> tuple[dict, ...]:
    rows = []
    for key, value in sorted(
        CATEGORY_REGISTRY.items(),
        key=lambda item: item[1].get("ui_order", 999),
    ):
        rows.append({
            "key":   key,
            "label": f"{value.get('icon', '')} {value.get('label_en', value.get('label_tr', key))}".strip(),
            "icon":  value.get("icon", ""),
        })
    return tuple(rows)


def get_main_category_options_en() -> list[dict]:
    """English variant of get_main_category_options_tr() — cached."""
    return list(_main_categories_cached())


@lru_cache(maxsize=64)
def _subcategories_cached(category_key: str) -> tuple[dict, ...]:
    if category_key not in CATEGORY_REGISTRY:
        raise ValueError(f"Invalid category: {category_key}")
    return tuple(
        {
            "key":   item["key"],
            "label": item.get("label_en", item.get("label_tr", item["key"])),
            "code":  item["code"],
        }
        for item in CATEGORY_REGISTRY[category_key]["subcategories"]
    )


def get_subcategory_options_en(category_key: str) -> list[dict]:
    """English variant of get_subcategory_options_tr() — cached per category."""
    return list(_subcategories_cached(category_key))


# ─────────────────────────────────────────────────────────────────────────────
# DATAFRAME TRANSLATION
# ─────────────────────────────────────────────────────────────────────────────
def _dedupe_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    If multiple source columns mapped to the same English name, keep the
    first non-empty occurrence and suffix any remaining duplicates with
    ' (2)', ' (3)', ... so Streamlit/Arrow won't reject the frame.
    """
    cols = list(df.columns)
    if len(cols) == len(set(cols)):
        return df

    seen: dict[str, int] = {}
    new_cols: list[str] = []
    for c in cols:
        if c in seen:
            seen[c] += 1
            new_cols.append(f"{c} ({seen[c]})")
        else:
            seen[c] = 1
            new_cols.append(c)

    out = df.copy()
    out.columns = new_cols
    return out


# Cache stratejisi (eski `id(df)` yaklaşımı düzeltildi):
#
#   Eski versiyon `id(df)` cache anahtarı kullanıyordu. İki sorun:
#     1. CPython GC adres yeniden kullanımı → farklı içerikli iki df aynı
#        id alabilir → yanlış cache hit (rapor edilen bug: P2).
#     2. Cache'ten dönen referans MUTABLE — caller mutate ederse cache'teki
#        içerik bozulur ("bayat veri" senaryosu).
#
#   Yeni davranış:
#     • Cache anahtarı veri içeriği + kolon imzasından türetilir
#       (src/utils.py::df_content_hash). Aynı içerik aynı anahtar; içerik
#        değişirse anahtar değişir → cache hit doğru.
#     • Cache'ten dönen değer DAİMA `.copy()` — caller mutate edebilir,
#        cache'teki orijinal güvende kalır.
#     • Anahtar `(content_hash, columns, translate_values)` üçlüsü.
#
#   Performans: hash maliyeti Kadıköy boyutunda ~10-30ms; rerun başına
#   5+ to_english çağrısı düşünüldüğünde hâlâ net kazanç (her birinde
#   tam copy + map zincirini atlamak ~50-150ms).
_TO_ENGLISH_CACHE: dict[tuple, pd.DataFrame] = {}
_TO_ENGLISH_CACHE_MAX = 32


def _to_english_cache_key(df: pd.DataFrame, translate_values: bool) -> tuple:
    """İçerik tabanlı stabil cache anahtarı (`id(df)` bağımlılığı yok)."""
    from src.utils import df_content_hash
    return (
        df_content_hash(df),
        tuple(df.columns),
        bool(translate_values),
    )


def to_english(
    df: pd.DataFrame,
    translate_values: bool = True,
) -> pd.DataFrame:
    """
    Return a fresh DataFrame with:
      • columns renamed from TR to EN
      • Confidence column values translated (Yüksek → High, etc.)
      • Category column values translated where possible
      • Status column values translated
      • Any accidental duplicate column names disambiguated

    Cache (P2 düzeltmesi): aynı içerikli df birden fazla yerden çağrılırsa
    copy + map tekrar edilmez. Cache anahtarı veri içeriği bazlı (`id(df)`
    GC reuse bug'ından bağışık), dönen değer her zaman `.copy()` — caller
    mutate ederse cache içeriği bozulmaz.
    """
    if df is None or df.empty:
        return df

    cache_key = _to_english_cache_key(df, translate_values)
    cached = _TO_ENGLISH_CACHE.get(cache_key)
    if cached is not None:
        # Caller'a daima yeni bir kopya ver — caller mutate ederse cache
        # bozulmaz. Shallow copy yeter (kolonlar/değerler kopyalanır).
        return cached.copy()

    out = df.copy()

    # Column rename
    out = out.rename(columns={c: COLUMN_MAP_EN.get(c, c) for c in out.columns})

    # Guard against duplicates (some TR columns may legitimately map to the same EN name)
    out = _dedupe_columns(out)

    if not translate_values:
        # translate_values=False yolunda da cache'i besle (mutation güvenli copy)
        if len(_TO_ENGLISH_CACHE) >= _TO_ENGLISH_CACHE_MAX:
            _TO_ENGLISH_CACHE.pop(next(iter(_TO_ENGLISH_CACHE)))
        _TO_ENGLISH_CACHE[cache_key] = out
        return out.copy()

    # Value translations
    if "Confidence" in out.columns:
        out["Confidence"] = out["Confidence"].map(
            lambda v: CONFIDENCE_MAP_EN.get(v, v) if pd.notna(v) else v
        )

    if "Category" in out.columns:
        out["Category"] = out["Category"].map(
            lambda v: translate_category_label(v) if pd.notna(v) else v
        )

    if "Subcategory" in out.columns:
        out["Subcategory"] = out["Subcategory"].map(
            lambda v: translate_category_label(v) if pd.notna(v) else v
        )

    if "Status" in out.columns:
        out["Status"] = out["Status"].map(
            lambda v: STATUS_MAP_EN.get(v, v) if pd.notna(v) else v
        )

    if "Boundary Status" in out.columns:
        out["Boundary Status"] = out["Boundary Status"].map(
            lambda v: BOUNDARY_STATUS_MAP_EN.get(v, v) if pd.notna(v) else v
        )

    if "Access Quality" in out.columns:
        out["Access Quality"] = out["Access Quality"].map(
            lambda v: ACCESS_QUALITY_MAP_EN.get(v, v) if pd.notna(v) else v
        )

    # Cache'e koy; sınır aşıldıysa eskilerden 1 tanesini at (basit FIFO).
    # Caller'a kopya döner; cache'te tutulan orijinal mutate edilmez.
    if len(_TO_ENGLISH_CACHE) >= _TO_ENGLISH_CACHE_MAX:
        _TO_ENGLISH_CACHE.pop(next(iter(_TO_ENGLISH_CACHE)))
    _TO_ENGLISH_CACHE[cache_key] = out
    return out.copy()


def columns_to_english(cols: Iterable[str]) -> list[str]:
    """Translate a list of column names only (no DataFrame)."""
    return [COLUMN_MAP_EN.get(c, c) for c in cols]
