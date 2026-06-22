"""
src/optimizer/data_loader.py

Mevcut veri toplama aracının çıktısını (GeoJSON / Excel) okur,
p-median çözücüsünün beklediği standart formata dönüştürür.

Çıktı şeması — binalar:
  geometry      : Point
  weight        : tahmini nüfus (TÜİK bazlı, population_estimator kullanır)
  mahalle       : mahalle adı
  alan_m2       : bina footprint'i
  levels        : kat sayısı (OSM building:levels; yoksa varsayılan)
  name          : OSM name etiketi (varsa) — bina etiketi üretimi için
  osm_id        : OSM element ID'si — stabil kimlik için
  bina_etiketi  : okunabilir etiket (3-seviyeli fallback ile üretilir)

Çıktı şeması — toplanma alanları:
  geometry  : Point
  ad        : alan adı
  area_m2   : alan büyüklüğü (kapasite hesabı için)
  kapasite  : AFAD standardında kişi kapasitesi (area_m2 / 1.5, min 50)
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from src.config.settings import DEFAULT_ASSEMBLY_AREA_FALLBACK_M2
from src.logger import get_logger
from src.optimizer.population_estimator import (
    DEFAULT_LEVELS,
    estimate_capacity_afad,
    estimate_population,
    estimate_population_uniform_per_building,
)

log = get_logger(__name__)

WGS84   = "EPSG:4326"
UTM_IST = "EPSG:32635"


# Nüfus tahmin yöntemi sabitleri — UI, fonksiyon imzaları ve test dosyaları
# tarafından paylaşılan tek kaynak. Modül başında tanımlı oldukları için
# `load_from_excel` / `load_from_geojson` default argümanlarında güvenle
# kullanılabilirler.
POP_METHOD_FOOTPRINT = "footprint_based"
POP_METHOD_UNIFORM   = "uniform_per_building"
POP_METHOD_AUTO      = "auto"


# ── Yardımcılar ──────────────────────────────────────────────────────────────

# P1.2 düzeltmesi: GeoJSON yüklenince polygon footprint'i centroid'e çevrilmeden
# ÖNCE UTM'de gerçek alan hesaplanır ve "footprint_m2" kolonuna yazılır. Aksi
# halde alan kolonu olmayan polygon GeoJSON yüklemelerinde nüfus tahmini ve
# kapasite varsayılan değerlere (0 m², 1000 m²) düşüyordu — kullanıcı bunu
# fark etmeden "karar destek" raporları üretiyordu (audit P1.2).
_FOOTPRINT_COL = "footprint_m2"


def _ensure_polygon_footprint_column(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Polygon/MultiPolygon geometrileri için UTM (İstanbul EPSG:32635)
    alanını `footprint_m2` kolonuna yazar.

    Satır-bazlı davranış:
      • Kullanıcı / upstream alan kolonu varsa o değer KORUNUR (öncelikli).
      • Bu kolonda boş (NaN) veya geçersiz (≤0) satırlar varsa, polygon
        geometrisi olanlar UTM'de hesaplanıp doldurulur. Sadece point
        satırları boş kalır → downstream fallback (1000 m² toplanma) onlara
        uygulanır.
      • Hiç alan kolonu yoksa polygon satırları için kolon oluşturulup
        doldurulur.

    Yarım-fix uyarısı: Önceden bu fonksiyon "kolon var → erken return"
    yapıyordu; bu yüzden NaN satırlar için polygon alanı hesaplanmıyordu
    ve downstream sessiz 1000 m² fallback'ine düşüyordu.
    """
    if gdf.empty:
        return gdf
    gdf = gdf.copy()

    poly_mask = gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if not poly_mask.any():
        return gdf  # Hiç polygon yok, doldurulacak şey de yok

    # Mevcut alan kolonu var mı?
    existing = _pick_first_column(
        gdf, ["Alan (m²)", "Area (m²)", "alan_m2", "footprint_m2", "area_m2"]
    )

    # Hangi satırlar için polygon'dan hesap gerekiyor?
    if existing is not None:
        existing_vals = pd.to_numeric(gdf[existing], errors="coerce")
        # NaN veya ≤0 olan polygon satırları doldurulur; pozitif olanlara dokunma
        needs_fill = poly_mask & (existing_vals.isna() | (existing_vals <= 0))
    else:
        # Hiç kolon yok → tüm polygon satırları doldurulur
        needs_fill = poly_mask

    if not needs_fill.any():
        return gdf  # Tüm polygon satırlarının kullanıcı değeri var → değişiklik yok

    # UTM'de gerçek alan
    poly_subset = gdf.loc[needs_fill, ["geometry"]].copy()
    if poly_subset.crs is None:
        poly_subset = poly_subset.set_crs(WGS84)
    utm_areas = poly_subset.to_crs(UTM_IST).geometry.area.values

    if existing is not None:
        # Kullanıcı kolonunu satır-bazlı doldur (mevcut değerlere dokunma)
        gdf.loc[needs_fill, existing] = utm_areas
        # Provenance (opsiyonel): geometriden gelen satırları işaretle
        if "_geom_filled" not in gdf.columns:
            gdf["_geom_filled"] = False
        gdf.loc[needs_fill, "_geom_filled"] = True
    else:
        gdf[_FOOTPRINT_COL] = pd.NA
        gdf.loc[needs_fill, _FOOTPRINT_COL] = utm_areas
        gdf["_geom_filled"] = False
        gdf.loc[needs_fill, "_geom_filled"] = True

    return gdf


def _to_point_gdf(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Poligon geometrileri TEMSİLİ noktaya çevirir.

    P2.2 düzeltmesi: önceden WGS84'te `g.centroid` kullanılıyordu →
      • GeoPandas geographic CRS uyarısı
      • concave/MultiPolygon'larda centroid polygon DIŞINA düşebiliyor
      • İstanbul enleminde yatay/dikey ölçek farkı küçük sapma yaratıyor

    Yeni davranış: UTM (EPSG:32635) projeksiyonunda
    `representative_point()` üretir ve WGS84'e geri çevirir. Sonuç her
    zaman polygon İÇİNDE bir noktadır; karar destek için temsiliyet doğru.
    Point/MultiPoint geometrileri olduğu gibi geçer.

    NOT: Çağrıdan ÖNCE `_ensure_polygon_footprint_column()` çalıştırılmalı
    ki polygon alanı kaybolmasın. _prepare_binalar/_prepare_toplanma içinde
    bu sıra zorunlu kılınmıştır.
    """
    if gdf.empty:
        return gdf
    gdf = gdf.copy()
    if gdf.crs is None:
        gdf = gdf.set_crs(WGS84)

    # Polygon/MultiPolygon → UTM representative_point (polygon içinde garanti).
    poly_mask = gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if poly_mask.any():
        polys = gdf.loc[poly_mask, ["geometry"]].to_crs(UTM_IST)
        rep_utm = polys.geometry.representative_point()
        rep_wgs = gpd.GeoSeries(rep_utm, crs=UTM_IST).to_crs(WGS84)
        gdf.loc[poly_mask, "geometry"] = rep_wgs.values

    # Point/MultiPoint geometrilere dokunma.
    return gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()


def _pick_first_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Verilen adaylardan df'de bulunan ilk sütunu döner."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _extract_alan_m2(df: pd.DataFrame) -> pd.Series:
    """Bina alanını bul — Excel Türkçe veya GeoJSON İngilizce sütunu."""
    col = _pick_first_column(df, ["Alan (m²)", "Area (m²)", "alan_m2", "footprint_m2", "area_m2"])
    if col is None:
        log.warning("Alan sütunu bulunamadı — 0 m² atanıyor (nüfus tahmini düşük olur)")
        return pd.Series(0.0, index=df.index)
    return pd.to_numeric(df[col], errors="coerce").fillna(0.0)


def _extract_levels(df: pd.DataFrame) -> pd.Series:
    """Kat sayısını bul — OSM building:levels, Kat Sayısı veya fallback."""
    col = _pick_first_column(
        df, ["Kat Sayısı", "Floors", "building:levels", "levels", "floors"]
    )
    if col is None:
        log.info(f"Kat sayısı sütunu yok — varsayılan {DEFAULT_LEVELS} kat kullanılıyor")
        return pd.Series(DEFAULT_LEVELS, index=df.index, dtype=float)
    vals = pd.to_numeric(df[col], errors="coerce")
    filled = vals.fillna(DEFAULT_LEVELS).clip(lower=1, upper=60)
    return filled


def _extract_name(df: pd.DataFrame) -> pd.Series:
    """OSM name sütununu bul (varsa)."""
    col = _pick_first_column(df, ["Ad", "name", "Name"])
    if col is None:
        return pd.Series("", index=df.index, dtype=str)
    return df[col].fillna("").astype(str).str.strip()


def _extract_osm_id(df: pd.DataFrame) -> pd.Series:
    """OSM ID sütununu bul (varsa)."""
    col = _pick_first_column(df, ["OSM ID", "osm_id", "id"])
    if col is None:
        return pd.Series("", index=df.index, dtype=str)
    return df[col].fillna("").astype(str).str.strip()


def _extract_mahalle(df: pd.DataFrame) -> pd.Series:
    col = _pick_first_column(df, ["Mahalle", "Neighbourhood", "mahalle", "neighbourhood", "Neighborhood"])
    if col is None:
        return pd.Series("Bilinmeyen", index=df.index, dtype=str)
    return df[col].fillna("Bilinmeyen").astype(str).str.strip().replace({"": "Bilinmeyen"})


# P2.6: konut-dışı bina kalitesi göstergesi.
# population_estimator hanehalkı × daire alanı varsayımıyla çalışır → konut için
# doğru, ticari/ofis/endüstriyel/kamu/depo binaları için sistematik fazla
# tahmin. Toplam talep şişerse kapasite ihtiyacı, kapsama oranı ve P-Median
# kararları bozulur. Optimize aşamasından ÖNCE kullanıcıya gösterilen sayı
# burada üretilir; yorum population_estimator.py docstring'inde.
_NON_RESIDENTIAL_VALUES = {
    "commercial", "office", "retail", "industrial", "warehouse", "supermarket",
    "mall", "garage", "garages", "parking", "stadium", "sports_hall", "hotel",
    "fuel_station", "fuel", "kiosk", "civic", "public", "police", "fire_station",
    "school", "university", "hospital", "kindergarten", "church", "mosque",
    "synagogue", "place_of_worship",
    # Türkçe etiketler (translate_values sonrası)
    "ticari bina", "ofis binası", "avm / mağaza", "endüstriyel", "depo",
    "süpermarket", "garaj", "otopark", "stadyum", "spor salonu", "otel",
    "benzin istasyonu", "belediye binası", "kamu binası", "karakol",
    "i̇tfaiye", "itfaiye", "okul binası", "üniversite binası", "hastane binası",
    "cami", "kilise", "sinagog", "i̇badet yeri", "ibadet yeri",
}


def count_non_residential(df: pd.DataFrame) -> int:
    """
    Yüklenen bina tablosunda konut DIŞI olduğu açıkça anlaşılan satır sayısını
    sayar. "yes", "residential", "apartments", "house", boş gibi konut sinyali
    veren değerler sayılmaz; belirsiz kalanlar (yes / boş) kullanıcıya
    "muhtemelen konut" varsayımıyla geçirilir.
    """
    col = _pick_first_column(df, ["Bina Tipi", "building", "Building"])
    if col is None:
        return 0
    series = df[col].astype(str).str.strip().str.lower()
    return int(series.isin({v.lower() for v in _NON_RESIDENTIAL_VALUES}).sum())


def _generate_building_labels(
    names: pd.Series,
    mahalleler: pd.Series,
) -> pd.Series:
    """
    3-seviyeli fallback ile okunabilir etiket üretir:
      1. OSM name varsa → kısaltılmış ad
      2. Mahalle + sıra numarası → "Caferağa Mh. #142"

    Etiketler deterministik: aynı giriş aynı çıktıyı verir (sıra index'e göre).

    H4 düzeltmesi: önceki `names.iloc[names.index.get_loc(idx)] if
    isinstance(names.index, pd.Index) else names[idx]` aşırı defensif idi —
    `pd.Series.index` her zaman `pd.Index` örneği (RangeIndex de Index alt
    sınıfı), bu yüzden ikinci dal asla yürümüyordu ama get_loc çağrısı
    her satırda pahalıydı. `Series.loc[idx]` ile aynı sonucu doğrudan al.
    """
    _MEANINGLESS_NAMES = frozenset({"nan", "none", "yes", "building", "-"})

    labels: list[str] = []
    mah_counter: dict[str, int] = {}
    # OSM'de aynı `name` ile çoklu bina var (örn. "Migros", "MASKO"). Önceki
    # versiyon ikisini de aynı etikete çeviriyordu → Step 4 building
    # selectbox'ı `set(label_options)` ile dedup ettiği için ikinci binaya
    # ulaşılamıyordu (H-Opt-8). Çözüm: tekrarlı isimlere #2, #3 suffix ekle.
    # İlk geliş suffix'siz kalır (geriye uyumlu).
    name_counter: dict[str, int] = {}

    for idx in names.index:
        name_clean = str(names.loc[idx]).strip()
        mah        = mahalleler.loc[idx]

        # 1. OSM name varsa ve "yes"/"building" gibi anlamsız değerse atla
        if name_clean and name_clean.lower() not in _MEANINGLESS_NAMES:
            truncated = name_clean[:50]
            name_counter[truncated] = name_counter.get(truncated, 0) + 1
            if name_counter[truncated] > 1:
                labels.append(f"{truncated} #{name_counter[truncated]}")
            else:
                labels.append(truncated)
            continue

        # 2. Mahalle + sıra
        mah_counter[mah] = mah_counter.get(mah, 0) + 1
        # "Mh." ekini dublikasyondan kaçın
        mah_display = (
            mah
            if mah.lower().endswith(("mh.", "mah.", "mahallesi"))
            else f"{mah} Mh."
        )
        labels.append(f"{mah_display} #{mah_counter[mah]}")

    return pd.Series(labels, index=names.index, dtype=str)


# ── GeoJSON okuyucu ──────────────────────────────────────────────────────────

def _resolve_method(raw_gdf: gpd.GeoDataFrame, requested: str) -> str:
    """`POP_METHOD_AUTO` ise `detect_population_method`'a delege; aksi halde aynen döner."""
    if requested == POP_METHOD_AUTO:
        return detect_population_method(raw_gdf)
    return requested


def load_from_geojson(
    bina_path: str | Path,
    toplanma_path: str | Path,
    *,
    population_method: str = POP_METHOD_FOOTPRINT,
    mahalle_pop: pd.DataFrame | None = None,
    pop_name_col: str = "mahalle_adi",
    pop_value_col: str = "nufus",
    fuzzy_threshold: float = 85.0,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """İki ayrı GeoJSON dosyasından bina ve toplanma GeoDataFrame'i döner.

    `population_method` "auto" verilirse içeride `detect_population_method`
    ile karar verilir (footprint kolonu varsa footprint_based, yoksa
    uniform_per_building). Bu durumda `mahalle_pop` UI tarafında zorunlu
    kılınmalıdır — uniform seçilirse fonksiyon ValueError fırlatır.
    """
    binalar_raw  = gpd.read_file(bina_path).to_crs(WGS84)
    toplanma_raw = gpd.read_file(toplanma_path).to_crs(WGS84)
    effective = _resolve_method(binalar_raw, population_method)

    return (
        _prepare_binalar(
            binalar_raw,
            population_method=effective,
            mahalle_pop=mahalle_pop,
            pop_name_col=pop_name_col,
            pop_value_col=pop_value_col,
            fuzzy_threshold=fuzzy_threshold,
        ),
        _prepare_toplanma(toplanma_raw),
    )


# ── Excel okuyucu ────────────────────────────────────────────────────────────

def load_from_excel(
    excel_path: str | Path,
    bina_sheet: str,
    toplanma_sheet: str,
    *,
    population_method: str = POP_METHOD_FOOTPRINT,
    mahalle_pop: pd.DataFrame | None = None,
    pop_name_col: str = "mahalle_adi",
    pop_value_col: str = "nufus",
    fuzzy_threshold: float = 85.0,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """
    Veri toplama aracının Excel çıktısından okur. İki format desteklenir:

      1. **Türkçe disk-export** (`ExcelExporter`): kategori sayfasında 1. satır
         birleşik başlık, 2. satır kolon başlıkları → `header=1` lazım.
      2. **İngilizce indirilebilir workbook** (`pages/1_Data_Extraction.py`):
         standart `pd.to_excel(..., index=False)` → 1. satır kolon başlıkları
         → `header=0` lazım.

    P1.2 düzeltmesi: önceden her zaman `header=1` deneniyor, hata firlatmazsa
    kabul ediliyordu — İngilizce workbook'ta SESSİZCE ilk veri satırını
    kolon başlığı yapıyordu (kayıt kaybı). Artık iki seçenek de denenir,
    "Enlem/Boylam | Latitude/Longitude" benzeri kolonların hangisinde
    göründüğüne bakarak doğrusu seçilir.
    """
    # `with` context ile ExcelFile handle'ı garantili kapanır (Windows'ta dosya
    # kilidi sorununa karşı; tempfile cleanup'ı engellemesin).
    with pd.ExcelFile(excel_path) as xl:
        bina_df     = _read_sheet_with_format_detect(xl, bina_sheet)
        toplanma_df = _read_sheet_with_format_detect(xl, toplanma_sheet)

    # AUTO: bina GDF'inden (df→gdf sonrası) footprint var mı bak.
    bina_gdf_raw = _df_to_gdf(bina_df)
    effective = _resolve_method(bina_gdf_raw, population_method)

    return (
        _prepare_binalar(
            bina_gdf_raw,
            population_method=effective,
            mahalle_pop=mahalle_pop,
            pop_name_col=pop_name_col,
            pop_value_col=pop_value_col,
            fuzzy_threshold=fuzzy_threshold,
        ),
        _prepare_toplanma(_df_to_gdf(toplanma_df)),
    )


# Koordinat kolonlarını her iki dilde tanı: TR Enlem/Boylam, EN Latitude/Longitude
_COORD_HINTS = ("nlem", "oylam", "atitude", "ongitude", "lat", "lon")


def _looks_like_data_header(columns) -> bool:
    """Sütun adlarından en az birinde koordinat ipucu varsa header doğru kabul edilir."""
    if columns is None:
        return False
    return any(
        isinstance(c, str) and any(h in c for h in _COORD_HINTS)
        for c in columns
    )


def _read_sheet_with_format_detect(xl: pd.ExcelFile, name: str) -> pd.DataFrame:
    """
    Sheet'i hem header=0 hem header=1 ile dener; koordinat sütunu adını
    yakalayan versiyonu döndürür. İkisi de başarısızsa header=0 ile döner
    (downstream _df_to_gdf zaten net hata fırlatır).
    """
    candidates: list[tuple[int, pd.DataFrame]] = []
    for hdr in (0, 1):
        try:
            df = pd.read_excel(xl, sheet_name=name, header=hdr)
        except Exception:
            continue
        if _looks_like_data_header(df.columns):
            candidates.append((hdr, df))

    if not candidates:
        # En son çare: header=0 ham hâliyle dön; _df_to_gdf koordinat
        # bulamazsa açık ValueError fırlatacak (P1.3 ile sertleştirilmiş).
        return pd.read_excel(xl, sheet_name=name, header=0)

    # İki aday da koordinat içeriyorsa daha çok satır verene bak
    # (header=1 → ilk satır kayboluyorsa header=0 daha doğrudur).
    candidates.sort(key=lambda x: -len(x[1]))
    return candidates[0][1]


# İstanbul bounding box — biraz cömert (komşu ilçeleri ve Boğaz'ı kapsar).
# `validate_points_within_boundary` kesin sınır kontrolünü pipeline tarafında
# zaten yapıyor; burası sadece "yanlış şehir" sızıntısını eler.
_IST_LAT_MIN, _IST_LAT_MAX = 40.55, 41.65
_IST_LON_MIN, _IST_LON_MAX = 27.95, 30.10


def _df_to_gdf(df: pd.DataFrame) -> gpd.GeoDataFrame:
    """
    Enlem/Boylam sütunlarından GeoDataFrame oluşturur — sertleştirilmiş
    validasyon ile (P1.3 audit bulgusu).

    Eleme katmanları:
      1. **Eksik kolon** → `ValueError` (önceden sessiz çalışıyordu).
      2. **NaN koordinat** → düşür.
      3. **Aralık dışı** (lat ∉ [-90,90] veya lon ∉ [-180,180]) → düşür.
      4. **(0,0) sentinel** → düşür (Atlantic Ocean — tipik "missing" işareti).
      5. **İstanbul bbox dışı** → düşür + WARNING log (kullanıcı yanlış
         ilçeden veri yüklemiş olabilir).

    Önceki davranış sadece NaN dropna yapıyordu → bozuk koordinatlar OD
    matrisinde graf node'una snap edilip karar destek raporuna sızıyordu.
    """
    lat_col = next((c for c in df.columns if "nlem" in c or "atitude" in c or c.lower() == "lat"), None)
    lon_col = next((c for c in df.columns if "oylam" in c or "ongitude" in c or c.lower() == "lon"), None)

    if lat_col is None or lon_col is None:
        raise ValueError(
            f"Enlem/Boylam (Latitude/Longitude) sütunları bulunamadı. "
            f"Mevcut sütunlar: {list(df.columns)}"
        )

    df = df.copy()
    df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
    df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")

    n_total = len(df)

    # 2. NaN koordinat
    nan_mask = df[lat_col].isna() | df[lon_col].isna()

    # 3. WGS84 aralık dışı
    out_of_range = (
        ~df[lat_col].between(-90.0, 90.0, inclusive="both")
        | ~df[lon_col].between(-180.0, 180.0, inclusive="both")
    )

    # 4. (0,0) sentinel — kayan nokta için |x| < 1e-9
    zero_zero = (df[lat_col].abs() < 1e-9) & (df[lon_col].abs() < 1e-9)

    # 5. İstanbul bbox dışı (NaN olmayanlar için)
    in_ist = (
        df[lat_col].between(_IST_LAT_MIN, _IST_LAT_MAX, inclusive="both")
        & df[lon_col].between(_IST_LON_MIN, _IST_LON_MAX, inclusive="both")
    )
    out_of_ist = (~in_ist) & (~nan_mask) & (~out_of_range) & (~zero_zero)

    drop_mask = nan_mask | out_of_range | zero_zero | out_of_ist
    n_drop_total      = int(drop_mask.sum())
    n_drop_nan        = int(nan_mask.sum())
    n_drop_range      = int((out_of_range & ~nan_mask).sum())
    n_drop_zero       = int((zero_zero & ~nan_mask & ~out_of_range).sum())
    n_drop_outside    = int(out_of_ist.sum())

    if n_drop_total > 0:
        log.warning(
            f"Optimizer _df_to_gdf: {n_drop_total}/{n_total} satır geçersiz "
            f"koordinat nedeniyle düşürüldü "
            f"(NaN={n_drop_nan}, aralık dışı={n_drop_range}, "
            f"(0,0) sentinel={n_drop_zero}, İstanbul bbox dışı={n_drop_outside}). "
            f"Karar destek sonuçlarını etkilememesi için kontrol edin."
        )

    df = df.loc[~drop_mask].copy()
    geometry = [Point(lon, lat) for lat, lon in zip(df[lat_col], df[lon_col])]
    return gpd.GeoDataFrame(df, geometry=geometry, crs=WGS84)


# ── Standart forma getirme ───────────────────────────────────────────────────

def detect_population_method(gdf: gpd.GeoDataFrame) -> str:
    """
    Auto-detect: footprint kolonu var ve anlamlı dolu ise footprint-based,
    aksi halde uniform per-building önerilir.

    "Anlamlı dolu" eşiği: en az 1 satırda > 0 değer. Tüm satırlar 0/NaN
    ise footprint mevcut sayılmaz.
    """
    col = _pick_first_column(gdf, ["Alan (m²)", "Area (m²)", "alan_m2", "footprint_m2", "area_m2"])
    if col is None:
        return POP_METHOD_UNIFORM
    vals = pd.to_numeric(gdf[col], errors="coerce")
    if vals.fillna(0).gt(0).any():
        return POP_METHOD_FOOTPRINT
    return POP_METHOD_UNIFORM


def _prepare_binalar(
    gdf: gpd.GeoDataFrame,
    *,
    population_method: str = POP_METHOD_FOOTPRINT,
    mahalle_pop: pd.DataFrame | None = None,
    pop_name_col: str = "mahalle_adi",
    pop_value_col: str = "nufus",
    fuzzy_threshold: float = 85.0,
) -> gpd.GeoDataFrame:
    """
    Bina GeoDataFrame'ini standartlaştırır.

    Çıktı: geometry(Point), weight, mahalle, alan_m2, levels, name,
           osm_id, bina_etiketi, nufus_kaynak

    population_method:
        "footprint_based" — wᵢ = footprint × kat × 0.025 (varsayılan).
        "uniform_per_building" — wᵢ = mahalle_nüfus / bina_sayısı; bu
            mod `mahalle_pop` parametresini ZORUNLU kılar.

    nufus_kaynak provenance kolonu:
        "footprint_based"           — formül ile tahmin
        "uniform_per_building"      — TÜİK mahalle / bina sayısı
        "uniform_missing_mahalle"   — uniform mod, mahalle TÜİK'te yok
                                       (weight = NaN; downstream filtre)
    """
    if gdf.empty:
        return gpd.GeoDataFrame(
            columns=["geometry", "weight", "mahalle", "alan_m2", "levels",
                     "name", "osm_id", "bina_etiketi", "nufus_kaynak"],
            crs=WGS84,
        )

    # P1.2: polygon → centroid'e çevirmeden ÖNCE gerçek alanı yakala.
    gdf = _ensure_polygon_footprint_column(gdf)
    gdf = _to_point_gdf(gdf).reset_index(drop=True)

    # Ham alanları çıkar (her iki modda da gerekli)
    mahalle  = _extract_mahalle(gdf)
    alan_m2  = _extract_alan_m2(gdf)
    levels   = _extract_levels(gdf)
    name     = _extract_name(gdf)
    osm_id   = _extract_osm_id(gdf)

    # ── Nüfus tahmini — moda göre ───────────────────────────────────────
    pop_audit_uniform: pd.DataFrame | None = None
    if population_method == POP_METHOD_UNIFORM:
        if mahalle_pop is None:
            raise ValueError(
                "population_method='uniform_per_building' modu mahalle_pop "
                "parametresini gerektirir (TÜİK mahalle nüfus tablosu)."
            )
        # Geçici GDF'i (mahalle kolonu dolu) uniform fonksiyona ver
        _tmp = gpd.GeoDataFrame(
            {"mahalle": mahalle, "geometry": gdf.geometry}, crs=WGS84
        )
        weights, pop_audit_uniform = estimate_population_uniform_per_building(
            _tmp,
            mahalle_pop,
            mahalle_col="mahalle",
            name_col=pop_name_col,
            pop_col=pop_value_col,
            fuzzy_threshold=fuzzy_threshold,
        )
        nufus = weights
        # Provenance: TÜİK'te bulunamayan mahalle binaları NaN
        kaynak = pd.Series(
            np.where(nufus.isna(),
                     "uniform_missing_mahalle",
                     "uniform_per_building"),
            index=gdf.index,
            dtype=str,
        )
    elif population_method == POP_METHOD_FOOTPRINT:
        nufus = estimate_population(alan_m2, levels)
        kaynak = pd.Series("footprint_based", index=gdf.index, dtype=str)
    else:
        raise ValueError(
            f"population_method={population_method!r} geçersiz. "
            f"İzin verilen: 'footprint_based' | 'uniform_per_building'"
        )

    # Okunabilir etiket
    bina_etiketi = _generate_building_labels(name, mahalle)

    # P2.6: konut-dışı bina sayısı metaya
    n_non_residential = count_non_residential(gdf)

    # Weight yuvarlama — NaN korunmalı (uniform_missing_mahalle satırları)
    nufus_rounded = pd.to_numeric(nufus, errors="coerce").round(1)

    out = gpd.GeoDataFrame(
        {
            "geometry":     gdf.geometry,
            "weight":       nufus_rounded,
            "mahalle":      mahalle,
            "alan_m2":      alan_m2.round(1),
            "levels":       levels.astype(int),
            "name":         name,
            "osm_id":       osm_id,
            "bina_etiketi": bina_etiketi,
            "nufus_kaynak": kaynak,
        },
        crs=WGS84,
    )
    out.attrs["non_residential_count"] = int(n_non_residential)
    out.attrs["population_method"]     = population_method
    if pop_audit_uniform is not None:
        out.attrs["uniform_audit"] = pop_audit_uniform

    # Uniform mode'da TÜİK'te bulunamayan mahalle binaları weight=NaN aldı;
    # bu satırlar optimizasyon ağırlıklarını bozar (NaN propagation).
    # Onları AYIRIYORUZ ve attrs'a sayıyı + ayrı GDF'i ekliyoruz, UI bilgi
    # gösterebilir. Footprint mode'da NaN üretilmez → no-op.
    dropped: gpd.GeoDataFrame | None = None
    n_dropped = int(out["weight"].isna().sum())
    if n_dropped > 0:
        dropped = out[out["weight"].isna()].copy()
        out = out[out["weight"].notna()].copy().reset_index(drop=True)

    out.attrs["total_count"]                  = int(len(out))
    out.attrs["dropped_missing_weight_count"] = n_dropped
    if dropped is not None:
        out.attrs["dropped_missing_weight"]   = dropped

    log.info(
        f"Bina GDF hazır: {len(out):,} kayıt · "
        f"yöntem={population_method} · "
        f"toplam nüfus tahmini ≈ {out['weight'].sum():,.0f} kişi · "
        f"ort. kat sayısı = {out['levels'].mean():.1f} · "
        f"ort. m² = {out['alan_m2'].mean():.0f} · "
        f"konut-dışı: {n_non_residential:,}"
        + (f" · ⚠ {n_dropped} bina nüfus atanamadı → optimizasyondan düşürüldü"
           if n_dropped > 0 else "")
    )

    return out


def _prepare_toplanma(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Toplanma alanı GeoDataFrame'ini standartlaştırır.
    Çıktı: geometry(Point), ad, area_m2, kapasite (AFAD 1.5 m²/kişi)
    """
    if gdf.empty:
        return gpd.GeoDataFrame(
            columns=["geometry", "ad", "area_m2", "kapasite"], crs=WGS84
        )

    # P1.2: polygon → centroid'e çevirmeden ÖNCE gerçek alanı yakala.
    # Aksi halde alan kolonu olmayan polygon GeoJSON yüklemelerinde toplanma
    # alanı kapasitesi sessizce 1000 m² varsayımına düşüyordu.
    gdf = _ensure_polygon_footprint_column(gdf)
    gdf = _to_point_gdf(gdf).reset_index(drop=True)

    # Alan adı
    ad_col = _pick_first_column(gdf, ["Ad", "ad", "name", "Name", "adi"])
    if ad_col:
        ad = gdf[ad_col].fillna("").astype(str).str.strip()
    else:
        ad = pd.Series([""] * len(gdf), index=gdf.index, dtype=str)

    # Boş adlara numara ver
    bos = ad.isin(["", "nan", "None"])
    if bos.any():
        ad = ad.copy()
        ad.loc[bos] = [f"Toplanma Alanı {i+1}" for i in range(bos.sum())]

    # ── Alan m² — eksik veri şeffaf işaretleniyor ──────────────────────────
    # DÜZELTME: Önceki hali eksik alanları sessizce 1000 m²'ye çekiyordu →
    # kapasite hesaplarında "uydurulmuş" sayılar sessizce kullanılıyordu.
    # Artık `area_source` sütunuyla satır-bazlı izlenebilir:
    #   "measured"          : kullanıcı/OSM verisinden alınmış geçerli değer
    #   "geometry_measured" : kullanıcı değeri NaN/0 idi → polygon geometrisinden
    #                         UTM'de hesaplandı (P1.2 satır-bazlı düzeltme)
    #   "estimated"         : ne kullanıcı değeri ne polygon → 1000 m² fallback
    #                         (genellikle Point geometrili kayıtlar)
    # Tek kaynak: src/config/settings.py — yerel alias yalnızca okunabilirlik
    # için (var olan log mesajları DEFAULT_AREA_FALLBACK_M2 değişkenini referansa
    # alıyor; settings'teki yeni isim daha açıklayıcı ama burada lokal kalıyor).
    DEFAULT_AREA_FALLBACK_M2 = DEFAULT_ASSEMBLY_AREA_FALLBACK_M2

    # footprint_m2: polygon GeoJSON yüklenirken _ensure_polygon_footprint_column
    # tarafından eklenir (P1.2). Bu yüzden listeye dahil ediyoruz.
    alan_col = _pick_first_column(gdf, ["Alan (m²)", "Area (m²)", "alan_m2", "area_m2", "footprint_m2"])
    geom_filled = gdf.get("_geom_filled", pd.Series(False, index=gdf.index)).fillna(False).astype(bool)
    if alan_col:
        raw = pd.to_numeric(gdf[alan_col], errors="coerce")
        missing_mask = raw.isna() | (raw <= 0)
        area_m2 = raw.fillna(DEFAULT_AREA_FALLBACK_M2).where(
            ~missing_mask, DEFAULT_AREA_FALLBACK_M2
        )
        # Provenance: önce default 'measured', sonra geometry_measured override,
        # son olarak gerçek estimated (kolon yine NaN olanlar) override.
        area_source = pd.Series("measured", index=gdf.index, dtype=str)
        area_source.loc[geom_filled] = "geometry_measured"
        # Gerçek estimated: hem kolonda değer yok hem polygon doldurulamadı
        truly_missing = missing_mask & (~geom_filled)
        area_source.loc[truly_missing] = "estimated"
        n_missing = int(truly_missing.sum())
        n_geom_filled = int(geom_filled.sum())
        if n_geom_filled > 0:
            log.info(
                f"{n_geom_filled}/{len(gdf)} toplanma alanı: kullanıcı m² boş, "
                f"polygon geometrisinden hesaplandı (area_source='geometry_measured')."
            )
        if n_missing > 0:
            log.warning(
                f"[!] {n_missing}/{len(gdf)} toplanma alanında ne geçerli m² ne "
                f"polygon var — {DEFAULT_AREA_FALLBACK_M2:.0f} m² varsayımı "
                f"uygulandı (kapasite tahminidir; area_source='estimated')."
            )
    else:
        area_m2 = pd.Series(DEFAULT_AREA_FALLBACK_M2, index=gdf.index)
        area_source = pd.Series("estimated", index=gdf.index, dtype=str)
        log.warning(
            f"[!] Toplanma alanı için alan sütunu hiç yok — TÜMÜ "
            f"{DEFAULT_AREA_FALLBACK_M2:.0f} m² varsayımı. Kapasite rakamları "
            f"TAHMİNİDİR, karar-destek için bu uyarıyı kullanıcıya gösterin."
        )

    # AFAD standardında kapasite
    kapasite = estimate_capacity_afad(area_m2)

    out = gpd.GeoDataFrame(
        {
            "geometry":    gdf.geometry,
            "ad":          ad,
            "area_m2":     area_m2.round(0),
            "kapasite":    kapasite,
            "area_source": area_source,   # "measured" | "geometry_measured" | "estimated"
        },
        crs=WGS84,
    )

    n_est = int((area_source == "estimated").sum())
    n_total = len(out)
    # Madde 1.6: alan bilgisi yok ise (hepsi estimated → fallback) kapasite
    # kısıtı UI'da disabled olmalı. attrs.area_available flag downstream UI
    # tarafından kullanılır. Karışık durum (bazı satırlar measured, bazıları
    # estimated) yine area_available=True; UI ayrı bir warning gösterir.
    out.attrs["area_available"] = (n_est < n_total)
    out.attrs["estimated_count"] = n_est
    out.attrs["total_count"]     = n_total

    log.info(
        f"Toplanma GDF hazır: {n_total:,} alan · "
        f"toplam kapasite = {int(out['kapasite'].sum()):,} kişi · "
        f"ort. kapasite = {int(out['kapasite'].mean()):,} · "
        f"tahmini ({n_est} alan, area_available={out.attrs['area_available']})"
    )

    return out


# ── Excel sayfa listesi yardımcısı ────────────────────────────────────────────

def list_excel_sheets(excel_path: str | Path) -> list[str]:
    """
    Excel'deki kategori sayfalarını listeler (özet sayfaları hariç).

    P1.2: hem Türkçe (`Özet`, `Mahalle Özeti`, `Veri Kalitesi`) hem
    İngilizce (`Summary`, `Neighborhood Pivot`, `Data Quality`) özet
    sayfalarını filtre listesine alır. Eşleşme substring; emoji prefix'li
    Türkçe sheet'ler de yakalanır.
    """
    skip_substrings = (
        # Türkçe (ExcelExporter)
        "Özet", "Mahalle", "Veri Kal",
        # İngilizce (Data Extraction download)
        "Summary", "Neighborhood Pivot", "Data Quality",
    )
    # Windows handle kilidini önlemek için context manager
    with pd.ExcelFile(excel_path) as xl:
        sheet_names = list(xl.sheet_names)
    return [
        s for s in sheet_names
        if not any(sk in s for sk in skip_substrings)
    ]
