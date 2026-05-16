"""
src/services/overpass_downloader.py

Overpass API'den (overpass-api.de/api/interpreter) bir İstanbul ilçesinin
mahalle sınırlarını indirir, Overpass Turbo'nun "Dışa Aktar → GeoJSON"
çıktısıyla aynı yapıda `data/mahalleleri/{dosya_adi}.geojson` dosyasına
yazar.

Sorgu formatı, kullanıcının elle indirmek için kullandığı:
    {{geocodeArea:Beşiktaş, İstanbul, Türkiye}}->.searchArea;
    relation/way["boundary"="administrative"]["admin_level"="8"](area.searchArea);
sorgusunun API-uyumlu eşdeğeridir. {{geocodeArea}} bir Overpass Turbo
makrosu olduğu için API doğrudan kabul etmez; bunun yerine "İstanbul"
(admin_level=4) içinde adı eşleşen ilçe (admin_level=6) area olarak
çözülür.

osm2geojson çıktısı (properties.tags.name vb.) mevcut
neighbourhood_loader.load_mahalleleri() bekleyişine birebir uyumludur.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import osm2geojson
import requests

from src.config.settings import MAH_DIR
from src.logger import get_logger
from src.services.neighbourhood_loader import (
    ILCE_DOSYA_ADI,
    clear_available_cache,
    dosya_adi,
)

log = get_logger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DEFAULT_TIMEOUT = 90
HTTP_TIMEOUT = DEFAULT_TIMEOUT + 30  # network read budget > Overpass query budget


class OverpassError(RuntimeError):
    """Overpass API çağrısı veya yanıtının dönüşümünde oluşan hata."""


def build_query(ilce: str, *, timeout: int = DEFAULT_TIMEOUT) -> str:
    """
    İlçe için API-uyumlu Overpass sorgusu üretir (admin_level=8 mahalleler).

    Aynı isimde başka bir Beşiktaş/Şile vb. olmaması için "İstanbul"
    (admin_level=4) içinde scope'lanır.
    """
    return (
        f"[out:json][timeout:{timeout}];\n"
        f'area["name"="İstanbul"]["admin_level"="4"]->.il;\n'
        f'area["name"="{ilce}"]["admin_level"="6"](area.il)->.searchArea;\n'
        f"(\n"
        f'  relation["boundary"="administrative"]["admin_level"="8"](area.searchArea);\n'
        f'  way["boundary"="administrative"]["admin_level"="8"](area.searchArea);\n'
        f");\n"
        f"out body;\n"
        f">;\n"
        f"out skel qt;"
    )


def fetch_overpass(query: str, *, timeout: int = HTTP_TIMEOUT) -> dict:
    """Overpass API'ye POST atar, JSON yanıtı döndürür."""
    try:
        resp = requests.post(
            OVERPASS_URL,
            data={"data": query},
            timeout=timeout,
            headers={"User-Agent": "istanbul-sdss/mahalle-updater"},
        )
    except requests.Timeout as e:
        raise OverpassError(f"Overpass API zaman aşımı ({timeout}s): {e}") from e
    except requests.RequestException as e:
        raise OverpassError(f"Overpass API ağ hatası: {e}") from e

    if resp.status_code == 429:
        raise OverpassError(
            "Overpass API hız sınırı (429). Lütfen birkaç dakika sonra tekrar deneyin."
        )
    if resp.status_code == 504:
        raise OverpassError(
            "Overpass API gateway zaman aşımı (504). Sorgu çok uzun sürdü."
        )
    if resp.status_code != 200:
        raise OverpassError(
            f"Overpass API hatası: HTTP {resp.status_code} — {resp.text[:200]}"
        )

    try:
        return resp.json()
    except ValueError as e:
        raise OverpassError(f"Geçersiz JSON yanıtı: {e}") from e


def to_geojson(osm_data: dict) -> dict:
    """OSM JSON → GeoJSON FeatureCollection (Overpass Turbo eşdeğeri)."""
    return osm2geojson.json2geojson(osm_data)


def _polygon_count(features: list[dict]) -> int:
    return sum(
        1
        for f in features
        if f.get("geometry", {}).get("type") in ("Polygon", "MultiPolygon")
    )


def save_geojson(
    ilce: str,
    geojson: dict,
    *,
    target_dir: Path | str = MAH_DIR,
    backup: bool = True,
) -> Path:
    """
    GeoJSON'u doğru dosya adıyla diske yazar; varsa eskisini `.bak.<ts>`
    olarak yedekler. Yedek, hata anında geri alınabilirlik içindir.
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{dosya_adi(ilce)}.geojson"

    if backup and target.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = target.with_name(f"{target.stem}.geojson.bak.{ts}")
        target.replace(bak)
        log.info(f"{ilce}: önceki dosya yedeklendi → {bak.name}")

    with open(target, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=4)

    return target


def update_district(
    ilce: str,
    *,
    target_dir: Path | str = MAH_DIR,
    backup: bool = True,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """
    Tek ilçe için tam akış: sorgu üret → API çağır → GeoJSON'a dönüştür → yaz.

    Dönen sözlük:
        ilce, path, feature_count, polygon_count
    """
    if ilce not in ILCE_DOSYA_ADI:
        raise OverpassError(f"Bilinmeyen ilçe: {ilce}")

    log.info(f"{ilce}: Overpass sorgusu gönderiliyor…")
    query = build_query(ilce, timeout=timeout)
    osm_data = fetch_overpass(query)
    geojson = to_geojson(osm_data)
    features = geojson.get("features", [])
    poly_n = _polygon_count(features)

    if poly_n == 0:
        raise OverpassError(
            f"{ilce}: poligon dönmedi — sorgu boş ya da admin_level eşleşmiyor."
        )

    path = save_geojson(ilce, geojson, target_dir=target_dir, backup=backup)
    clear_available_cache()  # disk değişti → list_available() yenilensin

    log.info(
        f"{ilce}: {len(features)} feature, {poly_n} poligon yazıldı → {path.name}"
    )
    return {
        "ilce": ilce,
        "path": str(path),
        "feature_count": len(features),
        "polygon_count": poly_n,
    }


def update_districts(
    ilceler: list[str],
    *,
    target_dir: Path | str = MAH_DIR,
    backup: bool = True,
    timeout: int = DEFAULT_TIMEOUT,
) -> Iterator[dict]:
    """
    Birden fazla ilçeyi sırayla günceller; her ilçe için sonuç sözlüğü
    (`update_district` çıktısı) veya hata sözlüğü (`{"ilce", "error"}`)
    yield eder. UI çağıran tarafta progress bar'ı bu yield'lere bağlar.
    """
    for ilce in ilceler:
        try:
            yield update_district(
                ilce, target_dir=target_dir, backup=backup, timeout=timeout
            )
        except OverpassError as e:
            log.error(f"{ilce}: {e}")
            yield {"ilce": ilce, "error": str(e)}


def file_status(ilce: str, *, target_dir: Path | str = MAH_DIR) -> dict:
    """Mevcut dosyanın varlık + son değişiklik tarihi + boyut bilgisi."""
    target = Path(target_dir) / f"{dosya_adi(ilce)}.geojson"
    if not target.exists():
        return {"ilce": ilce, "exists": False}
    stat = target.stat()
    return {
        "ilce": ilce,
        "exists": True,
        "path": str(target),
        "size_kb": round(stat.st_size / 1024, 1),
        "mtime": datetime.fromtimestamp(stat.st_mtime),
    }
