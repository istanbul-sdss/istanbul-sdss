"""
name_lookup_service._scoring — pure scoring math + input cleaning.

This sub-module is the "leaf" of the package dep graph: it depends only on
src.config.name_lookup_rules (for normalize_tr) and rapidfuzz; nothing else
inside the package imports from any sibling module. Splitting it out makes
the asymmetry-penalty math reviewable without scrolling through 1.8 kloc of
matcher orchestration.

Symbols:
  JACCARD_EXPONENT        — α in token_set_ratio × jaccard^α (default 0.5)
  AMBIGUITY_DELTA         — gap below which top-2 are flagged Ambiguous
  MIRROR_COLUMNS_TR       — pipeline-schema column list (used by row emitters
                            in matchers; kept here as the canonical mirror)
  _ALT_NAME_COLUMNS       — OSM tag fields scanned for alternate name forms
  _EMPTY_INPUT_LITERALS   — strings the input cleaner treats as "no value"
  _is_empty_input(value)  — Excel/CSV "blank cell" predicate
  _extract_name_variants  — primary + alt-name strings for a candidate row
  _score                  — score one pair (tokens × canonical)
  _score_variants         — best score across a candidate's name variants
  _classify               — Match Status verdict from best/runner_up/threshold
"""
from __future__ import annotations

import pandas as pd
from rapidfuzz import fuzz

from src.config.name_lookup_rules import normalize_tr

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
# Asymmetry-penalty exponent applied to Jaccard.
# 0.0 = no penalty (raw token_set_ratio)
# 0.5 = sqrt(jaccard) — moderate (default; calibrated against real data)
# 1.0 = full Jaccard penalty
JACCARD_EXPONENT = 0.5

# Score window between best and 2nd-best below which we flag Ambiguous
# — only triggers when ≥2 candidates clear the acceptance threshold.
AMBIGUITY_DELTA = 5

# Tier 1 / Tier 2 column expected to mirror pipeline output schema.
MIRROR_COLUMNS_TR = [
    "OSM Tipi", "OSM ID", "Ad",
    "Kategori", "Alt Kategori", "Kategori (TR)", "Kural Kodu",
    "Güven", "Eşleşme Nedeni",
    "Enlem", "Boylam", "Mahalle", "Sınır Durumu",
    "Tesis", "Sağlık Tipi", "Bina Tipi", "Dükkan", "Din",
    "Alan (m²)", "Kat Sayısı",
]

# OSM tag columns consulted for alternate name forms when scoring candidates.
# A POI registered with a formal name in the user's input list often appears
# in OSM under a different field — bilingual (`name:tr`), colloquial
# (`loc_name`), shorthand (`short_name`), or chain (`brand`/`operator`).
# Including all of these as searchable token sources directly improves recall
# without changing the matching algorithm.
_ALT_NAME_COLUMNS = [
    "name:tr", "name:en",
    "alt_name", "loc_name", "official_name", "short_name",
    "brand", "operator",
]


# Excel/CSV reader'larından gelen "boş hücre" senaryolarını tek noktada filtrele.
# Hem `pd.isna(val)` (gerçek NaN) hem de literal "nan"/"none"/"null" string
# (bazı reader'lar NaN'ı string'e çeviriyor) hem de boşluk-only girdiyi yutar.
_EMPTY_INPUT_LITERALS = frozenset({"", "nan", "none", "null", "n/a", "na", "-", "—"})


# ─────────────────────────────────────────────────────────────────────────────
# INPUT CLEANING
# ─────────────────────────────────────────────────────────────────────────────
def _is_empty_input(value) -> bool:
    """Bir arama girdisi olarak değerlendirilmemesi gereken değer mi?"""
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    s = str(value).strip().lower()
    return s in _EMPTY_INPUT_LITERALS


def _extract_name_variants(row) -> list[str]:
    """
    Return all non-empty distinct name strings for a candidate row, in
    preference order: primary `Ad` first, then `_ALT_NAME_COLUMNS`.

    Dedup is by normalize_tr(value) so trivially-different writings
    ("Şifa Eczanesi" vs "ŞİFA ECZANESİ") collapse to one variant.
    Backward-compatible: rows lacking alt-name columns yield [primary].
    """
    raws: list[str] = []
    seen: set[str] = set()

    primary = row.get("Ad")
    if primary is not None and not (isinstance(primary, float) and pd.isna(primary)):
        s = str(primary).strip()
        if s:
            raws.append(s)
            seen.add(normalize_tr(s))

    for col in _ALT_NAME_COLUMNS:
        v = row.get(col)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        s = str(v).strip()
        if not s:
            continue
        norm = normalize_tr(s)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        raws.append(s)
    return raws


# ─────────────────────────────────────────────────────────────────────────────
# SCORING
# ─────────────────────────────────────────────────────────────────────────────
def _score(
    input_tokens: set[str],
    cand_tokens: set[str],
    input_canonical: str,
    cand_canonical: str,
) -> tuple[float, set[str]]:
    """
    Returns (score, common_tokens).

    score = token_set_ratio(input_canonical, cand_canonical) × jaccard^α

    The Jaccard penalty fixes a known false-positive pattern in
    token_set_ratio: when one side's tokens are a strict subset of the
    other's and the intersection equals the smaller side, the algorithm
    scores 100. Real-world examples this used to mis-score:

        {anka}            vs {anka, sanat}    → was 100, now 71 (Possible)
        {acibadem, cadde} vs {cadde}          → was 100, now 71
        {pak}             vs {pak, berber}    → was 100, now 58 (Not found)

    Symmetric matches keep their score:
        {sifa}            vs {sifa}           → 100 (unchanged)
        {yildiz}          vs {yildiz}         → 100 (unchanged)
    """
    if not input_tokens or not cand_tokens:
        return 0.0, set()
    common = input_tokens & cand_tokens
    union  = input_tokens | cand_tokens
    if not common or not union:
        return 0.0, set()
    base = float(fuzz.token_set_ratio(input_canonical, cand_canonical))
    jaccard = len(common) / len(union)
    return base * (jaccard ** JACCARD_EXPONENT), common


def _score_variants(
    input_tokens: set[str],
    input_canonical: str,
    variants: list[tuple[set[str], str]],
) -> tuple[float, set[str]]:
    """
    Score input against every name variant of a candidate; return the best.

    Variants come from `name`, `name:tr`, `alt_name`, `loc_name`,
    `official_name`, `short_name`, `brand`, `operator`. A POI's input form
    in the user list often matches only one of these — taking the max
    boosts recall without changing the matching algorithm.

    Each variant is independently pre-filtered (cheap disjoint check) before
    the expensive token_set_ratio call, mirroring `_best_matches` semantics.
    """
    best_score = 0.0
    best_common: set[str] = set()
    if not input_tokens or not variants:
        return best_score, best_common
    for cd_tokens, cd_canonical in variants:
        if not cd_tokens:
            continue
        if input_tokens.isdisjoint(cd_tokens):
            if not any(t in cd_canonical for t in input_tokens if len(t) >= 4):
                continue
        s, common = _score(input_tokens, cd_tokens, input_canonical, cd_canonical)
        if s > best_score:
            best_score = s
            best_common = common
    return best_score, best_common


def _classify(
    best: float,
    runner_up: float,
    threshold: float,
    n_above_threshold: int,
) -> str:
    """
    Match Status decision matrix:
        best <= 0                                                    → Not found
        best >= threshold AND n_above ≥ 2 AND gap < AMBIGUITY_DELTA  → Ambiguous
        best >= threshold                                            → Matched
        otherwise                                                    → Possible match

    P4 fix: previously a single perfect match could be flagged Ambiguous
    because the runner-up gap math triggered against zero. We now require
    ≥2 candidates above threshold for Ambiguous, eliminating the
    spurious flagging of clean single-winner rows.
    """
    if best <= 0:
        return "Not found"
    if best >= threshold:
        if n_above_threshold >= 2 and (best - runner_up) < AMBIGUITY_DELTA:
            return "Ambiguous"
        return "Matched"
    return "Possible match"
