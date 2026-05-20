"""
components/domain_config.py — Use-case label & feature configuration.

Tool çekirdeği p-Median facility-location matematiği üzerine kurulu. Math
generic ama UI başlangıçta tek bir senaryo (earthquake assembly) için
hardcoded etiketlerle yazılmıştı. Bu modül domain-aware bir gevşeklik
katmanı sağlar:

  • Sidebar dropdown ile kullanıcı bir use-case seçer (Earthquake preset
    veya Custom generic).
  • UI tüm "Buildings → Demand points (buildings)" ile başlayan etiketleri
    seçili domain'in sözlüğünden çeker.
  • AFAD-spesifik methodology paragraflarının Excel raporda göründüğü
    Earthquake; Custom'da tüm yardımcılar açık ama AFAD detayları yok.

Akademik sınır: matematik 100% generic, ama Earthquake dışı bir senaryo
için weight/capacity verisi **kullanıcıdan beklenir** (kendi tablonuzu
yükleyin). Tez raporunda da bu açıkça belirtilir.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainConfig:
    """Bir domain için tüm görünür etiketler + feature flag'leri."""

    # Kimlik
    key: str
    display_name: str
    icon: str       # emoji veya benzer

    # Hero
    hero_eyebrow: str
    hero_subtitle: str

    # Demand (talep noktaları) — orijinal: Buildings
    demand_singular: str    # örn. "building"
    demand_plural: str      # örn. "buildings"
    demand_label: str       # KPI başlığı — örn. "Buildings (demand)"

    # Facility (tesisler) — orijinal: Assembly areas
    facility_singular: str  # örn. "assembly area"
    facility_plural: str    # örn. "assembly areas"
    facility_label: str     # KPI başlığı — örn. "Assembly areas (facilities)"

    # Weight (talep miktarı) — orijinal: Population
    weight_concept: str     # örn. "population", "enrollment"
    weight_label: str       # örn. "Avg est. population"

    # Capacity (kapasite varyantı) — orijinal: AFAD m²/person
    capacity_method_label: str  # density slider başlığı
    capacity_method_help_short: str    # density help tek satır

    # Travel
    travel_label: str       # "Walking time" / "Travel time"

    # Section başlıkları
    step1_weight_section_title: str   # örn. "Population data"
    step1_data_section_title: str     # örn. "Buildings & assembly areas"

    # Feature flags — hangi domain-spesifik UI gösterilsin?
    show_population_methods: bool   # Footprint / Uniform / Auto radio
    show_tuik_upload: bool          # TÜİK CSV upload
    show_afad_methodology: bool     # Methodology sheet'inde AFAD detayları

    # Methodology Excel paragrafları
    methodology_capacity: str       # capacity kısıtı açıklaması


# ════════════════════════════════════════════════════════════════════════════
# DOMAIN PRESETLERİ
# ════════════════════════════════════════════════════════════════════════════

EARTHQUAKE = DomainConfig(
    key="earthquake",
    display_name="Earthquake Assembly (preset)",
    icon="🏚️",
    hero_eyebrow="Decision Support · Facility-Location Optimization",
    hero_subtitle=(
        "A capacity-aware p-Median assignment optimizer (Hakimi 1964): "
        "assign any set of demand points to a chosen number of facilities, "
        "minimizing total travel time and optionally enforcing capacity. "
        "This preset is AFAD-tuned for **earthquake assembly area planning** "
        "(buildings → assembly areas, walking by default, m²/person capacity) — "
        "switch the sidebar use case to **Custom** for fully generic vocabulary."
    ),
    demand_singular="building",
    demand_plural="buildings",
    demand_label="Buildings (demand)",
    facility_singular="assembly area",
    facility_plural="assembly areas",
    facility_label="Assembly areas (facilities)",
    weight_concept="population",
    weight_label="Avg est. population",
    capacity_method_label="Density (m²/person)",
    capacity_method_help_short=(
        "How many m² each person needs in the assembly area. "
        "Capacity = area_m² / density."
    ),
    travel_label="Walking time",
    step1_weight_section_title="Population data",
    step1_data_section_title="Buildings & assembly areas",
    show_population_methods=True,
    show_tuik_upload=True,
    show_afad_methodology=True,
    methodology_capacity=(
        "When ON: Σᵢ wᵢ xᵢⱼ ≤ Cⱼ yⱼ with Cⱼ = area_m² / density. "
        "Density is a USER PARAMETER (m²/person, default 1.5 = AFAD assembly "
        "standard). Alternatives: 1.0 = high-density emergency, 2.5 = AFAD "
        "long-term shelter. The 'Compare capacity ON vs OFF' button (Step 3) "
        "automates side-by-side sensitivity."
    ),
)

CUSTOM = DomainConfig(
    key="custom",
    display_name="Custom (generic vocabulary)",
    icon="🔧",
    hero_eyebrow="Decision Support · Facility Location",
    hero_subtitle=(
        "Generic p-Median (Hakimi 1964) facility-location optimizer. Assign "
        "any set of demand points to a chosen number of facilities with "
        "optional capacity constraints. All earthquake-specific helpers "
        "(TÜİK upload, footprint estimator, AFAD density presets) remain "
        "available for users who want them."
    ),
    demand_singular="demand point",
    demand_plural="demand points",
    demand_label="Demand points",
    facility_singular="facility",
    facility_plural="facilities",
    facility_label="Facilities",
    weight_concept="demand weight",
    weight_label="Avg demand weight",
    capacity_method_label="Density (m²/unit)",
    capacity_method_help_short=(
        "Area required per unit of demand. Capacity = area_m² / density."
    ),
    travel_label="Travel time",
    step1_weight_section_title="Demand weights",
    step1_data_section_title="Demand points & facilities",
    show_population_methods=True,    # Custom: all features available
    show_tuik_upload=True,
    show_afad_methodology=False,
    methodology_capacity=(
        "When ON: Σᵢ wᵢ xᵢⱼ ≤ Cⱼ yⱼ with Cⱼ = area_m² / density. Density "
        "is a user parameter — set it to match the per-unit area assumption "
        "of your domain (m²/person, m²/student, m²/bed, …)."
    ),
)


# Ana sözlük: key → DomainConfig
#
# Tasarım kararı: sadece 2 preset tutuyoruz.
#   • Earthquake — AFAD birincil senaryo, tam methodology
#   • Custom    — generic vocabulary, tüm helpers açık
# Daha önce Schools/Healthcare preset'leri vardı ama her biri eksik
# data-preparation hikayesiyle "üstünkörü generic" hissi veriyordu.
# Custom + Earthquake ikilisi yeterli ve dürüst: "AFAD için hazır, başka
# her şey için kullanıcı kendi etiketlerini override eder."
DOMAINS: dict[str, DomainConfig] = {
    "earthquake": EARTHQUAKE,
    "custom":     CUSTOM,
}

DEFAULT_DOMAIN_KEY = "earthquake"


def get_domain(key: str | None) -> DomainConfig:
    """Domain config'i güvenle getir; bilinmeyen key default'a düşer."""
    if not key or key not in DOMAINS:
        return DOMAINS[DEFAULT_DOMAIN_KEY]
    return DOMAINS[key]
