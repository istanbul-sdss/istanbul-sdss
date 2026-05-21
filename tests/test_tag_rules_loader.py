"""
Regresyon (C2): tag_rules.py artık 1318 satırlık Python dict literal yerine
sibling `tag_rules.json` dosyasından yüklüyor. Bu testler:

- yüklemenin gerçekleştiğini ve rule sayısının beklenen seviyede olduğunu,
- şema validasyonunun eksik/yanlış-tipli alanı tespit ettiğini,
- NAME_PATTERNS'in eski public API olarak hâlâ import edilebildiğini,
- TAG_RULES içindeki polymorphic `strict_tags` (dict vs list) örneklerinin
  her ikisinin de geçerli sayıldığını,
- yardımcı fonksiyonların (get_rule, is_valid_rule_code, …) eski sözleşmeyi
  koruduğunu

doğrular. JSON dosyası bozulursa veya bir alan yanlışlıkla silinirse import
ImportError/ValueError/TypeError ile patlar — testler bu uçları çekiyor.
"""
from __future__ import annotations

import json

import pytest

from src.config.tag_rules import (
    _DATA_FILE,
    NAME_PATTERNS,
    TAG_RULES,
    _load_rules,
    _validate_rule,
    get_export_family,
    get_name_patterns,
    get_query_tags,
    get_rule,
    get_rules_by_category,
    is_valid_rule_code,
)


# ── 1. Loader temel davranışı ────────────────────────────────────────────────
def test_loader_returns_97_rules_with_known_codes():
    """
    Refactor sırasında rule sayısı değiştirilmeden taşınmalı. Spesifik
    rule code'ları kontrol ederek silent drop'u yakalarız.
    """
    assert len(TAG_RULES) == 97, (
        f"Rule sayısı beklenenin dışında: {len(TAG_RULES)}; tag_rules.json "
        f"içeriği daraltıldı veya genişledi — beklenen değişiklikse bu "
        f"sayıyı güncelleyin."
    )
    # Birkaç farklı kategori grubundan örnek
    for code in (
        "admin_neighbourhood",
        "building_house",
        "assembly_point",
        "primary_school",
        "hospital",
        "building_mosque",
        "public_bath",
    ):
        assert code in TAG_RULES, f"Beklenen rule kayıp: {code}"


def test_data_file_exists_and_is_valid_json():
    assert _DATA_FILE.exists(), f"tag_rules.json yok: {_DATA_FILE}"
    with _DATA_FILE.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    assert isinstance(raw, dict)
    assert len(raw) == len(TAG_RULES)


def test_name_patterns_still_exposed_for_backward_compat():
    """
    NAME_PATTERNS şu an dış modüllerce import edilmiyor ama refactor
    sırasında public sembolü kaldırmamak için inline tuttuk; importable
    olduğunu açıkça test et.
    """
    assert isinstance(NAME_PATTERNS, dict)
    assert "mosque" in NAME_PATTERNS
    assert isinstance(NAME_PATTERNS["mosque"], list)
    assert "cami" in NAME_PATTERNS["mosque"]


# ── 2. Şema validasyonu (zorunlu alanlar) ────────────────────────────────────
def test_validate_rule_accepts_complete_dict_rule():
    """Tipik dict-strict_tags rule formu — patlamamalı."""
    valid = {
        "category_group":             "buildings",
        "subcategory":                "house",
        "label_tr":                   "Müstakil Ev",
        "geometry_expected":          ["Polygon"],
        "query_mode":                 "union",
        "query_tags":                 [{"building": "house"}],
        "strict_tags":                {"building": "house"},
        "support_tags":               {},
        "name_patterns":              [],
        "allow_name_fallback":        False,
        "allow_building_yes_mapping": False,
        "collect_unresolved":         False,
        "export_family":              "building",
    }
    _validate_rule("building_house", valid)  # raise yoksa pas


def test_validate_rule_accepts_list_strict_tags():
    """assembly_point gibi OR-of-AND form: strict_tags list[dict]."""
    valid = {
        "category_group":             "emergency",
        "subcategory":                "assembly_point",
        "label_tr":                   "Toplanma Alanı",
        "geometry_expected":          ["Point", "Polygon"],
        "query_mode":                 "union",
        "query_tags":                 [{"emergency": "assembly_point"}],
        "strict_tags":                [
            {"emergency": "assembly_point"},
            {"amenity": "assembly_point"},
        ],
        "support_tags":               {},
        "name_patterns":              [],
        "allow_name_fallback":        False,
        "allow_building_yes_mapping": False,
        "collect_unresolved":         False,
        "export_family":              "emergency",
    }
    _validate_rule("assembly_point", valid)


def test_validate_rule_raises_on_missing_required_field():
    incomplete = {
        "category_group":             "buildings",
        # subcategory eksik bilerek
        "label_tr":                   "X",
        "geometry_expected":          ["Polygon"],
        "query_mode":                 "union",
        "query_tags":                 [{"building": "x"}],
        "strict_tags":                {"building": "x"},
        "support_tags":               {},
        "name_patterns":              [],
        "allow_name_fallback":        False,
        "allow_building_yes_mapping": False,
        "collect_unresolved":         False,
        "export_family":              "building",
    }
    with pytest.raises(ValueError, match="subcategory"):
        _validate_rule("test_missing", incomplete)


def test_validate_rule_raises_on_wrong_type():
    """label_tr int verilirse TypeError; pointer mesaj rule code'u içermeli."""
    bad = {
        "category_group":             "buildings",
        "subcategory":                "house",
        "label_tr":                   123,   # str beklenir
        "geometry_expected":          ["Polygon"],
        "query_mode":                 "union",
        "query_tags":                 [{"building": "house"}],
        "strict_tags":                {"building": "house"},
        "support_tags":               {},
        "name_patterns":              [],
        "allow_name_fallback":        False,
        "allow_building_yes_mapping": False,
        "collect_unresolved":         False,
        "export_family":              "building",
    }
    with pytest.raises(TypeError, match="label_tr"):
        _validate_rule("test_wrong_type", bad)


def test_validate_rule_accepts_optional_fields_with_correct_type():
    """accept_query_tag_match / query_tag_match_score opsiyonel ama tipli."""
    valid = {
        "category_group":             "x",
        "subcategory":                "y",
        "label_tr":                   "Z",
        "geometry_expected":          ["Point"],
        "query_mode":                 "union",
        "query_tags":                 [{"amenity": "z"}],
        "strict_tags":                {"amenity": "z"},
        "support_tags":               {},
        "name_patterns":              [],
        "allow_name_fallback":        False,
        "allow_building_yes_mapping": False,
        "collect_unresolved":         False,
        "export_family":              "generic",
        "accept_query_tag_match":     True,
        "query_tag_match_score":      5,
    }
    _validate_rule("test_optional", valid)


def test_validate_rule_rejects_wrong_type_on_optional_field():
    bad = {
        "category_group":             "x",
        "subcategory":                "y",
        "label_tr":                   "Z",
        "geometry_expected":          ["Point"],
        "query_mode":                 "union",
        "query_tags":                 [{"amenity": "z"}],
        "strict_tags":                {"amenity": "z"},
        "support_tags":               {},
        "name_patterns":              [],
        "allow_name_fallback":        False,
        "allow_building_yes_mapping": False,
        "collect_unresolved":         False,
        "export_family":              "generic",
        "query_tag_match_score":      "high",  # int beklenir
    }
    with pytest.raises(TypeError, match="query_tag_match_score"):
        _validate_rule("test_optional_wrong", bad)


# ── 3. Helper API geriye uyumluluk ───────────────────────────────────────────
def test_get_rule_returns_dict_for_known_code():
    rule = get_rule("building_house")
    assert isinstance(rule, dict)
    assert rule["category_group"] == "buildings"


def test_get_rule_raises_for_unknown_code():
    with pytest.raises(ValueError, match="Geçersiz rule code"):
        get_rule("nonexistent_rule_xyz")


def test_is_valid_rule_code():
    assert is_valid_rule_code("building_house") is True
    assert is_valid_rule_code("nonexistent_rule_xyz") is False


def test_get_query_tags_returns_list_of_dicts():
    tags = get_query_tags("building_house")
    assert isinstance(tags, list)
    assert all(isinstance(t, dict) for t in tags)


def test_get_name_patterns_returns_list():
    patterns = get_name_patterns("building_mosque")
    assert isinstance(patterns, list)


def test_get_rules_by_category_filters_correctly():
    admin = get_rules_by_category("admin_boundaries")
    assert len(admin) >= 1
    assert all(r["category_group"] == "admin_boundaries" for r in admin.values())


def test_get_export_family_returns_str():
    assert isinstance(get_export_family("building_house"), str)


# ── 4. Loader: dosyasız / bozuk JSON / yanlış toplevel tip ───────────────────
def test_load_rules_raises_import_error_when_file_missing(tmp_path, monkeypatch):
    """_DATA_FILE bulunamazsa anlamlı ImportError vermeli."""
    monkeypatch.setattr(
        "src.config.tag_rules._DATA_FILE",
        tmp_path / "does_not_exist.json",
    )
    with pytest.raises(ImportError, match="tag_rules.json not found"):
        _load_rules()


def test_load_rules_raises_import_error_on_invalid_json(tmp_path, monkeypatch):
    bad = tmp_path / "tag_rules.json"
    bad.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr("src.config.tag_rules._DATA_FILE", bad)
    with pytest.raises(ImportError, match="not valid JSON"):
        _load_rules()


def test_load_rules_raises_when_toplevel_not_object(tmp_path, monkeypatch):
    bad = tmp_path / "tag_rules.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setattr("src.config.tag_rules._DATA_FILE", bad)
    with pytest.raises(ImportError, match="must be a JSON object"):
        _load_rules()


def test_load_rules_raises_when_rule_value_not_object(tmp_path, monkeypatch):
    bad = tmp_path / "tag_rules.json"
    bad.write_text('{"bogus_rule": "not_an_object"}', encoding="utf-8")
    monkeypatch.setattr("src.config.tag_rules._DATA_FILE", bad)
    with pytest.raises(TypeError, match="must be an object"):
        _load_rules()


# ── 5. Tüm yüklü kuralların gerçek şema validasyonundan geçtiği invariant ───
def test_every_loaded_rule_passes_schema_validation():
    """TAG_RULES zaten import'ta validasyondan geçti; smoke için tekrar."""
    for rule_code, rule in TAG_RULES.items():
        _validate_rule(rule_code, rule)
