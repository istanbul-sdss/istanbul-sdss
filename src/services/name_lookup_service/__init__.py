"""
src/services/name_lookup_service — Reverse / name-based OSM lookup.

This package was a 1,800-line single .py file (`name_lookup_service.py`)
through commit f0b0618; the audit flagged it as the top maintainability
debt after tag_rules.py. The file split was done in C1 without altering
the public API — every existing import (`from src.services.name_lookup_service
import …`) keeps working because this `__init__.py` re-exports the same
symbols from sub-modules.

Layout (linear dependency: _scoring → _pools → _matchers; _tag_compat parallel):

  _scoring.py    Pure scoring math + input cleaning (no internal deps).
                 _score, _score_variants, _classify, _extract_name_variants,
                 _is_empty_input, JACCARD_EXPONENT, AMBIGUITY_DELTA,
                 MIRROR_COLUMNS_TR, _ALT_NAME_COLUMNS, _EMPTY_INPUT_LITERALS

  _tag_compat.py OSM tag compatibility evaluator + ranking + UI labels.
                 _check_tag_compat, _COMPAT_RANK, _TAG_MATCH_TR, _TAG_SCORE_MAP

  _pools.py      Candidate dataclasses + pool builders + heavy prepare entries.
                 _Candidate, _UniversalCandidate, PreparedPools, UniversalPool,
                 prepare_pools, prepare_universal_pool, _build_tier{1,2}_*,
                 _enrich_*, _fetch_*, _build_place_stopwords, _KEEP_TAG_COLUMNS,
                 TIER1/TIER2/MIXED_DEFAULT_THRESHOLD

  _matchers.py   Cascade matchers + mixed-list matcher + result types.
                 match_names, match_mixed_list, run_name_lookup,
                 NameLookupResult, MixedLookupResult, _ScoreBreakdown,
                 _emit_row, _emit_mixed_row, _best_matches,
                 _osm_category_label, _category_label_tr,
                 _mahalle_match, _normalize_mahalle, _strip_place_safely,
                 _get_rule_view, _OSM_CAT_KEY_PREFERENCE, _MAHALLE_NOISE

Two-tier cascade overview (was the original module docstring):
    Tier 1 (precision-first): Existing pipeline output for the chosen
        (district, rule_code) — POIs OSM-tagged correctly for that
        category. High signal-to-noise. Tokenization uses category-
        specific stopwords.
    Tier 2 (recall booster, opt-in): All named features inside the
        district boundary, EXCLUDING those already matched in Tier 1.
        Catches mistagged or category-less records (e.g. a pharmacy
        registered as `building=yes` with name "Şifa Eczanesi").
        Tokenization is LITE (generic stopwords only) on BOTH sides.
    Tier 3: Inputs that no tier could match → "Not found".

Scoring is `token_set_ratio × √jaccard`. The Jaccard term punishes
asymmetric matches like {anka} vs {anka, sanat} that token_set_ratio
otherwise scores 100; it leaves symmetric matches like {sifa} vs {sifa}
untouched.

Public entrypoints:
    prepare_pools(...)           — single-mode pool prep (fetch + tokenize)
    match_names(...)             — single-mode cascade against prepared pools
    run_name_lookup(...)         — convenience: prepare + match in one call
    prepare_universal_pool(...)  — mixed-mode pool prep (one Overpass fetch)
    match_mixed_list(...)        — mixed-mode auto-detect per row
"""
from __future__ import annotations

# Re-export sub-module public API. External callers
# (`from src.services.name_lookup_service import X`) keep working unchanged.
# Private symbols (leading underscore) are also re-exported because the test
# suite imports several of them as faux-public fixtures (_Candidate,
# _UniversalCandidate, _is_empty_input).
from ._matchers import (
    # Public result types + entrypoints (the 11 symbols pages/tests use):
    MIXED_DEFAULT_THRESHOLD,
    TIER1_DEFAULT_THRESHOLD,
    TIER2_DEFAULT_THRESHOLD,
    MixedLookupResult,
    NameLookupResult,
    PreparedPools,
    UniversalPool,
    match_mixed_list,
    match_names,
    prepare_pools,
    prepare_universal_pool,
    run_name_lookup,
    # Private but test-imported (kept stable across the refactor):
    _Candidate,
    _UniversalCandidate,
    _is_empty_input,
)

__all__ = [
    "MIXED_DEFAULT_THRESHOLD",
    "TIER1_DEFAULT_THRESHOLD",
    "TIER2_DEFAULT_THRESHOLD",
    "MixedLookupResult",
    "NameLookupResult",
    "PreparedPools",
    "UniversalPool",
    "match_mixed_list",
    "match_names",
    "prepare_pools",
    "prepare_universal_pool",
    "run_name_lookup",
]
