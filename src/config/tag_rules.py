"""
src/config/tag_rules.py — Tag-based entity rule registry.

Rule data lives in the sibling file `tag_rules.json` (single source of truth).
Previously this module held all 97 rules as a 1.3 kloc Python dict literal;
that form made code review noisy (every label/strict_tags change buried in
context) and discouraged non-Python contributors from touching it.

To **edit** an existing rule
  → open `src/config/tag_rules.json` and modify the rule's object. Schema
    validation runs at every import; a missing/mis-typed field raises an
    `ImportError`/`TypeError` with a precise rule + field pointer.

To **add** a new rule
  1. Add a new object in `tag_rules.json` keyed by the rule code
     (e.g. `"my_new_category": { … }`)
  2. All required keys listed in `_REQUIRED` below must be present.
  3. Run the test suite — `tests/test_tag_rules_loader.py` will exercise
     the schema validation and cross-check the count against
     `category_registry.py`.

`NAME_PATTERNS` (an organisational dict of reusable name-token lists) is
kept inline here for backward import compatibility. It is **not** the
authoritative source for rule fields any longer — the JSON contains the
fully-resolved name pattern lists per rule. If you change `NAME_PATTERNS`,
update the relevant rules' `name_patterns` arrays in the JSON to match.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ── Reusable name-token lists (organisational; not currently consumed by
#    other modules but exported for stability across this refactor) ────────
NAME_PATTERNS: dict[str, list[str]] = {
    "school":         ["okul", "school", "lise", "ilkokul", "ortaokul",
                       "kolej", "koleji"],
    "university":     ["üniversite", "universit"],
    "kindergarten":   ["anaokul", "kindergarten", "kreş", "kres"],
    "hospital":       ["hastane", "hospital", "tıp merkezi", "tip merkezi",
                       "medical"],
    "mosque":         ["cami", "camii", "mescit", "mosque"],
    "church":         ["church", "kilise"],
    "synagogue":      ["synagogue", "sinagog"],
    "museum":         ["müze", "muze", "museum"],
    "station":        ["istasyon", "station", "gar"],
    "pharmacy":       ["eczane", "pharmacy"],
    "park":           ["park"],
    "library":        ["kütüphane", "kutuphane", "library"],
    "bank":           ["banka", "bank"],
    "post_office":    ["postane", "ptt", "post office"],
    "theatre":        ["tiyatro", "theatre", "theater"],
    "cinema":         ["sinema", "cinema"],
    "arts_centre":    ["kültür merkezi", "kultur merkezi", "sanat merkezi",
                       "arts centre"],
    "ferry_terminal": ["iskele", "iskelesi", "pier", "ferry"],
}

_DATA_FILE = Path(__file__).with_name("tag_rules.json")

# Required fields + expected runtime type. `strict_tags` is polymorphic:
# dict for the AND case (most rules) or list-of-dicts for OR-of-AND
# (e.g. assembly_point which accepts emergency=assembly_point OR
# amenity=assembly_point OR amenity=emergency_assembly_point).
_REQUIRED: dict[str, type | tuple[type, ...]] = {
    "category_group":             str,
    "subcategory":                str,
    "label_tr":                   str,
    "geometry_expected":          list,
    "query_mode":                 str,
    "query_tags":                 list,
    "strict_tags":                (dict, list),
    "support_tags":               dict,
    "name_patterns":              list,
    "allow_name_fallback":        bool,
    "allow_building_yes_mapping": bool,
    "collect_unresolved":         bool,
    "export_family":              str,
}

# Optional fields (currently used by a small number of rules; presence is
# permitted but not required). Type still validated when present.
_OPTIONAL: dict[str, type | tuple[type, ...]] = {
    "accept_query_tag_match":  bool,
    "query_tag_match_score":   int,
}


def _validate_rule(rule_code: str, rule: dict[str, Any]) -> None:
    for key, expected_type in _REQUIRED.items():
        if key not in rule:
            raise ValueError(
                f"tag_rules.json: rule '{rule_code}' is missing required "
                f"field '{key}'"
            )
        if not isinstance(rule[key], expected_type):
            raise TypeError(
                f"tag_rules.json: rule '{rule_code}' field '{key}' has type "
                f"{type(rule[key]).__name__}, expected "
                f"{getattr(expected_type, '__name__', expected_type)}"
            )
    for key, expected_type in _OPTIONAL.items():
        if key in rule and not isinstance(rule[key], expected_type):
            raise TypeError(
                f"tag_rules.json: rule '{rule_code}' optional field '{key}' "
                f"has type {type(rule[key]).__name__}, expected "
                f"{getattr(expected_type, '__name__', expected_type)}"
            )
    # Unknown keys are not fatal — keep room for documented experimentation —
    # but we don't suppress them either; future schema additions just need to
    # update _REQUIRED or _OPTIONAL above.


def _load_rules() -> dict[str, dict[str, Any]]:
    try:
        with _DATA_FILE.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        raise ImportError(
            f"tag_rules.json not found at {_DATA_FILE} — rule registry "
            f"cannot load. Restore the file from version control."
        ) from exc
    except json.JSONDecodeError as exc:
        raise ImportError(
            f"tag_rules.json is not valid JSON: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ImportError(
            f"tag_rules.json must be a JSON object at the top level "
            f"(got {type(data).__name__})"
        )

    for rule_code, rule in data.items():
        if not isinstance(rule, dict):
            raise TypeError(
                f"tag_rules.json: rule '{rule_code}' must be an object, "
                f"got {type(rule).__name__}"
            )
        _validate_rule(rule_code, rule)

    return data


TAG_RULES: dict[str, dict[str, Any]] = _load_rules()


# ── HELPER FUNCTIONS (unchanged from pre-refactor; the public API stays
#    stable so the ~10 callers across src/services and src/optimizer keep
#    working) ───────────────────────────────────────────────────────────────

def get_rule(rule_code: str) -> dict:
    if rule_code not in TAG_RULES:
        raise ValueError(f"Geçersiz rule code: {rule_code}")
    return TAG_RULES[rule_code]


def is_valid_rule_code(rule_code: str) -> bool:
    return rule_code in TAG_RULES


def get_query_tags(rule_code: str) -> list[dict]:
    return get_rule(rule_code).get("query_tags", [])


def get_name_patterns(rule_code: str) -> list[str]:
    return get_rule(rule_code).get("name_patterns", [])


def get_rules_by_category(category_group: str) -> dict[str, dict]:
    return {
        k: v
        for k, v in TAG_RULES.items()
        if v.get("category_group") == category_group
    }


def get_export_family(rule_code: str) -> str:
    return get_rule(rule_code).get("export_family", "generic")
