from __future__ import annotations

from typing import Any

import pandas as pd

from src.config.tag_rules import TAG_RULES, get_name_patterns, get_rule

EMPTY_LIKE_VALUES = {"", "nan", "none", "null"}


def normalize_value(value: Any) -> str:
    """
    Tekil bir değeri güvenli biçimde normalize eder.
    """
    if pd.isna(value):
        return ""

    text = str(value).strip().lower()
    if text in EMPTY_LIKE_VALUES:
        return ""

    return text


def row_to_normalized_dict(row: Any) -> dict[str, str]:
    """
    pandas row / dict benzeri girdiyi normalize edilmiş sözlüğe çevirir.
    """
    if isinstance(row, pd.Series):
        raw = row.to_dict()
    elif isinstance(row, dict):
        raw = row
    else:
        raw = dict(row)

    return {str(k): normalize_value(v) for k, v in raw.items()}


def has_meaningful_value(value: Any) -> bool:
    """
    Değer anlamlı biçimde dolu mu?
    """
    return normalize_value(value) != ""


def match_tag_condition(row_dict: dict[str, str], key: str, expected: Any) -> bool:
    """
    Tek bir tag koşulunu kontrol eder.

    Kurallar:
    - expected=True ise kolonun dolu olması yeterlidir
    - aksi halde normalize edilmiş eşitlik aranır
    """
    actual = row_dict.get(key, "")

    if expected is True:
        return actual != ""

    return actual == normalize_value(expected)


def match_all_conditions(row_dict: dict[str, str], conditions: dict[str, Any]) -> bool:
    """
    Tüm koşullar aynı anda sağlanıyor mu?
    """
    if not conditions:
        return False

    return all(match_tag_condition(row_dict, key, expected) for key, expected in conditions.items())


def match_strict_tags(row_dict: dict[str, str], strict_tags: Any) -> bool:
    """
    strict_tags birden fazla geçerli tag kombinasyonunu destekler.

    Kabul edilen biçimler:
      • dict (klasik): tüm anahtarlar AND olarak eşleşmeli (eski davranış)
      • list[dict] (OR-of-AND): herhangi bir dict tam eşleşirse strict sayılır

    Örnek — assembly_point için 3 alternatif strict tanımı:
        "strict_tags": [
            {"emergency": "assembly_point"},
            {"amenity":   "assembly_point"},
            {"amenity":   "emergency_assembly_point"},
        ]

    OSM'de toplanma alanları üç farklı şekilde etiketlenebiliyor; bunların
    herhangi biri tek başına "strict" sayılmalı.
    """
    if not strict_tags:
        return False

    if isinstance(strict_tags, dict):
        return match_all_conditions(row_dict, strict_tags)

    if isinstance(strict_tags, (list, tuple)):
        return any(
            isinstance(option, dict) and match_all_conditions(row_dict, option)
            for option in strict_tags
        )

    return False


def _strict_tags_defined(strict_tags: Any) -> bool:
    """
    strict_tags anlamlı biçimde tanımlı mı? dict/list farkını normalize eder.
    """
    if not strict_tags:
        return False
    if isinstance(strict_tags, dict):
        return len(strict_tags) > 0
    if isinstance(strict_tags, (list, tuple)):
        return any(isinstance(opt, dict) and len(opt) > 0 for opt in strict_tags)
    return False


def count_support_matches(row_dict: dict[str, str], support_tags: dict[str, Any]) -> tuple[int, list[str]]:
    """
    Support tag eşleşme sayısını ve eşleşen support key'leri döner.
    """
    matched_keys: list[str] = []

    for key, expected in support_tags.items():
        if match_tag_condition(row_dict, key, expected):
            matched_keys.append(key)

    return len(matched_keys), matched_keys


def match_name_patterns(row_dict: dict[str, str], patterns: list[str]) -> tuple[bool, list[str]]:
    """
    name kolonu içinde pattern arar.
    """
    name_value = row_dict.get("name", "")
    if not name_value or not patterns:
        return False, []

    matched = [pattern for pattern in patterns if normalize_value(pattern) in name_value]
    return len(matched) > 0, matched


def match_any_query_tag(row_dict: dict[str, str], query_tags: Any) -> tuple[bool, dict[str, Any] | None]:
    """
    query_tags listesindeki HERHANGİ bir dict tam eşleşirse True döner.

    query_tags zaten union fetch'inin "neyi çekiyoruz" listesini tanımlıyor.
    Eğer bir satır herhangi bir query_tag kombinasyonunu karşılıyorsa — yani
    bu satır zaten bu rule'un fetch'i tarafından getirilebilir — o zaman
    rule'a ait sayılması en küçük makul varsayım. Aksi halde pipeline 3762
    bina çeker ve 1464'ünü resolved'a geri kalanını unresolved'a iter
    (Üsküdar "Konut - Genel" regresyonu).

    Dönen ikinci değer, eşleşen query_tag dict'i (reason/telemetri için).
    """
    if not query_tags or not isinstance(query_tags, (list, tuple)):
        return False, None

    for option in query_tags:
        if isinstance(option, dict) and option and match_all_conditions(row_dict, option):
            return True, option

    return False, None


def calculate_confidence_label(score: int) -> str:
    """
    Skora göre basit güven etiketi üretir.
    """
    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    if score >= 1:
        return "low"
    return "none"


def evaluate_rule(row: Any, rule_code: str) -> dict[str, Any]:
    """
    Bir satırı belirli bir rule'a göre değerlendirir.

    Dönen alanlar:
    - matched
    - score
    - confidence
    - reason
    - matched_support_keys
    - matched_name_patterns
    - used_strict
    - used_name_fallback
    """
    rule = get_rule(rule_code)
    row_dict = row_to_normalized_dict(row)

    strict_tags = rule.get("strict_tags", {}) or {}
    support_tags = rule.get("support_tags", {}) or {}
    allow_name_fallback = bool(rule.get("allow_name_fallback", False))
    name_patterns = get_name_patterns(rule_code)
    # Default: satır query_tags'ten herhangi birini tam karşılıyorsa rule'a
    # ait sayılır. Yalnızca explicit olarak False yaparsa rule opt-out eder.
    accept_query_tag_match = bool(rule.get("accept_query_tag_match", True))
    query_tags = rule.get("query_tags", []) or []
    # Çoğu umbrella rule'da query_tags içindeki formlar KANONIK alternatifler
    # (örn. building_residential için building=apartments/house/detached/terrace).
    # Bu yüzden default skor strict ile aynı (3 → medium confidence). Rule
    # bazında override edilebilir: assembly_point için leisure=park bir ipucu
    # olduğundan score=1 → low. Görmek için tag_rules.py'de
    # `query_tag_match_score: 1` kullan.
    query_tag_match_score = int(rule.get("query_tag_match_score", 3))

    strict_defined = _strict_tags_defined(strict_tags)
    strict_matched = match_strict_tags(row_dict, strict_tags) if strict_defined else False
    support_count, matched_support_keys = count_support_matches(row_dict, support_tags)
    name_matched, matched_name_patterns = match_name_patterns(row_dict, name_patterns)

    score = 0
    reason = "no_match"
    used_strict = False
    used_name_fallback = False

    if strict_matched:
        score += 3
        used_strict = True
        reason = "strict_match"

    if support_count > 0:
        score += support_count

    if allow_name_fallback and name_matched:
        score += 1
        used_name_fallback = True
        if reason == "no_match":
            reason = "name_fallback"

    # Matching logic:
    #   • strict_matched      → her zaman matched (en güçlü sinyal)
    #   • support + name      → ancak allow_name_fallback=True ise matched
    # support_count tek başına strict_defined=True iken matched'a yol açmaz;
    # strict_defined=False iken aşağıdaki blok bunu açıkça ele alır.
    # (Önceden 3. clause `strict_matched and support_count >= 0` vardı —
    # support_count her zaman >= 0 olduğu için 1. clause ile özdeş, ölü dal.)
    matched = strict_matched or (support_count > 0 and allow_name_fallback and name_matched)

    # strict tag yoksa support + name veya support tek başına bazı rule'lar için anlamlı olabilir
    if not strict_defined:
        if support_count > 0:
            matched = True
            reason = "support_match"
        elif allow_name_fallback and name_matched:
            matched = True
            reason = "name_fallback"

    # Son çare: satır rule'un kendi query_tags'ini karşılıyor mu?
    # Eşleşiyorsa, bu satır rule'un fetch'i tarafından getirilebilir demektir —
    # yani rule'a ait sayılmalı. Çoğu umbrella rule'da query_tags kanonik
    # alternatifleri içerdiği için skor strict ile aynı (medium). `assembly_point`
    # gibi filter-tipi rule'lar `query_tag_match_score: 1` ile override ederek
    # düşük güvenli bir ipucu olarak işaretler.
    if not matched and accept_query_tag_match and query_tags:
        query_hit, matched_option = match_any_query_tag(row_dict, query_tags)
        if query_hit:
            matched = True
            score += query_tag_match_score
            if reason == "no_match":
                reason = "query_tag_match"

    # Tag-only rule bump: Rule yazarı support_tags ve name_patterns tanımlamamışsa,
    # "kanonik tag match yeterli" demiş demektir — cross-validate edilecek başka
    # sinyal yok. Bu durumda strict (ve default-ağırlıklı query_tag) match'i FULL
    # confidence taşımalı. Kullanıcı geri bildirimi: "residential seçtim,
    # building=residential döndü, neden medium? high olmalı" — haklı; umbrella
    # rule'da ek doğrulama imkânı yok, primary tag tek ve yeterli sinyal.
    # assembly_point'in leisure=park query_tag_match'i bu bump'tan MUAF tutulur:
    # `query_tag_match_score: 1` override'ı "kanonik değil, hint" demek — öyle kalmalı.
    support_defined = bool(support_tags)
    tag_only_rule = not support_defined and not name_patterns
    if matched and tag_only_rule and score < 4:
        if reason == "strict_match" or reason == "query_tag_match" and query_tag_match_score >= 3:
            score = 4

    confidence = calculate_confidence_label(score if matched else 0)

    return {
        "rule_code": rule_code,
        "matched": matched,
        "score": score if matched else 0,
        "confidence": confidence,
        "reason": reason,
        "matched_support_keys": matched_support_keys,
        "matched_name_patterns": matched_name_patterns,
        "used_strict": used_strict,
        "used_name_fallback": used_name_fallback,
    }


def evaluate_multiple_rules(row: Any, rule_codes: list[str]) -> list[dict[str, Any]]:
    """
    Bir satırı birden fazla rule'a göre değerlendirir.
    """
    results = [evaluate_rule(row, rule_code) for rule_code in rule_codes]
    results.sort(
        key=lambda item: (
            item["matched"],
            item["score"],
            item["confidence"] == "high",
            item["confidence"] == "medium",
        ),
        reverse=True,
    )
    return results


def get_best_rule_match(row: Any, rule_codes: list[str] | None = None) -> dict[str, Any]:
    """
    Verilen satır için en iyi rule eşleşmesini döner.
    """
    if rule_codes is None:
        rule_codes = list(TAG_RULES.keys())

    results = evaluate_multiple_rules(row, rule_codes)

    for result in results:
        if result["matched"]:
            return result

    return {
        "rule_code": None,
        "matched": False,
        "score": 0,
        "confidence": "none",
        "reason": "no_match",
        "matched_support_keys": [],
        "matched_name_patterns": [],
        "used_strict": False,
        "used_name_fallback": False,
    }


def is_building_yes_record(row: Any) -> bool:
    """
    Satır building=yes mi?
    """
    row_dict = row_to_normalized_dict(row)
    return row_dict.get("building", "") == "yes"


def get_building_yes_candidate_rules() -> list[str]:
    """
    building=yes map etmede kullanılabilecek rule'ları döner.
    """
    candidates: list[str] = []

    for rule_code, rule in TAG_RULES.items():
        if rule.get("allow_building_yes_mapping", False):
            candidates.append(rule_code)

    return candidates


def map_building_yes_record(row: Any) -> dict[str, Any]:
    """
    building=yes bir kaydı uygun rule'lara map etmeye çalışır.
    """
    if not is_building_yes_record(row):
        return {
            "rule_code": None,
            "matched": False,
            "score": 0,
            "confidence": "none",
            "reason": "not_building_yes",
            "matched_support_keys": [],
            "matched_name_patterns": [],
            "used_strict": False,
            "used_name_fallback": False,
        }

    candidate_rules = get_building_yes_candidate_rules()
    best = get_best_rule_match(row, candidate_rules)

    if best["matched"]:
        best["reason"] = f"building_yes_mapped:{best['reason']}"
        return best

    return {
        "rule_code": "building_yes_unresolved",
        "matched": False,
        "score": 0,
        "confidence": "none",
        "reason": "building_yes_unresolved",
        "matched_support_keys": [],
        "matched_name_patterns": [],
        "used_strict": False,
        "used_name_fallback": False,
    }


def append_rule_match_columns(
    df: pd.DataFrame,
    rule_codes: list[str] | None = None,
    prefix: str = "rule_",
) -> pd.DataFrame:
    """
    DataFrame'e en iyi rule eşleşme kolonlarını ekler.
    """
    result = df.copy()

    if result.empty:
        result[f"{prefix}code"] = pd.Series(dtype="object")
        result[f"{prefix}matched"] = pd.Series(dtype="bool")
        result[f"{prefix}score"] = pd.Series(dtype="int")
        result[f"{prefix}confidence"] = pd.Series(dtype="object")
        result[f"{prefix}reason"] = pd.Series(dtype="object")
        return result

    matches = result.apply(lambda row: get_best_rule_match(row, rule_codes), axis=1)

    result[f"{prefix}code"] = matches.apply(lambda x: x["rule_code"])
    result[f"{prefix}matched"] = matches.apply(lambda x: x["matched"])
    result[f"{prefix}score"] = matches.apply(lambda x: x["score"])
    result[f"{prefix}confidence"] = matches.apply(lambda x: x["confidence"])
    result[f"{prefix}reason"] = matches.apply(lambda x: x["reason"])

    return result


def append_building_yes_mapping_columns(
    df: pd.DataFrame,
    prefix: str = "yes_map_",
) -> pd.DataFrame:
    """
    building=yes kayıtları için mapping sonucu kolonları ekler.
    """
    result = df.copy()

    if result.empty:
        result[f"{prefix}code"] = pd.Series(dtype="object")
        result[f"{prefix}matched"] = pd.Series(dtype="bool")
        result[f"{prefix}score"] = pd.Series(dtype="int")
        result[f"{prefix}confidence"] = pd.Series(dtype="object")
        result[f"{prefix}reason"] = pd.Series(dtype="object")
        return result

    matches = result.apply(lambda row: map_building_yes_record(row), axis=1)

    result[f"{prefix}code"] = matches.apply(lambda x: x["rule_code"])
    result[f"{prefix}matched"] = matches.apply(lambda x: x["matched"])
    result[f"{prefix}score"] = matches.apply(lambda x: x["score"])
    result[f"{prefix}confidence"] = matches.apply(lambda x: x["confidence"])
    result[f"{prefix}reason"] = matches.apply(lambda x: x["reason"])

    return result
