"""
name_lookup_service._matchers — cascade + mixed-list match orchestration.

Owns the two public matcher entrypoints (`match_names` for single-mode
cascade, `match_mixed_list` for mixed-mode auto-detect) plus the result
dataclasses they produce (`NameLookupResult`, `MixedLookupResult`,
`_ScoreBreakdown`) and the row-emitter helpers that mirror the pipeline
schema.

Dependency direction: this is the top of the package's internal stack.
It imports from `_scoring`, `_tag_compat`, and `_pools`; nothing under
`name_lookup_service/*.py` imports from here. The `__init__.py`
re-exports the public API of all sub-modules from here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd
from rapidfuzz import fuzz

from src.config.category_registry import CATEGORY_REGISTRY
from src.config.name_lookup_rules import (
    detect_category,
    normalize_tr,
    tokenize_for_match,
    tokenize_lite,
)
from src.logger import get_logger

# Sub-module: candidate dataclasses + pool builders + heavy prepare entries.
# Re-exported through __init__ so external callers keep their existing
# import paths. `noqa: F401` — these names are not used inside _matchers but
# are intentional re-exports for the top-level package + test imports.
from ._pools import (  # noqa: F401
    _KEEP_TAG_COLUMNS,
    MIXED_DEFAULT_THRESHOLD,
    TIER1_DEFAULT_THRESHOLD,
    TIER2_DEFAULT_THRESHOLD,
    PreparedPools,
    UniversalPool,
    _Candidate,
    _UniversalCandidate,
    prepare_pools,
    prepare_universal_pool,
)

# Sub-module: pure scoring math + input cleaning.
from ._scoring import (
    MIRROR_COLUMNS_TR,
    _classify,
    _is_empty_input,
    _score_variants,
)

# Sub-module: OSM tag-compatibility evaluation + ranking + UI labels.
from ._tag_compat import (
    _COMPAT_RANK,
    _TAG_MATCH_TR,
    _TAG_SCORE_MAP,
    _check_tag_compat,
)

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CASCADE MATCHER
# ─────────────────────────────────────────────────────────────────────────────
def _best_matches(
    input_tokens: set[str],
    input_canonical: str,
    candidates: list[_Candidate],
    top_k: int = 3,
) -> list[tuple[float, _Candidate, set[str]]]:
    """
    Score input against every candidate. Returns top_k descending.

    Each tuple is (score, candidate, common_tokens) so the caller can
    surface the matched tokens in diagnostic columns.
    """
    if not input_tokens or not candidates:
        return []
    scored: list[tuple[float, _Candidate, set[str]]] = []
    for cand in candidates:
        s, common = _score_variants(input_tokens, input_canonical, cand.variants)
        if s > 0:
            scored.append((s, cand, common))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top_k]


def _emit_row(
    input_name: str,
    matches: list[tuple[float, _Candidate, set[str]]],
    threshold: float,
    tier: int,
    *,
    in_tokens: set[str] | None = None,
    in_canonical: str | None = None,
) -> dict:
    """
    Build one output row — pipeline-mirror schema + match metadata.
    Empty matches → Not found.

    Single mode'da mahalle filtresi YOK ve Tier 1 adayları zaten kategorinin
    strict_tag'lerini taşıyor (rule-bazlı pipeline çıktısı), bu yüzden
    compat_raw = "match" varsayılır; Tier 2 (mistag) için "unknown".
    """
    base: dict = dict.fromkeys(MIRROR_COLUMNS_TR)
    base.update({
        "Girdi Ad":              input_name,
        "Eşleşme Durumu":        "Not found",
        "Eşleşme Skoru":         0.0,
        "Eşleşme Katmanı":       0,
        "Eşleşen Kelimeler":     "",
        "Skor: İsim":            None,
        "Skor: Jaccard":         None,
        "Skor: Tag":             None,
        "Skor: Mahalle":         None,
        "Eşleşme Açıklaması":    "—",
        "Alternatif Eşleşmeler": "",
    })

    if not matches:
        # Diagnostic: distinguish "input was unscoreable" from "no candidate
        # scored > 0". Without this users see a bare "Not found" with no
        # signal whether to retry, fix the input, or accept the gap.
        if in_tokens is not None and not in_tokens:
            base["Eşleşme Açıklaması"] = "input had no scoring tokens (empty or all stopwords)"
        else:
            base["Eşleşme Açıklaması"] = "no candidate matched any input token"
        return base

    best_score, best, common = matches[0]
    runner_score = matches[1][0] if len(matches) > 1 else 0.0
    n_above = sum(1 for s, _, _ in matches if s >= threshold)
    status = _classify(best_score, runner_score, threshold, n_above)

    base.update(best.payload)
    base.update({
        "Girdi Ad":          input_name,
        "Eşleşme Durumu":    status,
        "Eşleşme Skoru":     round(best_score, 1),
        "Eşleşme Katmanı":   tier,
        "Eşleşen Kelimeler": ", ".join(sorted(common)),
    })

    # Decomposed score breakdown (single mode):
    # Tier 1 → Pipeline çıktısı zaten strict-tag'li → "match" varsayılır.
    # Tier 2 → Mistag candidate; tag uyumu bilinmiyor → "unknown".
    # Tier 0 → Threshold altında near-miss; treat as unknown.
    if in_tokens is not None and in_canonical is not None and best.variants:
        compat_raw = "match" if tier == 1 else "unknown"
        breakdown = _compute_breakdown_from_variants(
            in_tokens=in_tokens,
            in_canonical=in_canonical,
            cand_variants=best.variants,
            common=common,
            compat_raw=compat_raw,
            mahalle_filter_used=False,    # single mode'da yok
            matched=True,
        )
        base.update({
            "Skor: İsim":         breakdown.name_similarity,
            "Skor: Jaccard":      breakdown.jaccard_pct,
            "Skor: Tag":          breakdown.tag_score,
            "Skor: Mahalle":      breakdown.mahalle_score,
            "Eşleşme Açıklaması": breakdown.explanation,
        })
        # When best < threshold (status = "Possible match"), prepend a quick
        # "near miss" hint so the user sees what they'd need to clear.
        if status == "Possible match":
            base["Eşleşme Açıklaması"] = (
                f"closest score {best_score:.0f} (threshold {threshold:.0f})"
                + (f" · {breakdown.explanation}"
                   if breakdown.explanation and breakdown.explanation != "—"
                   else "")
            )

    if len(matches) > 1:
        alts = [
            f"{m.payload.get('Ad', '?')} (skor={s:.0f})"
            for s, m, _ in matches[1:3]
        ]
        base["Alternatif Eşleşmeler"] = " · ".join(alts)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC RESULT TYPES (NameLookupResult/MixedLookupResult stay near the
# matcher functions that produce them; PreparedPools/UniversalPool live in
# _pools.py alongside their builders.)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class NameLookupResult:
    df:                pd.DataFrame
    tier1_count:       int
    tier2_count:       int
    not_found_count:   int
    ambiguous_count:   int
    candidate_pool_t1: int
    candidate_pool_t2: int


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC ENTRYPOINTS — match_names (single-mode cascade)
# ─────────────────────────────────────────────────────────────────────────────
def match_names(
    pools: PreparedPools,
    names: list[str],
    *,
    tier1_threshold: float = TIER1_DEFAULT_THRESHOLD,
    tier2_threshold: float = TIER2_DEFAULT_THRESHOLD,
    progress_cb: Callable | None = None,
) -> NameLookupResult:
    """
    Fast in-memory cascade against pre-built pools.

    Tier 1 input → tokenize_for_match(rule_code)   (full stopwords)
    Tier 2 input → tokenize_lite()                  (generic only,
                                                     same rule applied
                                                     to candidates)
    """
    def cb(msg: str) -> None:
        log.info(msg)
        if progress_cb:
            progress_cb(msg)

    rule_code = pools.rule_code

    # ── Row-preserving input cleaning ────────────────────────────────────
    # Boş/NaN-literal hücreleri ele (üretim Excel'lerinde sık karşılaşılır:
    # bazı reader'lar NaN'ı "nan" string'ine çeviriyor → arama girdisi olarak
    # değerlendirilmemeli). Aynı isim için tekrar skor hesabı yapmamak adına
    # iç dedup grupluyoruz; ama her input satırı için çıktıda ayrı bir
    # satır üretiyoruz (Input Row kolonu ile orijinal sıra korunur).
    cleaned_inputs: list[tuple[int, str]] = []  # (input_row_id, raw_name)
    for i, n in enumerate(names):
        if _is_empty_input(n):
            continue
        cleaned_inputs.append((i, str(n).strip()))

    # İç skor cache'i: aynı normalize_tr(n) için aynı pool sonucu çıkar.
    score_groups: dict[str, list[int]] = {}
    name_for_group: dict[str, str] = {}
    for input_id, raw in cleaned_inputs:
        key = normalize_tr(raw)
        score_groups.setdefault(key, []).append(input_id)
        name_for_group.setdefault(key, raw)

    cb(
        f"Input: {len(names)} raw, {len(cleaned_inputs)} non-empty "
        f"({len(score_groups)} unique names scored)"
    )

    rows: list[dict] = []
    t1_hits = t2_hits = ambig_hits = nf_hits = 0

    for key, input_ids in score_groups.items():
        input_name = name_for_group[key]
        # ── Tier 1 attempt (rule-aware tokenization) ─────────────────────
        t1_tokens = set(tokenize_for_match(input_name, rule_code))
        t1_canonical = " ".join(sorted(t1_tokens))
        m1 = _best_matches(t1_tokens, t1_canonical, pools.tier1_candidates)

        # ── Decide which match (if any) wins for this group ──────────────
        # Score grubu seviyesinde KARAR; sonra her input_id için aynı satır
        # şablonu üretilir (Input Row değeri farklı olur). Aksi halde aynı
        # isim+farklı satır kombinasyonunda dedup çalışır ve satır düşerdi.
        chosen_template: dict
        chosen_status_for_count: str

        if m1 and m1[0][0] >= tier1_threshold:
            chosen_template = _emit_row(
                input_name, m1, tier1_threshold, tier=1,
                in_tokens=t1_tokens, in_canonical=t1_canonical,
            )
            chosen_status_for_count = chosen_template["Eşleşme Durumu"]
            t1_hits += len(input_ids)
            if chosen_status_for_count == "Ambiguous":
                ambig_hits += len(input_ids)
        elif pools.tier2_candidates:
            t2_tokens = set(tokenize_lite(input_name))
            t2_canonical = " ".join(sorted(t2_tokens))
            m2 = _best_matches(t2_tokens, t2_canonical, pools.tier2_candidates)
            if m2 and m2[0][0] >= tier2_threshold:
                chosen_template = _emit_row(
                    input_name, m2, tier2_threshold, tier=2,
                    in_tokens=t2_tokens, in_canonical=t2_canonical,
                )
                # Tier 2 hits are by definition mistag candidates (high name
                # similarity but the OSM tag doesn't match the rule). Both
                # "Matched" and "Ambiguous" verdicts get reclassified to
                # "Possible mistag" so the dedicated tab catches all of
                # them — previously Ambiguous tier-2 hits were buried under
                # the "All results" tab only.
                if chosen_template["Eşleşme Durumu"] in ("Matched", "Ambiguous"):
                    chosen_template["Eşleşme Durumu"] = "Possible mistag"
                chosen_status_for_count = chosen_template["Eşleşme Durumu"]
                t2_hits += len(input_ids)
                if chosen_status_for_count == "Ambiguous":
                    ambig_hits += len(input_ids)
            else:
                chosen_template = (
                    _emit_row(input_name, m1, tier1_threshold, tier=1,
                              in_tokens=t1_tokens, in_canonical=t1_canonical)
                    if m1 else
                    _emit_row(input_name, [], tier1_threshold, tier=0)
                )
                nf_hits += len(input_ids)
        else:
            chosen_template = (
                _emit_row(input_name, m1, tier1_threshold, tier=1,
                          in_tokens=t1_tokens, in_canonical=t1_canonical)
                if m1 else
                _emit_row(input_name, [], tier1_threshold, tier=0)
            )
            nf_hits += len(input_ids)

        # Her input_id için satırın bir kopyasını üret — bu sayede orijinal
        # input listesi 1-1 temsil edilir.
        for input_id in input_ids:
            row = dict(chosen_template)
            row["Input Row"] = input_id
            rows.append(row)

    # Çıktı sırasını orijinal input sırasına göre sabitle (deterministik).
    rows.sort(key=lambda r: r.get("Input Row", 0))
    out_df = pd.DataFrame(rows)

    head_cols = ["Input Row", "Girdi Ad", "Eşleşme Durumu", "Eşleşme Skoru",
                 "Skor: İsim", "Skor: Jaccard", "Skor: Tag", "Skor: Mahalle",
                 "Eşleşme Açıklaması",
                 "Eşleşme Katmanı", "Eşleşen Kelimeler"]
    tail_cols = [c for c in out_df.columns
                 if c not in head_cols and c != "Alternatif Eşleşmeler"]
    out_df = out_df[head_cols + tail_cols + ["Alternatif Eşleşmeler"]]

    cb(
        f"Result: T1={t1_hits} · T2={t2_hits} · "
        f"Ambiguous={ambig_hits} · Not found={nf_hits}"
    )

    return NameLookupResult(
        df=out_df,
        tier1_count=t1_hits,
        tier2_count=t2_hits,
        not_found_count=nf_hits,
        ambiguous_count=ambig_hits,
        candidate_pool_t1=len(pools.tier1_candidates),
        candidate_pool_t2=len(pools.tier2_candidates),
    )


def run_name_lookup(
    ilce: str,
    cat_key: str,
    sub_key: str,
    names: list[str],
    *,
    enable_tier2: bool = True,
    tier1_threshold: float = TIER1_DEFAULT_THRESHOLD,
    tier2_threshold: float = TIER2_DEFAULT_THRESHOLD,
    progress_cb: Callable | None = None,
) -> NameLookupResult:
    """Convenience wrapper: prepare_pools → match_names. Not cached."""
    pools = prepare_pools(
        ilce=ilce, cat_key=cat_key, sub_key=sub_key,
        enable_tier2=enable_tier2, progress_cb=progress_cb,
    )
    return match_names(
        pools, names,
        tier1_threshold=tier1_threshold,
        tier2_threshold=tier2_threshold,
        progress_cb=progress_cb,
    )


# ═════════════════════════════════════════════════════════════════════════════
# MIXED-LIST MODE — auto-detect category per input row
# ═════════════════════════════════════════════════════════════════════════════
# Use case: assembly-point lists, BIMER POI lists, or any heterogeneous
# user-supplied set where each row may belong to a different OSM category
# (parks, mosques, schools, pharmacies …). The user uploads one list,
# system auto-classifies each row, fetches the district's full named-feature
# pool ONCE, and returns coordinates + neighborhood + category metadata for
# everything it can match.
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class MixedLookupResult:
    df:                   pd.DataFrame
    matched_count:        int
    tag_match_count:      int      # Matched AND tag aligned with detection
    tag_mismatch_count:   int      # Matched but candidate tags contradict
    not_detected_count:   int      # Detection failed → fuzzy fallback path
    not_found_count:      int
    candidate_pool_size:  int
    mahalle_filter_rows:  int = 0  # rows that supplied a mahalle hint
    mahalle_filter_empty: int = 0  # rows whose hinted mahalle had 0 candidates


# ─────────────────────────────────────────────────────────────────────────────
# OSM-Category inference for output
# ─────────────────────────────────────────────────────────────────────────────
_OSM_CAT_KEY_PREFERENCE = [
    "amenity", "leisure", "tourism", "historic", "shop", "office",
    "healthcare", "religion", "public_transport", "railway",
    "natural", "landuse", "man_made", "emergency", "highway", "building",
]


def _osm_category_label(payload: dict) -> str:
    """
    Pretty-print the candidate's actual OSM category from its tags.

    Picks the first non-empty tag from the preference order; demotes
    `building=yes` to a marker because that value carries no info.
    """
    for key in _OSM_CAT_KEY_PREFERENCE:
        v = payload.get(key)
        if v is None:
            continue
        if isinstance(v, float) and pd.isna(v):
            continue
        sv = str(v).strip()
        if not sv or sv.lower() == "nan":
            continue
        if key == "building" and sv.lower() == "yes":
            continue
        return f"{key}={sv}"
    if str(payload.get("building", "")).lower() == "yes":
        return "building=yes (untagged)"
    return "—"


def _category_label_tr(cat_key: str, sub_key: str) -> str:
    """Pretty Turkish label for the detected category."""
    cat = CATEGORY_REGISTRY.get(cat_key, {})
    icon = cat.get("icon", "")
    cat_label = cat.get("label_tr", cat_key)
    sub_label = sub_key
    for s in cat.get("subcategories", []):
        if s["key"] == sub_key:
            sub_label = s["label_tr"]
            break
    return f"{icon} {cat_label} / {sub_label}".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Per-rule token cache (lazy)
# ─────────────────────────────────────────────────────────────────────────────
def _strip_place_safely(tokens: set[str], place: set[str]) -> set[str]:
    """
    Subtract place stopwords from tokens, but fall back to the original
    set if stripping would leave nothing.

    Why the fallback: when a POI's discriminating name IS its neighborhood
    ("Moda Parkı", "Hürriyet Parkı"), both rule-strip and place-strip can
    collapse the token set to empty. Better to keep `{moda}` than wipe it.
    """
    stripped = tokens - place
    return stripped if stripped else tokens


def _get_rule_view(pool: UniversalPool, rule_code: str) -> list[list[tuple[set[str], str]]]:
    """
    Returns, for every candidate, a list of (rule_aware_tokens, canonical)
    — one entry per name variant (Ad, name:tr, alt_name…). Computed once
    per rule per pool, cached on the pool.

    Strips both the rule's category stopwords AND the pool's place
    stopwords (district + neighborhood names) so spurious prefixes
    don't tank the Jaccard ratio. Place stripping is "safe" — won't
    empty the token set.
    """
    cached = pool.rule_token_cache.get(rule_code)
    if cached is not None:
        return cached
    place = getattr(pool, "place_stopwords", set())
    view: list[list[tuple[set[str], str]]] = []
    for cand in pool.candidates:
        cand_view: list[tuple[set[str], str]] = []
        for raw in cand.raw_name_variants:
            toks = _strip_place_safely(
                set(tokenize_for_match(raw, rule_code)), place
            )
            if toks:
                cand_view.append((toks, " ".join(sorted(toks))))
        view.append(cand_view)
    pool.rule_token_cache[rule_code] = view
    return view




# ─────────────────────────────────────────────────────────────────────────────
# Neighborhood (mahalle) matching — used as candidate pre-filter
# ─────────────────────────────────────────────────────────────────────────────
# When the user supplies a per-row mahalle hint, we restrict the candidate
# pool to features assigned to that mahalle BEFORE running the fuzzy match.
# This collapses 10K candidates → ~100, eliminating the dominant source of
# false positives (same name in another mahalle).
_MAHALLE_NOISE = {"mahallesi", "mahalle", "mah", "mh"}


def _normalize_mahalle(s: str | None) -> set[str]:
    """Mahalle name → tokenized set, dropping the universal 'Mahallesi' suffix."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return set()
    norm = normalize_tr(str(s))
    if not norm:
        return set()
    return {t for t in norm.split()
            if len(t) >= 2 and t not in _MAHALLE_NOISE}


def _mahalle_match(input_mh: str | None, cand_mh: str | None) -> bool:
    """
    Tokenize both sides, compare as sets. True when they share at least one
    distinguishing token. Handles "Caferağa" ↔ "Caferağa Mahallesi" ↔
    "CAFERAGA MAH." cleanly.
    """
    a = _normalize_mahalle(input_mh)
    if not a:
        return True   # No input hint → don't filter
    b = _normalize_mahalle(cand_mh)
    if not b:
        return False  # Hint exists but candidate has no mahalle → reject
    return bool(a & b)


# ─────────────────────────────────────────────────────────────────────────────
# Mixed-list matcher
# ─────────────────────────────────────────────────────────────────────────────


def match_mixed_list(
    pool: UniversalPool,
    names: list[str],
    *,
    neighborhoods: list[str | None] | None = None,
    threshold: float = MIXED_DEFAULT_THRESHOLD,
    progress_cb: Callable | None = None,
) -> MixedLookupResult:
    """
    For each input name:
        1. detect_category → rule_code (or None)
        2. (NEW) If a per-row mahalle hint was supplied, restrict candidates
           to that mahalle BEFORE scoring — collapses pool ~10K → ~100 and
           eliminates the dominant false-positive class (same name elsewhere).
        3. Tokenize input + every candidate with that rule's stopwords
           (lite if no detection)
        4. Score with Jaccard penalty, pick top match
        5. Annotate with detected/OSM category + tag-compat + mahalle-filter
           verdicts.

    `neighborhoods` is parallel to `names`. None entries mean "no hint" for
    that row (no mahalle filter applied — full pool searched).
    """
    def cb(msg: str) -> None:
        log.info(msg)
        if progress_cb:
            progress_cb(msg)

    # ── Pair names with their mahalle hints, then dedup keeping the hint ──
    if neighborhoods is None:
        neighborhoods = [None] * len(names)
    if len(neighborhoods) != len(names):
        raise ValueError(
            f"neighborhoods length ({len(neighborhoods)}) must equal "
            f"names length ({len(names)})"
        )

    # ── Row-preserving input cleaning ────────────────────────────────────
    # Aynı "Aile Eczanesi" Caferağa'da ve Fenerbahçe'de varsa İKİ AYRI satır
    # olarak kalmalı. Eski dedup anahtarı sadece normalize_tr(n) idi → mahalle
    # hint'i göz ardı edildiği için ikinci satır siliniyordu (kullanıcı bulgusu).
    # Yeni anahtar: (normalize_tr(name), normalize_mahalle_token(mahalle)).
    # Aynı isim+mahalle çifti gerçekten redundant — onu dedup ediyoruz; ama
    # her input_row için çıktıda ayrı bir row üretiyoruz.
    cleaned_inputs: list[tuple[int, str, str | None]] = []   # (id, name, mh)
    for i, (n, mh) in enumerate(zip(names, neighborhoods)):
        if _is_empty_input(n):
            continue
        # Mahalle hint'i de boş literal olabilir; saklarken normalize edelim.
        mh_clean = None if _is_empty_input(mh) else str(mh).strip()
        cleaned_inputs.append((i, str(n).strip(), mh_clean))

    score_groups: dict[tuple[str, frozenset[str]], list[int]] = {}
    name_for_group: dict[tuple[str, frozenset[str]], tuple[str, str | None]] = {}
    for input_id, raw_name, raw_mh in cleaned_inputs:
        key = (normalize_tr(raw_name), frozenset(_normalize_mahalle(raw_mh)))
        score_groups.setdefault(key, []).append(input_id)
        name_for_group.setdefault(key, (raw_name, raw_mh))

    cb(
        f"Mixed mode: {len(names)} raw, {len(cleaned_inputs)} non-empty "
        f"({len(score_groups)} unique (name, neighborhood) pairs)"
    )
    n_with_mh = sum(
        1 for (_n, mh) in name_for_group.values() if mh and str(mh).strip()
    )
    if n_with_mh:
        cb(f"Neighborhood filter: active for {n_with_mh} unique pairs")

    rows: list[dict] = []
    matched = tag_match = tag_mismatch = no_detect = not_found = 0
    mh_filter_applied = mh_filter_empty = 0  # diagnostic counters

    def _emit_for_each(template: dict, ids: list[int]) -> None:
        """Aynı şablonu her input_id için Input Row alanı farklı kopyala."""
        for input_id in ids:
            row = dict(template)
            row["Input Row"] = input_id
            rows.append(row)

    for key, input_ids in score_groups.items():
        n_ids = len(input_ids)
        input_name, mh_hint = name_for_group[key]
        det = detect_category(input_name)
        detected_label = (
            _category_label_tr(det[0], det[1]) if det else "—"
        )
        rule_code = det[2] if det else None

        # Build input tokens with appropriate strategy.
        # Place-stopword subtraction is "safe": if it would empty the set,
        # fall back to the un-stripped version (covers names whose only
        # discriminator IS the place — e.g. "Moda Parkı").
        if rule_code:
            raw_tokens = set(tokenize_for_match(input_name, rule_code))
        else:
            raw_tokens = set(tokenize_lite(input_name))
            no_detect += n_ids
        in_tokens = _strip_place_safely(raw_tokens, getattr(pool, "place_stopwords", set()))
        in_canonical = " ".join(sorted(in_tokens))

        if not in_tokens:
            template = _emit_mixed_row(
                input_name, detected_label, None, 0.0, 0,
                "Not found", "—", "—", set(), "",
                mahalle_hint=mh_hint, mahalle_filter_used=False,
            )
            template["Eşleşme Açıklaması"] = (
                "input had no scoring tokens (empty or all stopwords)"
            )
            _emit_for_each(template, input_ids)
            not_found += n_ids
            continue

        # ── Mahalle pre-filter: shrink candidate set BEFORE fuzzy scoring ─
        # When the user supplied a mahalle hint, restrict candidates to
        # those assigned to that mahalle. This is the highest-leverage
        # accuracy lever: 10K candidates → ~100, killing the dominant
        # source of false positives ("same name in another mahalle").
        mh_filter_used = bool(mh_hint and str(mh_hint).strip())
        if mh_filter_used:
            mh_filter_applied += n_ids
            cand_indices = [
                i for i, c in enumerate(pool.candidates)
                if _mahalle_match(mh_hint, c.payload.get("Mahalle"))
            ]
            if not cand_indices:
                # Mahalle hint given but no candidates in that mahalle —
                # genuine "not found in this mahalle" signal.
                mh_filter_empty += n_ids
                template = _emit_mixed_row(
                    input_name, detected_label, None, 0.0, 0,
                    "Not found", "—", "—", set(), "",
                    mahalle_hint=mh_hint, mahalle_filter_used=True,
                )
                template["Eşleşme Açıklaması"] = (
                    f"no candidates in named neighborhood '{mh_hint}'"
                )
                _emit_for_each(template, input_ids)
                not_found += n_ids
                continue
        else:
            cand_indices = list(range(len(pool.candidates)))

        # Pick the appropriate candidate-token view. Both paths take the max
        # score across every name variant (Ad, name:tr, alt_name, brand, …)
        # so a POI whose user-supplied label only matches an alternate field
        # still surfaces.
        if rule_code:
            rule_view = _get_rule_view(pool, rule_code)
            scored: list[tuple[float, _UniversalCandidate, set[str]]] = []
            for i in cand_indices:
                cand = pool.candidates[i]
                variants = rule_view[i]
                if not variants:
                    continue
                s, common = _score_variants(in_tokens, in_canonical, variants)
                if s > 0:
                    scored.append((s, cand, common))
        else:
            # Lite path
            scored = []
            for i in cand_indices:
                cand = pool.candidates[i]
                s, common = _score_variants(in_tokens, in_canonical, cand.lite_variants)
                if s > 0:
                    scored.append((s, cand, common))

        # Tag-compat tiebreak (Fix 1): primary sort score desc, secondary
        # sort by tag-compatibility rank (match > support > unknown > mismatch).
        # This fixes "MODA PARKI" → "Moda" (neighborhood) vs "Moda Parkı"
        # (leisure=park) where both score 100 — the park wins because its
        # tags align with detected `park` rule.
        #
        # Perf: _check_tag_compat is called for every scored candidate during
        # the sort and again later for best/runner. Cache results per group
        # by id(payload) — payloads are stable dicts within a single match
        # pass so identity-keyed dict is safe and avoids re-evaluating the
        # rule strict_tags / support_tags structure 3-5× per candidate.
        compat_cache: dict[int, str] = {}

        # B023: outer-loop'tan gelen `rule_code` ve aynı kapsamdaki
        # `compat_cache` default-arg ile bağlanır. _compat() sadece
        # sort() içinde senkron kullanılıyor; yine de best-practice.
        def _compat(payload: dict, _rule_code=rule_code, _cache=compat_cache) -> str:
            if not _rule_code:
                return "unknown"
            k = id(payload)
            v = _cache.get(k)
            if v is None:
                v = _check_tag_compat(payload, _rule_code)
                _cache[k] = v
            return v

        if rule_code:
            scored.sort(key=lambda x: (
                -x[0],
                _COMPAT_RANK.get(_compat(x[1].payload), 3),
            ))
        else:
            scored.sort(key=lambda x: -x[0])
        top = scored[:3]

        if not top:
            template = _emit_mixed_row(
                input_name, detected_label, None, 0.0, 0,
                "Not found", "—", "—", set(), "",
                mahalle_hint=mh_hint, mahalle_filter_used=mh_filter_used,
            )
            template["Eşleşme Açıklaması"] = (
                "no candidate matched any input token"
            )
            _emit_for_each(template, input_ids)
            not_found += n_ids
            continue

        best_score, best_cand, common = top[0]
        runner = top[1][0] if len(top) > 1 else 0.0
        n_above = sum(1 for s, _, _ in top if s >= threshold)
        status = _classify(best_score, runner, threshold, n_above)

        osm_cat = _osm_category_label(best_cand.payload)
        compat_raw = _compat(best_cand.payload)

        # Override "Ambiguous" → "Matched" when tag-compat resolves the tie.
        # Both "Moda" (suburb, tag=—) and "Moda Parkı" (leisure=park, tag=✅)
        # score 100, but only the latter aligns with the detected `park`
        # rule. After the tag-aware sort the park is already at top[0];
        # this reclassifies the row from Ambiguous to Matched accordingly.
        if status == "Ambiguous" and rule_code and len(top) > 1:
            runner_compat = _compat(top[1][1].payload)
            if _COMPAT_RANK.get(compat_raw, 3) < _COMPAT_RANK.get(runner_compat, 3):
                status = "Matched"

        compat = _TAG_MATCH_TR[compat_raw]

        if status == "Matched":
            matched += n_ids
            if compat_raw == "match":
                tag_match += n_ids
            elif compat_raw == "mismatch":
                tag_mismatch += n_ids
        elif status in ("Possible match", "Ambiguous"):
            pass  # don't count as Matched
        else:
            not_found += n_ids

        alts = " · ".join(
            f"{c.payload.get('Ad','?')} (skor={s:.0f})"
            for s, c, _ in top[1:3]
        )

        # Decomposed score breakdown — kullanıcı "neden seçildi?" sorusunu
        # tek bakışta cevaplayabilsin. final_score zaten denklemde, burada
        # bileşenleri ayrıştırılmış olarak yüzeye çıkarıyoruz.
        breakdown = _compute_score_breakdown(
            in_tokens=in_tokens,
            in_canonical=in_canonical,
            cand=best_cand,
            rule_code=rule_code,
            pool=pool,
            mh_hint=mh_hint,
            mh_filter_used=mh_filter_used,
            compat_raw=compat_raw,
            common=common,
        )

        template = _emit_mixed_row(
            input_name=input_name,
            detected_label=detected_label,
            cand=best_cand,
            score=best_score,
            tier=1 if rule_code else 2,
            status=status,
            osm_category=osm_cat,
            tag_match=compat,
            common_tokens=common,
            alts=alts,
            mahalle_hint=mh_hint,
            mahalle_filter_used=mh_filter_used,
            breakdown=breakdown,
        )
        # Near-miss diagnostic: when status is "Possible match" the breakdown
        # explanation alone doesn't reveal the threshold gap. Prepend it so
        # the user sees at a glance how far below threshold the score landed.
        if status == "Possible match":
            existing = template.get("Eşleşme Açıklaması") or "—"
            tail = f" · {existing}" if existing not in ("—", "", None) else ""
            template["Eşleşme Açıklaması"] = (
                f"closest score {best_score:.0f} (threshold {threshold:.0f}){tail}"
            )
        _emit_for_each(template, input_ids)

    # Çıktı sırasını orijinal input sırasına sabitle (deterministik denetim).
    rows.sort(key=lambda r: r.get("Input Row", 0))
    out_df = pd.DataFrame(rows)
    head = [
        "Input Row", "Girdi Ad", "Mahalle (Girdi)", "Mahalle Filtresi",
        "Tespit Edilen Kategori", "Eşleşme Durumu",
        "Eşleşme Skoru",
        "Skor: İsim", "Skor: Jaccard", "Skor: Tag", "Skor: Mahalle",
        "Eşleşme Açıklaması",
        "OSM Kategori", "Etiket Uyumu",
        "Eşleşen Kelimeler",
    ]
    tail = [c for c in out_df.columns
            if c not in head and c != "Alternatif Eşleşmeler"]
    out_df = out_df[head + tail + ["Alternatif Eşleşmeler"]]

    cb(
        f"Mixed result: Matched={matched} (✅ {tag_match} · ❌ {tag_mismatch} tag mismatch) · "
        f"Detection-fail={no_detect} · NotFound={not_found}"
        + (f" · NeighborhoodFilter={mh_filter_applied} rows (empty={mh_filter_empty})"
           if mh_filter_applied else "")
    )

    return MixedLookupResult(
        df=out_df,
        matched_count=matched,
        tag_match_count=tag_match,
        tag_mismatch_count=tag_mismatch,
        not_detected_count=no_detect,
        not_found_count=not_found,
        candidate_pool_size=len(pool.candidates),
        mahalle_filter_rows=mh_filter_applied,
        mahalle_filter_empty=mh_filter_empty,
    )


@dataclass
class _ScoreBreakdown:
    """
    Decomposed score components — surfaces the internal signals that
    drive `Eşleşme Skoru` so the user can audit "why this candidate?".

    All fields are 0-100 scaled. None means "not applicable" (ör. mahalle
    filtresi aktif değilse Skor: Mahalle = None).
    """
    name_similarity: float          # raw token_set_ratio (0-100)
    jaccard_pct:     float          # token overlap ratio × 100
    tag_score:       float | None  # match=100, support=70, unknown=50, mismatch=0
    mahalle_score:   float | None  # 100 if hint matched, None if no hint
    explanation:     str            # human-readable "why" string




def _compute_breakdown_from_variants(
    *,
    in_tokens: set[str],
    in_canonical: str,
    cand_variants: list[tuple[set[str], str]],
    common: set[str],
    compat_raw: str,
    mahalle_filter_used: bool,
    matched: bool,
) -> _ScoreBreakdown:
    """
    Mevcut hesaplanan skoru bileşenlerine ayrıştırır — yeni hesap yok,
    sadece görünür hale getirme. Hem mixed hem single mode'dan çağrılır.

    `matched=True` olduğunda candidate'in geçerli olduğunu kabul ederiz
    (caller best_match'i seçti). `False` ise breakdown nötr/0 döner.
    """
    name_sim = 0.0
    jaccard_pct = 0.0
    if matched and in_tokens and cand_variants:
        for cd_tokens, cd_canonical in cand_variants:
            if not cd_tokens:
                continue
            common_v = in_tokens & cd_tokens
            union_v = in_tokens | cd_tokens
            if not common_v or not union_v:
                continue
            sim = float(fuzz.token_set_ratio(in_canonical, cd_canonical))
            if sim > name_sim:
                name_sim = sim
                jaccard_pct = (len(common_v) / len(union_v)) * 100.0

    tag_score = _TAG_SCORE_MAP.get(compat_raw)

    mahalle_score: float | None = None
    if mahalle_filter_used and matched:
        mahalle_score = 100.0

    bits: list[str] = []
    if common:
        bits.append(f"common tokens: {', '.join(sorted(common))}")
    if compat_raw == "match":
        bits.append("OSM tag aligned")
    elif compat_raw == "support":
        bits.append("supporting tag")
    elif compat_raw == "mismatch":
        bits.append("⚠️ tag contradicts")
    if mahalle_filter_used:
        bits.append("passed neighborhood filter")
    if jaccard_pct < 50 and name_sim >= 80:
        bits.append("asymmetric name (low Jaccard)")
    explanation = " · ".join(bits) if bits else "—"

    return _ScoreBreakdown(
        name_similarity=round(name_sim, 1),
        jaccard_pct=round(jaccard_pct, 1),
        tag_score=tag_score,
        mahalle_score=mahalle_score,
        explanation=explanation,
    )


def _compute_score_breakdown(
    *,
    in_tokens: set[str],
    in_canonical: str,
    cand,                              # _UniversalCandidate (Optional in tests)
    rule_code: str | None,
    pool,                              # UniversalPool
    mh_hint: str | None,
    mh_filter_used: bool,
    compat_raw: str,
    common: set[str],
) -> _ScoreBreakdown:
    """Mixed-mode adapter — UniversalPool variants'ından çekip core'a delege."""
    if cand is None:
        return _compute_breakdown_from_variants(
            in_tokens=in_tokens, in_canonical=in_canonical,
            cand_variants=[], common=common,
            compat_raw=compat_raw, mahalle_filter_used=mh_filter_used,
            matched=False,
        )
    # Rule-aware view veya lite variants
    variants = cand.lite_variants
    if rule_code:
        try:
            rule_view = _get_rule_view(pool, rule_code)
            cand_index = next(
                (i for i, c in enumerate(pool.candidates) if c is cand), None
            )
            if cand_index is not None and rule_view[cand_index]:
                variants = rule_view[cand_index]
        except Exception:
            pass
    return _compute_breakdown_from_variants(
        in_tokens=in_tokens, in_canonical=in_canonical,
        cand_variants=variants, common=common,
        compat_raw=compat_raw, mahalle_filter_used=mh_filter_used,
        matched=True,
    )


def _emit_mixed_row(
    input_name: str,
    detected_label: str,
    cand: _UniversalCandidate | None,
    score: float,
    tier: int,
    status: str,
    osm_category: str,
    tag_match: str,
    common_tokens: set[str],
    alts: str,
    mahalle_hint: str | None = None,
    mahalle_filter_used: bool = False,
    breakdown: _ScoreBreakdown | None = None,
) -> dict:
    """Build one mixed-mode output row."""
    base: dict = {
        "Girdi Ad":              input_name,
        "Mahalle (Girdi)":       (str(mahalle_hint).strip()
                                  if mahalle_hint and not pd.isna(mahalle_hint)
                                  else ""),
        "Mahalle Filtresi":      "Aktif" if mahalle_filter_used else "—",
        "Tespit Edilen Kategori": detected_label,
        "Eşleşme Durumu":        status,
        "Eşleşme Skoru":         round(score, 1),
        "Skor: İsim":            (breakdown.name_similarity if breakdown else None),
        "Skor: Jaccard":         (breakdown.jaccard_pct if breakdown else None),
        "Skor: Tag":             (breakdown.tag_score if breakdown else None),
        "Skor: Mahalle":         (breakdown.mahalle_score if breakdown else None),
        "Eşleşme Açıklaması":    (breakdown.explanation if breakdown else "—"),
        "OSM Kategori":          osm_category,
        "Etiket Uyumu":          tag_match,
        "Eşleşen Kelimeler":     ", ".join(sorted(common_tokens)),
        "Alternatif Eşleşmeler": alts,
    }
    if cand is not None:
        # Surface the standard pipeline-mirror columns from candidate payload.
        for col in ["OSM Tipi", "OSM ID", "Ad", "Enlem", "Boylam",
                    "Mahalle", "Sınır Durumu", "Alan (m²)", "Alan Kaynağı"]:
            base[col] = cand.payload.get(col)
        # Surface raw tag columns too — useful for audit.
        for col in _KEEP_TAG_COLUMNS:
            base[col] = cand.payload.get(col)
    else:
        for col in ["OSM Tipi", "OSM ID", "Ad", "Enlem", "Boylam",
                    "Mahalle", "Sınır Durumu", "Alan (m²)", "Alan Kaynağı"]:
            base[col] = None
        for col in _KEEP_TAG_COLUMNS:
            base[col] = None
    return base
