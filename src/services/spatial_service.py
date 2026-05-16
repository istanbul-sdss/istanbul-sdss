"""
src/services/spatial_service.py

Düzeltmeler:
1. assign_neighbourhoods: .values yerine index-safe join
2. validate_points_within_boundary: boundary.unary_union kullanıyor
3. add_lat_lon_from_point: null-safe (.apply yerine doğrudan)
4. clean_geometry: Point.buffer(0) boş geometri üretiyordu — sadece polygon'a uygula
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from src.config.settings import (
    AFAD_M2_PER_PERSON as _SETTINGS_AFAD_M2_PER_PERSON,
)
from src.logger import get_logger

log = get_logger(__name__)

WGS84        = "EPSG:4326"
UTM_ISTANBUL = "EPSG:32635"


# ── CRS HELPERS ──────────────────────────────────────────────────────────────

def ensure_wgs84(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf.copy()
    if gdf.crs is None:
        return gdf.set_crs(WGS84)
    return gdf.to_crs(WGS84)


def to_utm(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf.copy()
    return gdf.to_crs(UTM_ISTANBUL)


# ── GEOMETRY CLEANING ─────────────────────────────────────────────────────────

def clean_geometry(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    DÜZELTME: buffer(0) sadece Polygon/MultiPolygon'a uygulanıyor.
    Point.buffer(0) → boş geometri üretir → veri kaybolur.
    """
    result = gdf.copy()
    if result.empty:
        return result

    poly_mask = result.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if poly_mask.any():
        result.loc[poly_mask, "geometry"] = result.loc[poly_mask, "geometry"].buffer(0)

    result = result[result.geometry.notna()].copy()
    result = result[~result.geometry.is_empty].copy()
    return result


# ── REPRESENTATIVE POINT ──────────────────────────────────────────────────────

def add_representative_points(
    gdf: gpd.GeoDataFrame,
    col_name: str = "rep_point",
) -> gpd.GeoDataFrame:
    """Polygon içinde kesin kalan nokta üretir (centroid yerine daha güvenli)."""
    result = ensure_wgs84(gdf.copy())
    if result.empty:
        result[col_name] = pd.Series(dtype="object")
        return result

    utm          = to_utm(result)
    rep_utm      = utm.geometry.representative_point()
    rep_wgs      = gpd.GeoSeries(rep_utm, crs=UTM_ISTANBUL).to_crs(WGS84)
    result[col_name] = rep_wgs.values
    return result


# ── LAT / LON EXTRACTION ──────────────────────────────────────────────────────

def add_lat_lon_from_point(
    gdf: gpd.GeoDataFrame,
    point_col: str = "rep_point",
    lat_col: str = "latitude",
    lon_col: str = "longitude",
) -> gpd.GeoDataFrame:
    """
    DÜZELTME: None rep_point gelirse patlamasın diye null-safe apply.
    """
    result = gdf.copy()
    if result.empty:
        result[lat_col] = pd.Series(dtype="float")
        result[lon_col] = pd.Series(dtype="float")
        return result

    result[lat_col] = result[point_col].apply(
        lambda p: p.y if isinstance(p, Point) else None
    )
    result[lon_col] = result[point_col].apply(
        lambda p: p.x if isinstance(p, Point) else None
    )
    return result


# ── FOOTPRINT AREA ────────────────────────────────────────────────────────────

# AFAD toplanma alanı standardı: kişi başı 1.5 m²
# Tek kaynak: src/config/settings.py — modül seviyesinde alias bırakıyoruz
# çünkü `from src.services.spatial_service import AFAD_M2_PER_PERSON`
# çağrılarını kıracak başka modüller var.
AFAD_M2_PER_PERSON = _SETTINGS_AFAD_M2_PER_PERSON


def _coerce_capacity(value) -> float | None:
    """OSM `capacity` tag'ini sayıya çevirir. Boş/parse edilemezse None."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        num = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None


def add_footprint_area(
    gdf: gpd.GeoDataFrame,
    col_name: str = "footprint_m2",
    *,
    point_fallback: bool = True,
    source_col: str = "area_source",
    overlay_polygons: gpd.GeoDataFrame | None = None,
) -> gpd.GeoDataFrame:
    """
    Polygon/MultiPolygon için alanı UTM'de gerçekten hesaplar.

    Point/MultiPoint için iki kademeli GERÇEK/TÜREVSEL hesap
    (uydurma default YOK — kanıt yoksa alan boş bırakılır):

      1. **polygon_overlay**: Point, aynı fetch içindeki (veya
         `overlay_polygons`'ta verilen) bir poligonun içine düşüyorsa
         o poligonun alanını miras alır. Gerçek footprint.
         OSM'de "Ahmet Taner Kışlalı Parkı" gibi isimli Point'ler
         genelde aynı parkın poligonu üzerine yerleştirilmiş label
         node'lardır; bu adım onları yakalar.

      2. **capacity_derived**: Point'te `capacity` tag varsa, AFAD
         standardıyla (`capacity × 1.5 m²/kişi`) alan türetilir.

    Hiçbiri olmazsa `footprint_m2 = NaN` ve `area_source = ""` kalır.
    Downstream tüketiciler boş hücreyi açıkça "alan bilinmiyor" olarak
    görsün — sessiz bir 500 m² uydurma yapmıyoruz (reviewer bulgu #2).

    `source_col` provenance taşır — Excel'e kadar gider:
      • "measured"          → Polygon UTM ölçümü
      • "polygon_overlay"   → Point, poligon içinde → miras
      • "capacity_derived"  → Point + capacity → AFAD 1.5 m²/kişi
      • ""                  → Hesaplanamadı (izole Point, Line vs.)
    """
    result = gdf.copy()
    if result.empty:
        result[col_name] = pd.Series(dtype="float")
        result[source_col] = pd.Series(dtype="object")
        return result

    result[col_name] = None
    result[source_col] = ""

    # 1) Polygon/MultiPolygon: gerçek UTM alanı
    poly_mask = result.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if poly_mask.any():
        utm = to_utm(result[poly_mask])
        result.loc[poly_mask, col_name] = utm.geometry.area.values
        result.loc[poly_mask, source_col] = "measured"

    if not point_fallback:
        result[col_name] = pd.to_numeric(result[col_name], errors="coerce")
        return result

    point_mask = result.geometry.geom_type.isin(["Point", "MultiPoint"])
    if not point_mask.any():
        result[col_name] = pd.to_numeric(result[col_name], errors="coerce")
        return result

    # 2) polygon_overlay: aynı fetch içindeki (veya dışarıdan verilen) poligonlar
    if overlay_polygons is not None and not overlay_polygons.empty:
        poly_src = overlay_polygons.copy()
    else:
        poly_src = result.loc[poly_mask, ["geometry"]].copy()
        poly_src["__area_m2__"] = result.loc[poly_mask, col_name].values

    overlay_hits: dict = {}
    if not poly_src.empty:
        if "__area_m2__" not in poly_src.columns:
            poly_utm_tmp = to_utm(poly_src)
            poly_src["__area_m2__"] = poly_utm_tmp.geometry.area.values

        # Deterministik tiebreak için stabil bir poligon kimliği üret. Aynı
        # alana sahip iki kapsayıcı varsa tutarlı sonuç almak gerekir
        # (regression: spatial index seed/sjoin batch sıralaması değişimleri
        # arasında Excel çıktısının değişmemesi). __poly_id__ poly_src'in
        # orijinal sırasını yansıtır.
        poly_src = poly_src.copy()
        poly_src["__poly_id__"] = range(len(poly_src))

        pts = result.loc[point_mask, ["geometry"]].copy()
        pts["__orig_idx__"] = pts.index

        try:
            joined = gpd.sjoin(
                pts,
                poly_src[["geometry", "__area_m2__", "__poly_id__"]],
                how="left",
                predicate="within",
            )
            if "__area_m2__" in joined.columns:
                valid = joined.dropna(subset=["__area_m2__"])
                if not valid.empty:
                    # Birden fazla poligonla eşleşirse EN KÜÇÜĞÜNÜ (en spesifik)
                    # al. Önceki davranış en büyüğü alıyordu — bir park label
                    # Point'i hem küçük park poligonu hem de daha büyük landuse
                    # / yeşil alan / ilçe sınırı içinde olabilir; en büyük
                    # seçilince Excel'e yüz binlerce m² yazılıyordu
                    # (kullanıcı bulgusu: "park alanları yanlış geliyor").
                    # En küçük overlay = gerçek footprint'e en yakın referans.
                    # Tiebreak: aynı alanlı iki poligon varsa __poly_id__
                    # (stabil orijinal sıra) deterministik karar.
                    best = (
                        valid
                        .sort_values(["__area_m2__", "__poly_id__"], ascending=[True, True])
                        .groupby("__orig_idx__", sort=False)
                        .head(1)
                    )
                    for _, row in best.iterrows():
                        overlay_hits[row["__orig_idx__"]] = float(row["__area_m2__"])
        except Exception as exc:  # pragma: no cover
            log.debug(f"polygon_overlay sjoin skipped: {exc}")

    # 3) Her Point için tier uygula — hiçbiri yoksa NaN/"" bırak
    has_capacity_col = "capacity" in result.columns
    for idx in result.index[point_mask]:
        if idx in overlay_hits:
            result.at[idx, col_name] = overlay_hits[idx]
            result.at[idx, source_col] = "polygon_overlay"
            continue

        raw_cap = result.at[idx, "capacity"] if has_capacity_col else None
        cap = _coerce_capacity(raw_cap)
        if cap is not None:
            result.at[idx, col_name] = cap * AFAD_M2_PER_PERSON
            result.at[idx, source_col] = "capacity_derived"
        # aksi halde dokunma: footprint_m2=None(NaN), area_source=""

    result[col_name] = pd.to_numeric(result[col_name], errors="coerce")
    return result


# ── NEIGHBOURHOOD ASSIGNMENT ──────────────────────────────────────────────────

def load_neighbourhoods(
    geojson_path: str,
    name_col: str = "name",
    district_col: str | None = None,
    district_name: str | None = None,
) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(geojson_path)
    gdf = ensure_wgs84(gdf)
    gdf = clean_geometry(gdf)

    if district_col and district_name:
        gdf = gdf[gdf[district_col] == district_name].copy()

    if name_col not in gdf.columns:
        raise ValueError(f"Mahalle isim kolonu bulunamadı: {name_col}")

    gdf = gdf.rename(columns={name_col: "neighbourhood_name"})
    return gdf


def assign_neighbourhoods(
    gdf: gpd.GeoDataFrame,
    neighbourhoods: gpd.GeoDataFrame,
    point_col: str = "rep_point",
) -> gpd.GeoDataFrame:
    """
    Mahalle atama — üç kademeli + provenance kolonu.

      1. **within**     → Point bir mahalle poligonunun strict iç bölgesinde.
                          `boundary_status = "ilçe_içi"`.
      2. **intersects** → within bulunmazsa: paylaşılan kenar üzerindeki Point'ler.
                          `boundary_status = "sınır_üstü"`.
      3. **nearest**    → o da boşsa: en yakın mahalle ile doldurulur AMA
                          `boundary_status = "ilçe_dışı"` olarak işaretlenir.
                          Bu kayıtlar muhtemelen komşu ilçelere ait
                          (Overpass'ın `area:` filtresi vs Nominatim boundary
                          farkı, polygon'un sınırı çapraz kesmesi gibi nedenlerle
                          gelir). Sessizce silmek yerine etiketliyoruz —
                          analist Excel'de görüp filtreleyebilir.

    `boundary_status` kolonu downstream export'larda Türkçe "Sınır Durumu"
    olarak görünür; karar destek raporunda hangi kayıtların gerçekten ilçe
    içi olduğu net görünsün.
    """
    result = gdf.copy()

    if result.empty or neighbourhoods.empty:
        result["neighbourhood"]   = pd.Series(dtype="object")
        result["boundary_status"] = pd.Series(dtype="object")
        return result

    points = gpd.GeoDataFrame(
        result.drop(columns="geometry"),
        geometry=result[point_col],
        crs=WGS84,
    )

    nbhd = neighbourhoods[["neighbourhood_name", "geometry"]]

    # provenance: hangi tier hangi index'te kazandı
    status = pd.Series("", index=points.index, dtype=object)

    # 1) within (strict interior)
    joined_within = gpd.sjoin(points, nbhd, how="left", predicate="within")
    joined_within = joined_within[~joined_within.index.duplicated(keep="first")]
    assigned = joined_within["neighbourhood_name"]
    status.loc[assigned.notna()] = "ilçe_içi"

    # 2) intersects (paylaşılan kenar) — sadece within boş olanlar için
    missing_mask = assigned.isna()
    if missing_mask.any():
        unresolved_pts = points[missing_mask]
        joined_inter = gpd.sjoin(unresolved_pts, nbhd, how="left", predicate="intersects")
        joined_inter = joined_inter[~joined_inter.index.duplicated(keep="first")]
        inter_assigned = joined_inter["neighbourhood_name"]
        # combine_first: object-dtype güvenli, pandas downcasting uyarısı yok
        assigned = assigned.combine_first(inter_assigned)
        # intersects'ten gelenler "sınır_üstü"
        status.loc[inter_assigned.notna() & (status == "")] = "sınır_üstü"

    # 3) nearest neighbour — UTM projeksiyonunda (geographic CRS sapması yok)
    missing_mask = assigned.isna()
    if missing_mask.any():
        unresolved_pts = points[missing_mask]
        try:
            pts_utm  = unresolved_pts.to_crs(UTM_ISTANBUL)
            nbhd_utm = nbhd.to_crs(UTM_ISTANBUL)
            joined_near = gpd.sjoin_nearest(
                pts_utm, nbhd_utm, how="left", distance_col="__nbhd_dist__"
            )
            joined_near = joined_near[~joined_near.index.duplicated(keep="first")]
            near_assigned = joined_near["neighbourhood_name"]
            n_recovered = int(near_assigned.notna().sum())
            if n_recovered > 0:
                log.warning(
                    f"assign_neighbourhoods: {n_recovered} kayıt ilçe sınırının "
                    f"DIŞINDA — en yakın mahalle ile dolduruldu ve "
                    f"boundary_status='ilçe_dışı' olarak işaretlendi. Bu kayıtlar "
                    f"muhtemelen komşu ilçelere ait; Excel'de 'Sınır Durumu' "
                    f"kolonundan filtrelenebilir."
                )
            assigned = assigned.combine_first(near_assigned)
            status.loc[near_assigned.notna() & (status == "")] = "ilçe_dışı"
        except Exception as exc:  # pragma: no cover
            log.debug(f"sjoin_nearest fallback skipped: {exc}")

    result["neighbourhood"]   = assigned
    result["boundary_status"] = status
    return result


# ── QUALITY CHECK ─────────────────────────────────────────────────────────────

def validate_points_within_boundary(
    gdf: gpd.GeoDataFrame,
    boundary_gdf: gpd.GeoDataFrame,
    point_col: str = "rep_point",
) -> dict:
    """
    DÜZELTME: boundary_gdf.geometry.iloc[0] yerine unary_union kullanılıyor.
    Multi-polygon boundary'lerde tek geometri varsayımı yanlış sonuç verirdi.
    """
    if gdf.empty:
        return {"total": 0, "outside_count": 0, "outside_ratio": 0.0}

    # DÜZELTME: unary_union → tüm boundary parçalarını birleştirir
    # shapely 2.0 / geopandas 1.0 uyumu: union_all() tercih edilir, eski sürümler için fallback
    _geom_series = boundary_gdf.to_crs(WGS84).geometry
    boundary_geom = (
        _geom_series.union_all()
        if hasattr(_geom_series, "union_all")
        else _geom_series.unary_union
    )

    valid_points = gdf[point_col].apply(lambda p: isinstance(p, Point))
    if not valid_points.any():
        return {"total": len(gdf), "outside_count": 0, "outside_ratio": 0.0}

    outside_mask  = ~gdf.loc[valid_points, point_col].within(boundary_geom)
    outside_count = int(outside_mask.sum())
    total         = len(gdf)

    return {
        "total":         total,
        "outside_count": outside_count,
        "outside_ratio": float(outside_count / total) if total > 0 else 0.0,
    }


# ── FULL ENRICHMENT PIPELINE ──────────────────────────────────────────────────

def enrich_with_spatial_features(
    gdf: gpd.GeoDataFrame,
    boundary_gdf: gpd.GeoDataFrame,
    neighbourhoods_gdf: gpd.GeoDataFrame | None = None,
) -> tuple[gpd.GeoDataFrame, dict]:
    result = gdf.copy()
    if result.empty:
        return result, {"total": 0}

    result = ensure_wgs84(result)
    result = clean_geometry(result)
    result = add_representative_points(result)
    result = add_lat_lon_from_point(result)
    result = add_footprint_area(result)

    if neighbourhoods_gdf is not None:
        result = assign_neighbourhoods(result, neighbourhoods_gdf)

    qc = validate_points_within_boundary(result, boundary_gdf)
    return result, qc


# ── UI YARDIMCI: lat/lon sütunlu DataFrame → GeoDataFrame ────────────────────

def df_latlon_to_geodataframe(
    df: pd.DataFrame,
    lat_col: str = "Enlem",
    lon_col: str = "Boylam",
    crs: str = WGS84,
) -> gpd.GeoDataFrame:
    """
    Enlem/Boylam sütunlu DataFrame'i GeoDataFrame'e dönüştürür.

    P3.3 düzeltmesi:
      • Önceden eksik kolonda `df.get(col, 0)` → scalar `0` → `pd.to_numeric`
        scalar döner → `.fillna()` AttributeError veriyordu.
      • Eksik kolon SESSİZCE 0 ile dolduruluyordu → tüm noktalar (0,0)
        Atlantic Ocean'da düşüyor. Karar destek için tehlikeli.
      • Artık eksik kolon → açık `ValueError`; geçersiz/eksik koordinatlı
        satırlar düşürülüp logda raporlanır.
    """
    if lat_col not in df.columns:
        raise ValueError(
            f"Enlem kolonu yok: '{lat_col}'. Mevcut kolonlar: {list(df.columns)}"
        )
    if lon_col not in df.columns:
        raise ValueError(
            f"Boylam kolonu yok: '{lon_col}'. Mevcut kolonlar: {list(df.columns)}"
        )

    df = df.copy()
    lat = pd.to_numeric(df[lat_col], errors="coerce")
    lon = pd.to_numeric(df[lon_col], errors="coerce")

    # Geçerli aralık: WGS84 (-90/90, -180/180). Aralık dışı veya NaN → düşür.
    in_range = (
        lat.between(-90.0, 90.0, inclusive="both")
        & lon.between(-180.0, 180.0, inclusive="both")
    )
    n_total   = len(df)
    n_invalid = int((~in_range).sum())
    if n_invalid > 0:
        log.warning(
            f"df_latlon_to_geodataframe: {n_invalid}/{n_total} kayıtta "
            f"geçersiz/eksik koordinat — düşürüldü (eskiden (0,0) atanıyordu)."
        )

    df = df.loc[in_range].copy()
    lat = lat.loc[in_range]
    lon = lon.loc[in_range]
    geometries = gpd.points_from_xy(lon, lat)
    return gpd.GeoDataFrame(df, geometry=geometries, crs=crs)


def safe_buffer_zero(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Polygon geometrileri buffer(0) ile normalize eder (invalid polygon fix).
    Point geometrilere uygulanmaz — Point.buffer(0) boş geometri üretir.
    clean_geometry ile aynı mantık; backward compat için ayrı tutuldu.
    """
    return clean_geometry(gdf)
