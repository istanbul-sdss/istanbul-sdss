"""
Admin level (OSM) konfigürasyonu.

Bu dosya:
- OSM admin_level değerlerini merkezi olarak tutar
- UI dropdown üretimi için kullanılır
- Backend query generation için kullanılır

Referans:
- admin_level=4 → İl
- admin_level=6 → İlçe
- admin_level=8 → Mahalle
"""


# ==========================================================
# 🔹 ANA ADMIN LEVEL TANIMLARI
# ==========================================================

ADMIN_LEVELS = {
    "province": {
        "label_tr": "İl Sınırları",
        "label_en": "Province Boundaries",
        "admin_level": "4",
        "osm_tags": {"boundary": "administrative", "admin_level": "4"},
    },
    "district": {
        "label_tr": "İlçe Sınırları",
        "label_en": "District Boundaries",
        "admin_level": "6",
        "osm_tags": {"boundary": "administrative", "admin_level": "6"},
    },
    "neighbourhood": {
        "label_tr": "Mahalle Sınırları",
        "label_en": "Neighbourhood Boundaries",
        "admin_level": "8",
        "osm_tags": {"boundary": "administrative", "admin_level": "8"},
    },
}


# ==========================================================
# 🔹 UI DROPDOWN İÇİN FORMATLANMIŞ LİSTE
# ==========================================================

def get_admin_level_options_tr() -> list[dict]:
    """
    UI dropdown için Türkçe seçenek listesi üretir.

    Örnek çıktı:
    [
        {"key": "neighbourhood", "label": "Mahalle Sınırları (Level 8)"},
        {"key": "district", "label": "İlçe Sınırları (Level 6)"},
        {"key": "province", "label": "İl Sınırları (Level 4)"},
    ]
    """
    return [
        {
            "key": key,
            "label": f"{value['label_tr']} (Level {value['admin_level']})",
        }
        for key, value in ADMIN_LEVELS.items()
    ]


# ==========================================================
# 🔹 BACKEND QUERY YARDIMCILARI
# ==========================================================

def get_admin_level_tags(level_key: str) -> dict:
    """
    Verilen admin level key için OSM tag'lerini döner.

    Örnek:
    get_admin_level_tags("neighbourhood")
    → {"boundary": "administrative", "admin_level": "8"}
    """
    if level_key not in ADMIN_LEVELS:
        raise ValueError(f"Geçersiz admin level: {level_key}")

    return ADMIN_LEVELS[level_key]["osm_tags"]


def get_admin_level_number(level_key: str) -> str:
    """
    Sadece admin_level sayısını döner.
    """
    if level_key not in ADMIN_LEVELS:
        raise ValueError(f"Geçersiz admin level: {level_key}")

    return ADMIN_LEVELS[level_key]["admin_level"]


# ==========================================================
# 🔹 VALIDATION
# ==========================================================

def is_valid_admin_level(level_key: str) -> bool:
    """
    Geçerli admin level mı kontrol eder.
    """
    return level_key in ADMIN_LEVELS
