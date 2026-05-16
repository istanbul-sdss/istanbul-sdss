"""
src/services/osm_service.py

Düzeltmeler (v2 — istanbul):
- ensure_wgs84 / safe_buffer_zero: spatial_service'den import ediliyor (duplikasyon giderildi)
- print("[DEBUG]") → log.debug() — merkezi logger
- f-string formatı düzeltildi: log.debug("... {place_name}") → log.debug(f"... {place_name}")
- Tüm fonksiyon gövdeleri korundu (önceki versiyonda stub bırakılmıştı → NoneType hatası)
"""

from __future__ import annotations

import time
from typing import Any

import geopandas as gpd
import osmnx as ox
import pandas as pd

# osmnx 2.x "query succeeded with zero results" istisnası.
# Bunu mirror-retry döngüsünden çıkarıp boş GDF döndürmek gerekiyor;
# aksi halde her "bulunamayan" tag için 3+ mirror × 60-90 sn ceza yaşanıyor.
try:
    from osmnx._errors import InsufficientResponseError  # osmnx 2.x
except ImportError:
    try:
        from osmnx.utils import EmptyOverpassResponse as InsufficientResponseError  # osmnx 1.x
    except ImportError:
        class InsufficientResponseError(Exception):
            """Fallback — gerçek istisna yoksa asla raise olmayan sentinel."""
            pass

from src.config.settings import CACHE_DIR
from src.config.tag_rules import get_query_tags, get_rule
from src.logger import get_logger
from src.services.spatial_service import ensure_wgs84, safe_buffer_zero

log = get_logger(__name__)


# ==========================================================
# OSMNX SETTINGS
# ==========================================================

ox.settings.use_cache           = True
ox.settings.cache_folder        = str(CACHE_DIR)
ox.settings.log_console         = False   # Streamlit'te log kalabalığı önler

# ── osmnx 1.x / 2.x uyumluluk ───────────────────────────────────────────────
# osmnx 2.0 ile `timeout` → `requests_timeout`, `overpass_rate_limit` ise kaldırıldı.
# Timeout: büyük ilçelerde building=True gibi geniş sorgular 60s'i aşabilir
# (Esenyurt, Bağcılar vb.) — 180s güvenli üst sınır.
if hasattr(ox.settings, "requests_timeout"):
    ox.settings.requests_timeout = 180
else:  # osmnx < 2.0
    ox.settings.timeout = 180

# KRİTİK — osmnx 2.x'te default True. Aktifken her sorgudan önce
# `/api/status` polling + kibar bekleme yapıyor; küçük sorgularda bile
# 60-180 saniye gecikme yaratıyor. Single-user araç için devre dışı.
if hasattr(ox.settings, "overpass_rate_limit"):
    ox.settings.overpass_rate_limit = False


# osmnx 2.x artık `overpass_url` ayarına `/interpreter` suffix'ini kendisi ekliyor.
# osmnx 1.x ise tam URL bekliyordu. İki sürümde de çalışması için temel URL'leri
# base (suffix'siz) tutuyor, gerektiğinde aşağıda `_overpass_endpoint()` ile ayarlıyoruz.
# Overpass mirror listesi:
#   1. overpass-api.de          — resmi ana sunucu (FOSSGIS)
#   2. lz4.overpass-api.de      — ana sunucunun yük dengelenmiş kopyası
#   3. overpass.kumi.systems    — community mirror (son yedek)
# NOT: Overpass altyapısı zaman zaman toplu 504 Gateway Timeout dönüyor.
# osmnx 504 alınca internal retry yaptığı için toplam sorgu süresi 5-10 dk'ya
# kadar uzayabiliyor. Bu durumda https://overpass-api.de/api/status adresini
# kontrol edin (running queries + slot durumu). Geçici outage'ler 1-2 saat
# içinde düzeliyor — kod değişikliği gerekmiyor.
# osm.ch denenmemeli: global değil, sadece İsviçre verisi barındırıyor.
_OVERPASS_BASES = [
    "https://overpass-api.de/api",
    "https://lz4.overpass-api.de/api",
    "https://overpass.kumi.systems/api",
]

# osmnx 2.x göstergesi: settings.requests_timeout mevcutsa 2.x, değilse 1.x
_OSMNX_V2 = hasattr(ox.settings, "requests_timeout")


def _overpass_endpoint(base: str) -> str:
    """osmnx sürümüne göre doğru Overpass URL'sini üretir."""
    return base if _OSMNX_V2 else f"{base}/interpreter"


OVERPASS_URLS = [_overpass_endpoint(b) for b in _OVERPASS_BASES]

EMPTY_GDF = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")


# ── Hata sınıfları (P2.2) ────────────────────────────────────────────────────
# Audit bulgusu: Önceden Overpass network hatası ile "0 kayıt" sonucu aynı
# sessiz boş GDF ile temsil ediliyordu → DNS/SSL/timeout outage'ında kullanıcı
# "bu ilçede veri yok" sanıyordu. Artık ayrım explicit:
#   • OverpassNetworkError → tüm endpoint'ler başarısız (gerçek hata, raise)
#   • Boş GeoDataFrame      → sorgu başarılı, gerçekten 0 kayıt (normal sonuç)

class OverpassNetworkError(RuntimeError):
    """Overpass endpoint'lerinin tümüyle erişilememesi (ağ/dns/ssl/timeout)."""
    pass


def fetch_boundary(place_name: str) -> gpd.GeoDataFrame:
    log.debug(f"fetch_boundary başladı: {place_name}")
    start = time.time()
    gdf = ox.geocode_to_gdf(place_name).copy()
    gdf = ensure_wgs84(gdf)
    gdf = safe_buffer_zero(gdf)
    if gdf.empty:
        raise ValueError(f"Sınır bulunamadı: {place_name}")
    log.debug(f"fetch_boundary bitti: count={len(gdf)} süre={time.time()-start:.2f}s")
    return gdf


def get_boundary_geometry(boundary_gdf: gpd.GeoDataFrame):
    if boundary_gdf.empty:
        raise ValueError("Boundary GeoDataFrame boş")
    return ensure_wgs84(boundary_gdf).geometry.iloc[0]


def fetch_features_from_polygon(polygon, tags: dict[str, Any]) -> gpd.GeoDataFrame:
    last_error = None
    for overpass_url in OVERPASS_URLS:
        try:
            log.debug(f"OSM sorgusu başladı. endpoint={overpass_url} tags={tags}")
            ox.settings.overpass_url = overpass_url
            start = time.time()
            gdf = ox.features_from_polygon(polygon, tags=tags).copy()
            log.debug(f"OSM sorgusu bitti. endpoint={overpass_url} süre={time.time()-start:.2f}s kayıt={len(gdf)}")
            if gdf.empty:
                return EMPTY_GDF.copy()
            return ensure_wgs84(gdf)
        except InsufficientResponseError:
            # Sorgu başarılı, sadece eşleşen kayıt yok — bu bir hata değil.
            # Mirror-retry yapmadan boş GDF dönüyoruz (ilçede bu tag yok).
            log.debug(f"OSM sorgusu: 0 kayıt ({tags}) endpoint={overpass_url} süre={time.time()-start:.2f}s")
            return EMPTY_GDF.copy()
        except Exception as exc:
            last_error = exc
            log.warning(f"Overpass endpoint başarısız: {overpass_url} → {exc}")
    # P2.2: explicit network exception sınıfı — upstream "0 kayıt"tan ayırabilsin.
    raise OverpassNetworkError(
        f"Tüm Overpass endpoint'leri başarısız oldu: {last_error}"
    ) from last_error


def filter_by_geometry_types(gdf: gpd.GeoDataFrame, geometry_expected: list[str] | None = None) -> gpd.GeoDataFrame:
    if gdf.empty or not geometry_expected:
        return gdf.copy()
    return gdf[gdf.geometry.type.isin(geometry_expected)].copy()


def standardize_osm_columns(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    result = gdf.copy()
    rename_map = {"Building": "building", "Name": "name"}
    existing_map = {k: v for k, v in rename_map.items() if k in result.columns}
    if existing_map:
        result = result.rename(columns=existing_map)
    return result


def add_element_and_id_columns(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    result = gdf.copy()
    if result.empty:
        if "element" not in result.columns:
            result["element"] = pd.Series(dtype="object")
        if "id" not in result.columns:
            result["id"] = pd.Series(dtype="object")
        return result
    if "element" in result.columns and "id" in result.columns:
        return result
    if isinstance(result.index, pd.MultiIndex) and len(result.index.levels) >= 2:
        result = result.reset_index()
        cols = list(result.columns)
        if "element" not in cols and len(cols) >= 1:
            result = result.rename(columns={cols[0]: "element"})
        if "id" not in result.columns:
            for candidate in ["osmid", "id"]:
                if candidate in result.columns:
                    result = result.rename(columns={candidate: "id"})
                    break
            if "id" not in result.columns and len(result.columns) >= 2:
                second_col = result.columns[1]
                if second_col != "element":
                    result = result.rename(columns={second_col: "id"})
        return result
    result = result.reset_index(drop=False)
    if "element" not in result.columns:
        result["element"] = None
    if "id" not in result.columns:
        if "osmid" in result.columns:
            result = result.rename(columns={"osmid": "id"})
        elif "index" in result.columns:
            result = result.rename(columns={"index": "id"})
        else:
            result["id"] = None
    return result


def drop_duplicate_features(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    result = gdf.copy()
    if result.empty:
        return result
    result = add_element_and_id_columns(result)
    if {"element", "id"}.issubset(result.columns):
        result = result.drop_duplicates(subset=["element", "id"]).copy()
    else:
        result = result.drop_duplicates().copy()
    return result.reset_index(drop=True)


def fetch_union_features_within_boundary(
    boundary_gdf: gpd.GeoDataFrame,
    query_tags_list: list[dict[str, Any]],
    geometry_expected: list[str] | None = None,
) -> gpd.GeoDataFrame:
    """
    Union sorgusu: query_tags_list'teki her tag için ayrı sorgu, sonuç birleşim.

    Hata semantiği (P2.2):
      • Tüm tag sorguları OverpassNetworkError ile düşerse → raise
        (kullanıcı outage'i "veri yok" sanmasın).
      • Bazıları network hatası, bazıları başarılı → devam, ama dönen GDF
        `attrs["partial_failure"]=True` ve `attrs["failed_tags"]=[...]` ile
        işaretlenir; pipeline log'u + UI bunu kullanıcıya gösterebilir.
      • Tüm sorgular başarılı, sadece bazıları/hepsi 0 kayıt → boş/dolu GDF
        normal döner (gerçekten "veri yok" senaryosu).
    """
    if not query_tags_list:
        return EMPTY_GDF.copy()
    polygon = get_boundary_geometry(boundary_gdf)
    chunks: list[gpd.GeoDataFrame] = []
    network_failed_tags: list[dict[str, Any]] = []
    other_failed_tags:   list[dict[str, Any]] = []
    successful_count = 0   # "0 kayıt" da başarı sayılır (sorgu cevap aldı)
    for tags in query_tags_list:
        try:
            log.debug(f"union sorgulanıyor: {tags}")
            chunk = fetch_features_from_polygon(polygon, tags)
            chunk = standardize_osm_columns(chunk)
            chunk = filter_by_geometry_types(chunk, geometry_expected)
            successful_count += 1
            if not chunk.empty:
                log.debug(f"union parça eklendi: {tags} count={len(chunk)}")
                chunks.append(chunk)
            else:
                log.debug(f"union boş döndü: {tags}")
        except OverpassNetworkError as exc:
            network_failed_tags.append(tags)
            log.warning(f"OSM network hatası: tags={tags} → {exc}")
        except Exception as exc:
            other_failed_tags.append(tags)
            log.warning(f"OSM sorgu (veri/parsing) başarısız: tags={tags} → {exc}")

    # Hiçbir sorgu yanıt almadıysa AND network hatası vardıysa → açık raise.
    # Sadece "0 kayıt" senaryosu (hiç hata yok, hepsi boş) raise etmez.
    if successful_count == 0 and network_failed_tags:
        raise OverpassNetworkError(
            f"Tüm {len(network_failed_tags)} sorgu Overpass network hatasıyla "
            f"düştü; bu sonuç 'veri yok' DEĞİL, kaynak erişilemiyor. "
            f"İnternet bağlantısı / VPN / Overpass status kontrol edin."
        )

    if not chunks:
        # Tüm sorgular başarılı ama 0 kayıt → gerçekten veri yok
        result = EMPTY_GDF.copy()
    else:
        merged = pd.concat(chunks, ignore_index=False)
        merged = gpd.GeoDataFrame(merged, geometry="geometry", crs="EPSG:4326")
        merged = standardize_osm_columns(merged)
        merged = add_element_and_id_columns(merged)
        merged = drop_duplicate_features(merged)
        log.debug(f"union toplam kayıt: {len(merged)}")
        result = merged

    # Kısmi hata varsa metadata olarak işaretle (caller log'a/UI'ya yansıtabilir)
    if network_failed_tags or other_failed_tags:
        result.attrs["partial_failure"] = True
        result.attrs["failed_tags"] = network_failed_tags + other_failed_tags
        result.attrs["network_failed_count"] = len(network_failed_tags)
        log.warning(
            f"Kısmi başarısızlık: {len(network_failed_tags)} network + "
            f"{len(other_failed_tags)} diğer hata; {len(chunks)} sorgu başarılı. "
            f"Sonuç eksik olabilir — partial_failure=True işaretlendi."
        )
    return result


def fetch_rule_based_features(place_name: str, rule_code: str) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    rule = get_rule(rule_code)
    boundary = fetch_boundary(place_name)
    query_tags = get_query_tags(rule_code)
    geometry_expected = rule.get("geometry_expected", None)
    log.debug(f"rule bazlı çekim başladı: rule_code={rule_code} query_tags={query_tags}")
    features = fetch_union_features_within_boundary(
        boundary_gdf=boundary, query_tags_list=query_tags, geometry_expected=geometry_expected,
    )
    log.debug(f"rule bazlı çekim bitti: rule_code={rule_code} count={len(features)}")
    return boundary, features


def fetch_rule_based_features_with_boundary(boundary_gdf: gpd.GeoDataFrame, rule_code: str) -> gpd.GeoDataFrame:
    rule = get_rule(rule_code)
    query_tags = get_query_tags(rule_code)
    geometry_expected = rule.get("geometry_expected", None)
    log.debug(f"hazır boundary ile çekim başladı: rule_code={rule_code}")
    features = fetch_union_features_within_boundary(
        boundary_gdf=boundary_gdf, query_tags_list=query_tags, geometry_expected=geometry_expected,
    )
    log.debug(f"hazır boundary ile çekim bitti: rule_code={rule_code} count={len(features)}")
    return features


def filter_features_inside_boundary(
    boundary_gdf: gpd.GeoDataFrame,
    features_gdf: gpd.GeoDataFrame,
    predicate: str = "intersects",
) -> gpd.GeoDataFrame:
    if features_gdf.empty:
        return features_gdf.copy()
    boundary_geom = get_boundary_geometry(boundary_gdf)
    features = ensure_wgs84(features_gdf).copy()
    if predicate == "within":
        mask = features.geometry.within(boundary_geom)
    else:
        mask = features.geometry.intersects(boundary_geom)
    return features.loc[mask].copy().reset_index(drop=True)


def fetch_raw_buildings(place_name: str) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    boundary = fetch_boundary(place_name)
    features = fetch_union_features_within_boundary(
        boundary_gdf=boundary,
        query_tags_list=[{"building": True}],
        geometry_expected=["Polygon", "MultiPolygon"],
    )
    return boundary, features


def fetch_raw_buildings_with_boundary(boundary_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return fetch_union_features_within_boundary(
        boundary_gdf=boundary_gdf,
        query_tags_list=[{"building": True}],
        geometry_expected=["Polygon", "MultiPolygon"],
    )
