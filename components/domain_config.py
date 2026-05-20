"""
components/domain_config.py — Multi-domain label & feature configuration.

Tool çekirdeği p-Median facility-location matematiği üzerine kurulu. Math
generic ama UI başlangıçta tek bir senaryo (earthquake assembly) için
hardcoded etiketlerle yazılmıştı. Bu modül domain-aware bir gevşeklik
katmanı sağlar:

  • Domain dropdown ile kullanıcı bir senaryo seçer (Earthquake, Schools,
    Healthcare, Custom).
  • UI tüm "Buildings → Demand points (buildings)" ile başlayan etiketleri
    seçili domain'in sözlüğünden çeker.
  • Earthquake-spesifik özellikler (TÜİK upload, footprint formülü, AFAD
    methodology) sadece Earthquake/Custom'da görünür; diğer domain'lerde
    gizlenip kullanıcı "kendi weight'inizi yükleyin" yönlendirmesi alır.

Akademik sınır: matematik 100% generic, ama veri ön-hazırlığı (örn. school
enrollment Excel'i, hospital bed kapasitesi) **kullanıcıdan beklenir** —
bu aracın sunduğu uyarlanabilirliğin scope sınırıdır. Tez raporunda da
bu açıkça belirtilir.
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
    display_name="Earthquake Assembly (default)",
    icon="🏚️",
    hero_eyebrow="Decision Support · Earthquake Preparedness",
    hero_subtitle=(
        "Allocate buildings to the optimal set of earthquake assembly areas "
        "with a capacity-aware P-Median model. Choose walking (AFAD default) "
        "or driving (comparative analysis), and balance coverage, average "
        "travel time, and optional capacity in a single run."
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

SCHOOLS = DomainConfig(
    key="schools",
    display_name="Schools (students → schools)",
    icon="🏫",
    hero_eyebrow="Decision Support · Educational Planning",
    hero_subtitle=(
        "Assign demand points (population centers / households) to a chosen "
        "number of schools using a capacity-aware P-Median model. "
        "Weights are interpreted as student counts; capacity reflects "
        "classroom seats. Underlying solver is identical to the earthquake "
        "preset — only the UI vocabulary adapts."
    ),
    demand_singular="population center",
    demand_plural="population centers",
    demand_label="Population centers (demand)",
    facility_singular="school",
    facility_plural="schools",
    facility_label="Schools (facilities)",
    weight_concept="student count",
    weight_label="Avg students per center",
    capacity_method_label="Density (m²/student)",
    capacity_method_help_short=(
        "How many m² each student needs in the school. "
        "Capacity = area_m² / density. Typical: 2-4 m²/student."
    ),
    travel_label="Travel time",
    step1_weight_section_title="Student demand",
    step1_data_section_title="Population centers & schools",
    show_population_methods=False,
    show_tuik_upload=False,
    show_afad_methodology=False,
    methodology_capacity=(
        "When ON: Σᵢ wᵢ xᵢⱼ ≤ Cⱼ yⱼ with Cⱼ = area_m² / density "
        "(m²/student, user-tunable). For schools, density typically reflects "
        "classroom-area-per-student (2–4 m² depending on jurisdiction)."
    ),
)

HEALTHCARE = DomainConfig(
    key="healthcare",
    display_name="Healthcare (patients → hospitals/clinics)",
    icon="🏥",
    hero_eyebrow="Decision Support · Healthcare Access",
    hero_subtitle=(
        "Assign demand points (population centers) to a chosen number of "
        "healthcare facilities using a capacity-aware P-Median model. "
        "Weights are interpreted as patient demand; capacity reflects bed "
        "or service-slot capacity. Solver is unchanged — UI adapts."
    ),
    demand_singular="population center",
    demand_plural="population centers",
    demand_label="Population centers (demand)",
    facility_singular="facility",
    facility_plural="facilities",
    facility_label="Healthcare facilities",
    weight_concept="patient demand",
    weight_label="Avg patients per center",
    capacity_method_label="Density (m²/patient or bed)",
    capacity_method_help_short=(
        "How many m² each patient/bed needs. Capacity = area_m² / density. "
        "User-tunable for outpatient (smaller) vs inpatient (larger) services."
    ),
    travel_label="Travel time",
    step1_weight_section_title="Patient demand",
    step1_data_section_title="Population centers & healthcare facilities",
    show_population_methods=False,
    show_tuik_upload=False,
    show_afad_methodology=False,
    methodology_capacity=(
        "When ON: Σᵢ wᵢ xᵢⱼ ≤ Cⱼ yⱼ with Cⱼ = area_m² / density. For "
        "healthcare, the user supplies the per-patient-area assumption that "
        "best matches their service type (outpatient vs inpatient)."
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
DOMAINS: dict[str, DomainConfig] = {
    "earthquake": EARTHQUAKE,
    "schools":    SCHOOLS,
    "healthcare": HEALTHCARE,
    "custom":     CUSTOM,
}

DEFAULT_DOMAIN_KEY = "earthquake"


def get_domain(key: str | None) -> DomainConfig:
    """Domain config'i güvenle getir; bilinmeyen key default'a düşer."""
    if not key or key not in DOMAINS:
        return DOMAINS[DEFAULT_DOMAIN_KEY]
    return DOMAINS[key]
