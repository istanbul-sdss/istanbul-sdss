"""
Kategori bazlı export kolon konfigürasyonları.

Neden footprint_m2 her family'de var?
--------------------------------------
OSM'de bir hastane hem Point (amenity=hospital) hem de Polygon
(building=hospital) olabilir. Poligon geldiğinde spatial_service
footprint_m2'yi hesaplar, ama eski POI şemasında bu sütun yoktu
→ alan bilgisi kesiliyordu.

Çözüm: footprint_m2 + building:levels + height tüm family'lere eklendi.
_to_clean_dataframe zaten "available = [c for c in desired if c in g.columns]"
kullanıyor → sütun GeoDataFrame'de yoksa otomatik atlanıyor, zarar yok.
"""

# ── ORTAK TEMEL SÜTUNLAR ──────────────────────────────────────────────────────
COMMON_OUTPUT_COLUMNS = [
    "element",
    "id",
    "name",
    "category_group",
    "subcategory",
    "label_tr",
    "rule_code",
    "confidence",
    "reason",
    "latitude",
    "longitude",
    "neighbourhood",
    # boundary_status: "ilçe_içi" / "sınır_üstü" / "ilçe_dışı"
    # assign_neighbourhoods tarafından üretilir; analist Excel/CSV'de
    # ilçe sınırı dışındaki kayıtları (Overpass'ın komşu ilçeden sızdırdığı
    # kayıtlar) görüp filtreleyebilir.
    "boundary_status",
]

# ── MEKÂNSAL ZENGİNLEŞTİRME SÜTUNLARI ───────────────────────────────────────
# Poligon gelebilecek her kategori için (hastane, okul, park vb.)
SPATIAL_COLUMNS = [
    "building:levels",   # kat sayısı
    "height",            # yükseklik (m)
    "footprint_m2",      # ayak izi alanı — spatial_service tarafından hesaplanır
    "area_source",       # provenance: measured / polygon_overlay / capacity_derived / point_default
]

# ── AİLE BAZLI SÜTUN LİSTELERİ ───────────────────────────────────────────────

BUILDING_OUTPUT_COLUMNS = COMMON_OUTPUT_COLUMNS + [
    "building",
    "amenity",
    "shop",
    "office",
    "tourism",
    "religion",
    "healthcare",
    "public_transport",
    "railway",
] + SPATIAL_COLUMNS

POI_OUTPUT_COLUMNS = COMMON_OUTPUT_COLUMNS + [
    "amenity",
    "shop",
    "office",
    "tourism",
    "religion",
    "healthcare",
    "public_transport",
    "railway",
] + SPATIAL_COLUMNS  # ← Hastane/okul/park poligon gelince alan gösterilsin

LANDUSE_OUTPUT_COLUMNS = COMMON_OUTPUT_COLUMNS + [
    "landuse",
    "leisure",
    "natural",
] + SPATIAL_COLUMNS  # ← Park, orman vb. için alan önemli

NETWORK_OUTPUT_COLUMNS = COMMON_OUTPUT_COLUMNS + [
    "highway",
    "railway",
    "bridge",
]

# ── AİLE → SÜTUN EŞLEMESİ ────────────────────────────────────────────────────
EXPORT_COLUMNS_BY_FAMILY = {
    "building":       BUILDING_OUTPUT_COLUMNS,
    "poi":            POI_OUTPUT_COLUMNS,
    "transport":      POI_OUTPUT_COLUMNS,
    "culture":        POI_OUTPUT_COLUMNS,
    "infrastructure": POI_OUTPUT_COLUMNS,
    "landuse":        LANDUSE_OUTPUT_COLUMNS,
    "network":        NETWORK_OUTPUT_COLUMNS,
    "admin":          COMMON_OUTPUT_COLUMNS,
    "derived":        BUILDING_OUTPUT_COLUMNS,
    "generic":        COMMON_OUTPUT_COLUMNS,
}


def get_export_columns(export_family: str) -> list[str]:
    return EXPORT_COLUMNS_BY_FAMILY.get(export_family, COMMON_OUTPUT_COLUMNS)
