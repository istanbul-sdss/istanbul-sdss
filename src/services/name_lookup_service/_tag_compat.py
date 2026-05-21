"""
name_lookup_service._tag_compat — OSM tag compatibility evaluation.

When a candidate is found by name match, this module answers the question
"do this candidate's actual OSM tags fit the rule we're searching for?".
That answer becomes both a tie-breaker (a tag-aligned 80 beats an unrelated
80) and a sub-score in the user-facing breakdown.

Symbols:
  _check_tag_compat(payload, rule_code)
      → str in {"match","support","mismatch","unknown"}.
      Handles `strict_tags` as either a single AND'd dict or a list of
      OR'd AND-dicts (assembly_point and 3 other rules use the list form).
      Multi-value `expected = [v1, v2]` is matched against any.
  _COMPAT_RANK            — int ordering for tie-break sort
                            (lower = better; match=0, mismatch=3)
  _TAG_MATCH_TR           — Turkish-labelled emoji equivalent
                            (UI translation map; rendered in mixed-mode rows)
  _TAG_SCORE_MAP          — numeric weight for the "Why Matched" breakdown
                            (rendered in the score-explainer column)

This file depends only on `src.config.tag_rules.get_rule` and pandas (for
NaN handling). It does NOT import from any other name_lookup_service
sibling — kept leaf so refactor noise stays low.
"""
from __future__ import annotations

import pandas as pd

from src.config.tag_rules import get_rule

# Tag-compat ranking — used to break score ties (Fix 1).
# Lower is better. A tag-aligned candidate at score 100 wins over an
# unrelated 100 (e.g. neighborhood "Moda" vs park "Moda Parkı").
_COMPAT_RANK = {"match": 0, "support": 1, "unknown": 2, "mismatch": 3}


_TAG_MATCH_TR = {
    "match":    "✅ Uyumlu",
    "support":  "⚠️ Destekleyici",
    "mismatch": "❌ Çelişkili",
    "unknown":  "— (etiket yok)",
}


# Tag uyum durumunu sayısallaştır — kullanıcıya "neden 87?" sorusunda
# tag bileşeninin payını gösterir. Skor değil sıralama; mantıksal
# sayıdır (compat_rank != bu skor).
_TAG_SCORE_MAP = {
    "match":    100.0,
    "support":  70.0,
    "unknown":  50.0,
    "mismatch": 0.0,
}


def _check_tag_compat(payload: dict, rule_code: str) -> str:
    """
    Compare candidate's OSM tag values against rule's strict_tags + support_tags.

    `strict_tags` may be:
      - dict {key: value | [values]}    — single AND'd requirement set
      - list[dict]                      — OR'd alternatives (e.g. building_mosque)
                                          where each dict is an AND'd requirement
    `support_tags` is always a single dict.

    Returns one of:
        "match"      ✅  candidate satisfies any strict alternative
        "support"    ⚠️  candidate has supporting (but not strict) tags
        "mismatch"   ❌  candidate has at least one strict-tag KEY with a
                         contradicting value AND none of the alternatives matched
        "unknown"    —   no relevant tags present (most common for plain
                         name-only OSM rows)
    """
    rule = get_rule(rule_code)
    strict = rule.get("strict_tags") or {}
    support = rule.get("support_tags") or {}

    def _normalize_target(v) -> list[str]:
        if isinstance(v, list):
            return [str(x).lower() for x in v]
        return [str(v).lower()]

    def _cand_val(key: str) -> str | None:
        v = payload.get(key)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        sv = str(v).strip().lower()
        return None if (not sv or sv == "nan") else sv

    def _evaluate_strict_alternative(alt: dict) -> tuple[bool, bool]:
        """
        Evaluate a single AND'd requirement set.
        Returns (all_present_match, any_contradiction).
        all_present_match = True iff every key present in candidate has a
        matching value AND at least one key was actually present.
        """
        any_present = False
        all_match = True
        any_contradict = False
        for key, expected in alt.items():
            cv = _cand_val(key)
            if cv is None:
                all_match = False  # missing required key — incomplete match
                continue
            any_present = True
            if cv not in _normalize_target(expected):
                all_match = False
                any_contradict = True
        return (any_present and all_match), any_contradict

    # Normalize strict to a list of alternatives
    alternatives = strict if isinstance(strict, list) else [strict]
    alternatives = [a for a in alternatives if a]  # drop empties

    has_match = False
    has_contradiction = False
    for alt in alternatives:
        m, c = _evaluate_strict_alternative(alt)
        if m:
            has_match = True
            break
        if c:
            has_contradiction = True

    if has_match:
        return "match"
    if has_contradiction:
        return "mismatch"

    # Support tags
    for key, expected in (support or {}).items():
        cv = _cand_val(key)
        if cv is None:
            continue
        if cv in _normalize_target(expected):
            return "support"

    return "unknown"
