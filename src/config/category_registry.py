"""
UI kategori ve alt kategori kayıtları.

Bu dosya:
- frontend dropdown üretimi için kullanılır
- backend tarafında kullanıcı seçimini rule koduna map eder
- Türkçe etiketler ile teknik anahtarları ayırır

Not:
- Buradaki `code` alanları, ileride tag_rules.py içindeki rule anahtarlarıyla eşleşecektir.
- `admin_boundaries` kategorisi özel bir kategori olarak tutulur;
  bunun alt tipleri admin_levels.py ile ilişkilidir.
"""


CATEGORY_REGISTRY = {
    "admin_boundaries": {
        "label_tr": "İdari Sınırlar",
        "label_en": "Administrative Boundaries",
        "icon": "🏳️",
        "ui_order": 1,
        "subcategories": [
            {
                "key": "neighbourhood",
                "label_tr": "Mahalle Sınırları",
                "label_en": "Neighbourhood Boundaries",
                "code": "admin_neighbourhood",
                "source": "admin_levels",
            },
            {
                "key": "district",
                "label_tr": "İlçe Sınırları",
                "label_en": "District Boundaries",
                "code": "admin_district",
                "source": "admin_levels",
            },
            {
                "key": "province",
                "label_tr": "İl Sınırları",
                "label_en": "Province Boundaries",
                "code": "admin_province",
                "source": "admin_levels",
            },
        ],
    },

    "buildings": {
        "label_tr": "Binalar",
        "label_en": "Buildings",
        "icon": "🏢",
        "ui_order": 2,
        "subcategories": [
            {"key": "residential", "label_tr": "Konut - Genel", "label_en": "Residential", "code": "building_residential"},
            {"key": "house", "label_tr": "Müstakil Ev", "label_en": "House", "code": "building_house"},
            {"key": "apartments", "label_tr": "Apartman", "label_en": "Apartments", "code": "building_apartments"},
            {"key": "detached", "label_tr": "Villa", "label_en": "Detached House", "code": "building_detached"},
            {"key": "terrace", "label_tr": "İkiz / Sıra Ev", "label_en": "Terrace", "code": "building_terrace"},
            {"key": "commercial", "label_tr": "Ticari Genel", "label_en": "Commercial", "code": "building_commercial"},
            {"key": "office", "label_tr": "Ofis Binası", "label_en": "Office Building", "code": "building_office"},
            {"key": "retail", "label_tr": "Alışveriş Merkezi", "label_en": "Retail Building", "code": "building_retail"},
            {"key": "industrial", "label_tr": "Endüstriyel", "label_en": "Industrial", "code": "building_industrial"},
            {"key": "warehouse", "label_tr": "Depo", "label_en": "Warehouse", "code": "building_warehouse"},
            {"key": "hospital", "label_tr": "Hastane Binası", "label_en": "Hospital Building", "code": "building_hospital"},
            {"key": "school", "label_tr": "Okul Binası", "label_en": "School Building", "code": "building_school"},
            {"key": "university", "label_tr": "Üniversite Binası", "label_en": "University Building", "code": "building_university"},
            {"key": "religious", "label_tr": "Dini Yapı - Genel", "label_en": "Religious Building", "code": "building_religious"},
            {"key": "mosque", "label_tr": "Cami", "label_en": "Mosque", "code": "building_mosque"},
            {"key": "church", "label_tr": "Kilise", "label_en": "Church", "code": "building_church"},
            {"key": "synagogue", "label_tr": "Sinagog", "label_en": "Synagogue", "code": "building_synagogue"},
            {"key": "public", "label_tr": "Kamu Binası", "label_en": "Public Building", "code": "building_public"},
            {"key": "civic", "label_tr": "Belediye", "label_en": "Civic Building", "code": "building_civic"},
            {"key": "police", "label_tr": "Karakol", "label_en": "Police Building", "code": "building_police"},
            {"key": "fire_station", "label_tr": "İtfaiye", "label_en": "Fire Station", "code": "building_fire_station"},
            {"key": "garages", "label_tr": "Garaj / Otopark", "label_en": "Garage / Parking", "code": "building_garages"},
            {"key": "sports_hall", "label_tr": "Spor Salonu", "label_en": "Sports Hall", "code": "building_sports_hall"},
            {"key": "historic", "label_tr": "Tarihsel", "label_en": "Historic Building", "code": "building_historic"},
            {"key": "yes", "label_tr": "Belirsiz Bina (yes)", "label_en": "Unspecified Building (yes)", "code": "building_yes"},
            {"key": "yes_unresolved", "label_tr": "Çözülemeyen yes Binaları", "label_en": "Unresolved yes Buildings", "code": "building_yes_unresolved"},
        ],
    },

    "health": {
        "label_tr": "Sağlık",
        "label_en": "Health",
        "icon": "🏥",
        "ui_order": 3,
        "subcategories": [
            {"key": "hospital", "label_tr": "Hastane", "label_en": "Hospital", "code": "hospital"},
            {"key": "clinic", "label_tr": "Klinik / Poliklinik", "label_en": "Clinic", "code": "clinic"},
            {"key": "family_health", "label_tr": "Aile Hekimi / Sağlık Ocağı", "label_en": "Family Health Center", "code": "family_health"},
            {"key": "dentist", "label_tr": "Diş Hekimi", "label_en": "Dentist", "code": "dentist"},
            {"key": "pharmacy", "label_tr": "Eczane", "label_en": "Pharmacy", "code": "pharmacy"},
            {"key": "emergency", "label_tr": "Acil Servis", "label_en": "Emergency", "code": "emergency"},
            {"key": "veterinary", "label_tr": "Veteriner", "label_en": "Veterinary", "code": "veterinary"},
            {"key": "ambulance_station", "label_tr": "Ambulans İstasyonu", "label_en": "Ambulance Station", "code": "ambulance_station"},
            {"key": "optician", "label_tr": "Optisyen", "label_en": "Optician", "code": "optician"},
            {"key": "private_hospital", "label_tr": "Hastane - Özel", "label_en": "Private Hospital", "code": "private_hospital"},
            {"key": "public_hospital", "label_tr": "Hastane - Kamu", "label_en": "Public Hospital", "code": "public_hospital"},
        ],
    },

    "education": {
        "label_tr": "Eğitim",
        "label_en": "Education",
        "icon": "🎓",
        "ui_order": 4,
        "subcategories": [
            {"key": "primary_school", "label_tr": "İlkokul", "label_en": "Primary School", "code": "primary_school"},
            {"key": "middle_school", "label_tr": "Ortaokul", "label_en": "Middle School", "code": "middle_school"},
            {"key": "high_school", "label_tr": "Lise", "label_en": "High School", "code": "high_school"},
            {"key": "public_school", "label_tr": "Devlet Okulu", "label_en": "Public School", "code": "public_school"},
            {"key": "private_school", "label_tr": "Özel Okul", "label_en": "Private School", "code": "private_school"},
            {"key": "university", "label_tr": "Üniversite", "label_en": "University", "code": "education_university"},
            {"key": "student_dormitory", "label_tr": "Yurt / KYK", "label_en": "Student Dormitory", "code": "student_dormitory"},
            {"key": "kindergarten", "label_tr": "Anaokulu / Kreş", "label_en": "Kindergarten", "code": "kindergarten"},
            {"key": "college_course", "label_tr": "Dershane / Kurs", "label_en": "College / Course", "code": "college_course"},
            {"key": "library", "label_tr": "Kütüphane", "label_en": "Library", "code": "library"},
        ],
    },

    "green_area": {
        "label_tr": "Yeşil Alan",
        "label_en": "Green Area",
        "icon": "🌳",
        "ui_order": 5,
        "subcategories": [
            {"key": "park", "label_tr": "Park", "label_en": "Park", "code": "park"},
            {"key": "playground", "label_tr": "Çocuk Oyun Alanı", "label_en": "Playground", "code": "playground"},
            {"key": "pitch", "label_tr": "Spor Sahası", "label_en": "Pitch", "code": "pitch"},
            {"key": "assembly_point", "label_tr": "Toplanma Alanı", "label_en": "Assembly Point", "code": "assembly_point"},
            {"key": "garden", "label_tr": "Botanik Bahçe", "label_en": "Botanical Garden", "code": "garden"},
            {"key": "forest", "label_tr": "Orman / Koruluk", "label_en": "Forest", "code": "forest"},
            {"key": "cemetery", "label_tr": "Mezarlık", "label_en": "Cemetery", "code": "cemetery"},
            {"key": "beach", "label_tr": "Sahil / Kıyı Bandı", "label_en": "Beach", "code": "beach"},
            {"key": "sports_centre", "label_tr": "Spor Kompleksi", "label_en": "Sports Centre", "code": "sports_centre"},
            {"key": "stadium", "label_tr": "Stadyum", "label_en": "Stadium", "code": "stadium"},
        ],
    },

    "transport": {
        "label_tr": "Ulaşım",
        "label_en": "Transport",
        "icon": "🚇",
        "ui_order": 6,
        "subcategories": [
            {"key": "bus_stop", "label_tr": "Otobüs Durağı", "label_en": "Bus Stop", "code": "bus_stop"},
            {"key": "metro_station", "label_tr": "Metro İstasyonu", "label_en": "Metro Station", "code": "metro_station"},
            {"key": "metrobus_stop", "label_tr": "Metrobüs Durağı", "label_en": "Metrobus Stop", "code": "metrobus_stop"},
            {"key": "tram_stop", "label_tr": "Tramvay Durağı", "label_en": "Tram Stop", "code": "tram_stop"},
            {"key": "ferry_terminal", "label_tr": "Vapur İskelesi", "label_en": "Ferry Terminal", "code": "ferry_terminal"},
            {"key": "bus_station", "label_tr": "Otogar", "label_en": "Bus Station", "code": "bus_station"},
            {"key": "parking", "label_tr": "Otopark", "label_en": "Parking", "code": "parking"},
            {"key": "bicycle_parking", "label_tr": "Bisiklet Park", "label_en": "Bicycle Parking", "code": "bicycle_parking"},
            {"key": "taxi", "label_tr": "Taksi Durağı", "label_en": "Taxi", "code": "taxi"},
            {"key": "bridge", "label_tr": "Köprü", "label_en": "Bridge", "code": "bridge"},
        ],
    },

    "commerce": {
        "label_tr": "Ticaret",
        "label_en": "Commerce",
        "icon": "🛒",
        "ui_order": 7,
        "subcategories": [
            {"key": "supermarket", "label_tr": "Süpermarket", "label_en": "Supermarket", "code": "supermarket"},
            {"key": "market", "label_tr": "Market", "label_en": "Convenience Store", "code": "market"},
            {"key": "mall", "label_tr": "AVM", "label_en": "Mall", "code": "mall"},
            {"key": "bank", "label_tr": "Banka", "label_en": "Bank", "code": "bank"},
            {"key": "atm", "label_tr": "ATM", "label_en": "ATM", "code": "atm"},
            {"key": "restaurant", "label_tr": "Restoran", "label_en": "Restaurant", "code": "restaurant"},
            {"key": "cafe", "label_tr": "Kafe", "label_en": "Cafe", "code": "cafe"},
            {"key": "post_office", "label_tr": "Postane", "label_en": "Post Office", "code": "post_office"},
            {"key": "hotel", "label_tr": "Otel", "label_en": "Hotel", "code": "commerce_hotel"},
            {"key": "fuel", "label_tr": "Benzin İstasyonu", "label_en": "Fuel Station", "code": "fuel"},
        ],
    },

    "infrastructure": {
        "label_tr": "Altyapı",
        "label_en": "Infrastructure",
        "icon": "⚙️",
        "ui_order": 8,
        "subcategories": [
            {"key": "power_substation", "label_tr": "Elektrik Trafosu", "label_en": "Power Substation", "code": "power_substation"},
            {"key": "water_tower", "label_tr": "Su Deposu", "label_en": "Water Tower", "code": "water_tower"},
            {"key": "communication_tower", "label_tr": "İletişim Kulesi", "label_en": "Communication Tower", "code": "communication_tower"},
            {"key": "waste_disposal", "label_tr": "Çöp Toplama", "label_en": "Waste Disposal", "code": "waste_disposal"},
            {"key": "recycling", "label_tr": "Geri Dönüşüm", "label_en": "Recycling", "code": "recycling"},
            {"key": "police", "label_tr": "Karakol", "label_en": "Police", "code": "infrastructure_police"},
            {"key": "fire_station", "label_tr": "İtfaiye İstasyonu", "label_en": "Fire Station", "code": "infrastructure_fire_station"},
            {"key": "power_line", "label_tr": "Elektrik Hattı", "label_en": "Power Line", "code": "power_line"},
            {"key": "mast", "label_tr": "Baz İstasyonu", "label_en": "Base Station", "code": "mast"},
        ],
    },

    "culture": {
        "label_tr": "Kültür",
        "label_en": "Culture",
        "icon": "🏛️",
        "ui_order": 9,
        "subcategories": [
            {"key": "museum", "label_tr": "Müze", "label_en": "Museum", "code": "museum"},
            {"key": "historic_building", "label_tr": "Tarihi Yapı", "label_en": "Historic Building", "code": "historic_building"},
            {"key": "monument", "label_tr": "Anıt", "label_en": "Monument", "code": "monument"},
            {"key": "castle", "label_tr": "Kale / Sur", "label_en": "Castle / Walls", "code": "castle"},
            {"key": "theatre", "label_tr": "Tiyatro", "label_en": "Theatre", "code": "theatre"},
            {"key": "cinema", "label_tr": "Sinema", "label_en": "Cinema", "code": "cinema"},
            {"key": "arts_centre", "label_tr": "Kültür Merkezi", "label_en": "Arts Centre", "code": "arts_centre"},
            {"key": "public_bath", "label_tr": "Hamam", "label_en": "Public Bath", "code": "public_bath"},
        ],
    },
}


def get_main_category_options_tr() -> list[dict]:
    """
    Ana kategori dropdown için Türkçe seçenekleri döner.
    """
    rows = []

    for key, value in sorted(
        CATEGORY_REGISTRY.items(),
        key=lambda item: item[1].get("ui_order", 999),
    ):
        rows.append(
            {
                "key": key,
                "label": f"{value.get('icon', '')} {value['label_tr']}".strip(),
            }
        )

    return rows


def get_subcategory_options_tr(category_key: str) -> list[dict]:
    """
    Belirli bir ana kategori için alt kategori seçeneklerini döner.
    """
    if category_key not in CATEGORY_REGISTRY:
        raise ValueError(f"Geçersiz kategori: {category_key}")

    return [
        {
            "key": item["key"],
            "label": item["label_tr"],
            "code": item["code"],
        }
        for item in CATEGORY_REGISTRY[category_key]["subcategories"]
    ]


def get_subcategory_code(category_key: str, subcategory_key: str) -> str:
    """
    Kategori + alt kategori seçimine göre teknik rule code döner.
    """
    if category_key not in CATEGORY_REGISTRY:
        raise ValueError(f"Geçersiz kategori: {category_key}")

    for item in CATEGORY_REGISTRY[category_key]["subcategories"]:
        if item["key"] == subcategory_key:
            return item["code"]

    raise ValueError(
        f"Geçersiz alt kategori: {subcategory_key} (category={category_key})"
    )


def is_valid_category(category_key: str) -> bool:
    """
    Geçerli ana kategori mi?
    """
    return category_key in CATEGORY_REGISTRY


def is_valid_subcategory(category_key: str, subcategory_key: str) -> bool:
    """
    Verilen ana kategori altında alt kategori geçerli mi?
    """
    if category_key not in CATEGORY_REGISTRY:
        return False

    return any(
        item["key"] == subcategory_key
        for item in CATEGORY_REGISTRY[category_key]["subcategories"]
    )
