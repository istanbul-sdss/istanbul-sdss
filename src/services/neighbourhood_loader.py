"""
src/services/neighbourhood_loader.py

39 İstanbul ilçesi için yerel GeoJSON mahalle sınırlarını yükler.

Dosya konvansiyonu:
    data/mahalleleri/kadikoy.geojson
    data/mahalleleri/besiktas.geojson
    ...
"""
from __future__ import annotations

import json
import warnings
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import pandas as pd

from src.config.settings import MAH_DIR_STR
from src.logger import get_logger

log = get_logger(__name__)

WGS84 = "EPSG:4326"

# ── İlçe adı → dosya adı eşlemesi ────────────────────────────────────────────
ILCE_DOSYA_ADI: dict[str, str] = {
    "Adalar":         "adalar",
    "Arnavutköy":     "arnavutkoy",
    "Ataşehir":       "atasehir",
    "Avcılar":        "avcilar",
    "Bağcılar":       "bagcilar",
    "Bahçelievler":   "bahcelievler",
    "Bakırköy":       "bakirkoy",
    "Başakşehir":     "basaksehir",
    "Bayrampaşa":     "bayrampasa",
    "Beşiktaş":       "besiktas",
    "Beykoz":         "beykoz",
    "Beylikdüzü":     "beylikduzu",
    "Beyoğlu":        "beyoglu",
    "Büyükçekmece":   "buyukcekmece",   # ← DÜZELTİLDİ
    "Çatalca":        "catalca",
    "Çekmeköy":       "cekmekoy",
    "Esenler":        "esenler",
    "Esenyurt":       "esenyurt",
    "Eyüpsultan":     "eyupsultan",
    "Fatih":          "fatih",
    "Gaziosmanpaşa":  "gaziosmanpasa",
    "Güngören":       "gungoren",
    "Kadıköy":        "kadikoy",
    "Kağıthane":      "kagithane",
    "Kartal":         "kartal",
    "Küçükçekmece":   "kucukcekmece",   # ← DÜZELTİLDİ
    "Maltepe":        "maltepe",
    "Pendik":         "pendik",
    "Sancaktepe":     "sancaktepe",
    "Sarıyer":        "sariyer",
    "Şile":           "sile",
    "Silivri":        "silivri",
    "Şişli":          "sisli",
    "Sultanbeyli":    "sultanbeyli",
    "Sultangazi":     "sultangazi",
    "Tuzla":          "tuzla",
    "Ümraniye":       "umraniye",
    "Üsküdar":        "uskudar",
    "Zeytinburnu":    "zeytinburnu",
}

# NOTE: The canonical list of districts lives in src/config/settings.py
# (`ISTANBUL_ILCELER`). This module previously also defined
# `ISTANBUL_ILCELER = list(ILCE_DOSYA_ADI.keys())` which created two
# parallel sources of truth that could silently drift. Removed — callers
# import from settings.


def dosya_adi(ilce: str) -> str:
    return ILCE_DOSYA_ADI.get(ilce, ilce.lower())


def get_mahalle_path(ilce: str, data_dir: str = MAH_DIR_STR) -> Path | None:
    base = Path(data_dir)
    norm = dosya_adi(ilce)
    for candidate in [
        base / f"{norm}.geojson",
        base / f"{ilce.lower()}.geojson",
    ]:
        if candidate.exists():
            return candidate
    return None


def load_mahalleleri(
    ilce: str,
    data_dir: str = MAH_DIR_STR,
) -> gpd.GeoDataFrame:
    """
    İlçeye ait mahalle sınırlarını yerel GeoJSON'dan yükler.

    Dönen GeoDataFrame sütunları:
        - neighbourhood_name : mahalle adı (spatial_service uyumlu)
        - ilce               : ilçe adı
        - geometry           : Polygon / MultiPolygon

    Problem: Bazı ilçelerin GeoJSON'larında mahalle adı düz
    properties.name yerine iç içe properties.tags.name yapısında
    geliyor (Üsküdar, Beykoz, Beşiktaş vb.). gpd.read_file() bu
    iç içe yapıyı düzleştiremiyor → "1. Mahalle", "4. Mahalle" gibi
    sahte adlar üretiliyor.

    Çözüm: json.load() ile saf okuma → her feature'da tags.name
    önce aranır, yoksa name alanına düşülür.
    """
    path = get_mahalle_path(ilce, data_dir)

    if path is None:
        log.warning(f"{ilce}: mahalle dosyası bulunamadı — "
                    f"beklenen: {data_dir}/{dosya_adi(ilce)}.geojson")
        return gpd.GeoDataFrame(
            columns=["neighbourhood_name", "ilce", "geometry"],
            geometry="geometry",
            crs=WGS84,
        )

    # ── 1. Saf JSON olarak oku, iç içe tags.name'i düzleştir ────────────────
    # gpd.read_file() yerine json.load() kullanıyoruz çünkü bazı ilçelerde
    # mahalle adı properties.tags.name içinde geliyor, üst seviye name yok.
    with open(path, encoding="utf-8") as f:
        geo_data = json.load(f)

    for feature in geo_data.get("features", []):
        props = feature.get("properties", {})
        if props is None:
            props = {}
            feature["properties"] = props

        # Öncelik 1: properties.tags.name (Üsküdar vb. iç içe yapı)
        tags = props.get("tags")
        if isinstance(tags, dict) and tags.get("name"):
            props["mahalle_adi_kesin"] = tags["name"]
        # Öncelik 2: properties.name (Kadıköy vb. düz yapı)
        elif props.get("name"):
            props["mahalle_adi_kesin"] = props["name"]
        # Öncelik 3: properties.name:tr
        elif props.get("name:tr"):
            props["mahalle_adi_kesin"] = props["name:tr"]
        # Öncelik 4: properties.local_name
        elif props.get("local_name"):
            props["mahalle_adi_kesin"] = props["local_name"]
        else:
            props["mahalle_adi_kesin"] = ""   # sonra düzeltilecek

    # ── 2. Düzleştirilmiş veriden GeoDataFrame oluştur ───────────────────────
    gdf = gpd.GeoDataFrame.from_features(geo_data["features"])

    # CRS düzelt
    if gdf.crs is None:
        gdf = gdf.set_crs(WGS84)
    else:
        gdf = gdf.to_crs(WGS84)

    # ── 3. Geometri temizle ───────────────────────────────────────────────────
    # DÜZELTME: Önce polygon filtresi, sonra buffer(0).
    # Point.buffer(0) → boş geometri üretir; eski sırada label node'ları
    # "geçerli ama boş" hale geldiği için is_empty maskesi onları düşürüyordu —
    # çalışıyordu ama fragile. Şimdi sadece polygon'a buffer(0) uygulanıyor.
    warnings.filterwarnings("ignore", "GeoSeries.notna", UserWarning)
    gdf = gdf[gdf.geometry.notna()].copy()

    # Sadece poligon geometrileri al (Point label node'ları at)
    gdf = gdf[
        gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    ].copy()

    # Polygon'lara buffer(0): invalid ring vb. düzeltir
    gdf["geometry"] = gdf.geometry.buffer(0)
    gdf = gdf[~gdf.geometry.is_empty].copy()

    if gdf.empty:
        log.warning(f"{ilce}: poligon geometrisi bulunamadı")
        return gpd.GeoDataFrame(
            columns=["neighbourhood_name", "ilce", "geometry"],
            geometry="geometry",
            crs=WGS84,
        )

    # MultiIndex temizle
    if isinstance(gdf.index, pd.MultiIndex):
        gdf = gdf.reset_index()

    # ── 4. Mahalle adı ataması ────────────────────────────────────────────────
    if "mahalle_adi_kesin" in gdf.columns:
        gdf["neighbourhood_name"] = gdf["mahalle_adi_kesin"].astype(str).str.strip()
    else:
        gdf["neighbourhood_name"] = (
            ilce + " Mah. " + (pd.RangeIndex(len(gdf)) + 1).astype(str)
        )

    # Boş isimleri düzelt
    bos_mask = gdf["neighbourhood_name"].isin(["", "nan", "None"])
    if bos_mask.any():
        sayac = bos_mask.cumsum()
        gdf.loc[bos_mask, "neighbourhood_name"] = (
            ilce + " Mah. " + sayac[bos_mask].astype(str)
        )

    gdf["ilce"] = ilce

    result = gdf[["neighbourhood_name", "ilce", "geometry"]].copy()
    result = result.reset_index(drop=True)

    # Gerçek mahalle adı olan ve olmayan kayıt sayısını raporla
    gercek   = (~bos_mask).sum() if bos_mask.any() else len(result)
    isimsiz  = len(result) - gercek
    log.info(f"{ilce}: {len(result)} mahalle yüklendi "
             f"({gercek} gerçek ad{f', {isimsiz} isimsiz' if isimsiz else ''}) ← {path.name}")
    return result


@lru_cache(maxsize=8)
def _list_available_cached(data_dir: str) -> tuple[str, ...]:
    """
    Disk taraması cache'lenmiş hâli. Streamlit her widget tıklamasında
    sidebar'daki "available districts" göstergesini yeniden çiziyordu →
    her seferinde glob taraması. Disk içeriği nadiren değiştiği için
    process-local cache yeterli; yeni geojson eklendiyse Streamlit'i
    yeniden başlatmak gerekir (yine de günde 1-2 kez olur).
    """
    base = Path(data_dir)
    if not base.exists():
        return tuple()

    dosya_adlari = {f.stem for f in base.glob("*.geojson")}
    ters_map = {v: k for k, v in ILCE_DOSYA_ADI.items()}

    return tuple(sorted(
        ilce for stem in dosya_adlari
        if (ilce := ters_map.get(stem)) is not None
    ))


def list_available(data_dir: str = MAH_DIR_STR) -> list[str]:
    """İndirilmiş mahalle verisi olan ilçe adlarını döner (cached)."""
    return list(_list_available_cached(data_dir))


def clear_available_cache() -> None:
    """Yeni .geojson eklendiyse manuel cache temizleme."""
    _list_available_cached.cache_clear()


def get_overpass_query(ilce: str) -> str:
    """
    Belirtilen ilçe için Overpass **Turbo** (overpass-turbo.eu) sorgusu döner.

    Mevcut `data/mahalleleri/*.geojson` dosyaları bu sorgunun
    "Dışa Aktar → GeoJSON" çıktısıyla aynı yapıda. Mahalle sınırları
    Türkiye OSM'inde admin_level=8 olarak işaretli (deneyle doğrulandı).

    Not: `{{geocodeArea:...}}` bir Turbo makrosudur; doğrudan Overpass
    API'ye gönderilemez. Otomatik indirme için bkz.
    `src.services.overpass_downloader.build_query()`.
    """
    return f"""[out:json][timeout:90];

{{{{geocodeArea:{ilce}, İstanbul, Türkiye}}}}->.searchArea;

(
  relation["boundary"="administrative"]["admin_level"="8"](area.searchArea);
  way["boundary"="administrative"]["admin_level"="8"](area.searchArea);
);

out body;
>;
out skel qt;"""
