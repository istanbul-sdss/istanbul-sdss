"""
Multi-domain UI etiket konfigürasyonu regresyonu.

components/domain_config.py'daki sözlüklerin tutarlılığını + Optimization_Tool
tarafının onu doğru tükettiğini kontrol eder. Streamlit-bound UI'ı doğrudan
test edemiyoruz ama config katmanı pure Python — test edilebilir.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from components.domain_config import (
    DEFAULT_DOMAIN_KEY,
    DOMAINS,
    DomainConfig,
    get_domain,
)


def test_default_domain_is_earthquake():
    """Default değişmemeli — earthquake birincil scope."""
    assert DEFAULT_DOMAIN_KEY == "earthquake"
    assert DEFAULT_DOMAIN_KEY in DOMAINS


def test_all_four_presets_exist():
    """4 preset (earthquake/schools/healthcare/custom) tanımlı olmalı."""
    expected = {"earthquake", "schools", "healthcare", "custom"}
    assert set(DOMAINS.keys()) == expected


def test_get_domain_falls_back_to_default_on_unknown():
    """Bilinmeyen key default'a düşer — UI hatasından sonra session bozulmasın."""
    bogus = get_domain("schrödinger")
    assert bogus.key == DEFAULT_DOMAIN_KEY


def test_get_domain_falls_back_on_none():
    """None argümanı da default'a düşmeli (session_state boş ise)."""
    assert get_domain(None).key == DEFAULT_DOMAIN_KEY


@pytest.mark.parametrize("key", list(DOMAINS.keys()))
def test_each_domain_has_complete_label_set(key: str):
    """Her domain tüm zorunlu alanları (None değil, boş string değil) doldurmalı."""
    d = DOMAINS[key]
    assert isinstance(d, DomainConfig)
    required_string_fields = [
        "display_name", "icon", "hero_eyebrow", "hero_subtitle",
        "demand_singular", "demand_plural", "demand_label",
        "facility_singular", "facility_plural", "facility_label",
        "weight_concept", "weight_label",
        "capacity_method_label", "capacity_method_help_short",
        "travel_label",
        "step1_weight_section_title", "step1_data_section_title",
        "methodology_capacity",
    ]
    for fld in required_string_fields:
        val = getattr(d, fld)
        assert isinstance(val, str) and val.strip(), (
            f"Domain '{key}' has empty/non-string {fld!r}: {val!r}"
        )


@pytest.mark.parametrize("key", list(DOMAINS.keys()))
def test_each_domain_has_feature_flags(key: str):
    """Feature flag'leri bool olmalı."""
    d = DOMAINS[key]
    for fld in [
        "show_population_methods",
        "show_tuik_upload",
        "show_afad_methodology",
    ]:
        assert isinstance(getattr(d, fld), bool)


def test_earthquake_has_all_afad_features_enabled():
    """Earthquake birincil scope — tüm AFAD/TÜİK özellikleri açık olmalı."""
    eq = DOMAINS["earthquake"]
    assert eq.show_population_methods is True
    assert eq.show_tuik_upload is True
    assert eq.show_afad_methodology is True


def test_non_earthquake_domains_disable_tuik_when_appropriate():
    """
    Schools/Healthcare için TÜİK upload anlamlı değil; gizlenmiş olmalı.
    Custom için açık (kullanıcı dilerse kullanır).
    """
    assert DOMAINS["schools"].show_tuik_upload is False
    assert DOMAINS["healthcare"].show_tuik_upload is False
    assert DOMAINS["custom"].show_tuik_upload is True


def test_labels_are_distinct_across_domains():
    """Farklı domain'ler farklı demand label'ı kullanmalı — fark görünür."""
    demand_labels = {DOMAINS[k].demand_label for k in DOMAINS}
    assert len(demand_labels) >= 3, (
        f"Demand label'ları çok benzer: {demand_labels}"
    )


def test_optimization_tool_imports_domain_config():
    """Optimization_Tool.py'nin domain_config'i import ettiğinden emin ol."""
    src = Path("Optimization_Tool.py").read_text(encoding="utf-8")
    assert "from components.domain_config import" in src, (
        "Optimization_Tool.py domain_config'i import etmeli"
    )
    assert "DEFAULT_DOMAIN_KEY" in src
    assert "get_domain" in src
