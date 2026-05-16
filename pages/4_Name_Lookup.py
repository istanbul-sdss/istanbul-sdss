"""
pages/4_Name_Lookup.py — Reverse / name-based OSM lookup.

User uploads a list of names (e.g. official pharmacy names from a chamber).
For a chosen district + category, the module:
    Tier 1 — matches against POIs OSM tags correctly for that category
    Tier 2 — broadens to all named features in the district (mistag catcher)
    Tier 3 — leaves the rest as Not found (with closest near-miss diagnostic)

Output mirrors the existing pipeline schema (Latitude, Longitude,
Neighborhood, OSM ID, etc.) plus Match Status / Score / Tier / Alternatives.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from components import cards
from components.state import KEY_SELECTED_DISTRICT, init_state
from components.styles import configure_page
from components.translations import to_english
from src.config.category_registry import (
    CATEGORY_REGISTRY,
    get_subcategory_options_tr,
)
from src.config.settings import ISTANBUL_ILCELER
from src.logger import get_logger
from src.services.name_lookup_service import (
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
)

# ── Cached pool preparation ────────────────────────────────────────────────
# Both prep paths are independent of the input name list, so we cache them
# across runs. Different prep functions for single-category vs mixed mode.
#
# Bump _POOL_SCHEMA_VERSION when UniversalPool / PreparedPools dataclasses
# gain a field — Streamlit cache pickles the dataclass by value, so an
# older cached instance wouldn't have the new attribute and would crash on
# access. Including the version in the cache key forces a fresh fetch.
#
# v3: _build_place_stopwords now reads `neighbourhood_name` (the real
# column produced by neighbourhood_loader) instead of "mahalle"/"name".
# Old cached pools have empty mahalle stopwords — bumping invalidates them.
# v4: Candidates carry per-variant token lists (Ad, name:tr, alt_name,
# loc_name, official_name, short_name, brand, operator) so scoring takes
# the max across name sources. _UniversalCandidate.lite_variants and
# _Candidate.variants are new fields — old pickled pools would AttributeError.
# v5: Universal/Tier 2 enrichment now computes "Alan (m²)" via UTM polygon
# measurement + point→polygon overlay fallback, and "Alan Kaynağı" carries
# provenance ("measured" / "polygon_overlay" / "capacity_derived" / "").
# Old cached payloads would surface empty area cells.
_POOL_SCHEMA_VERSION = 5


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_prepare_pools(
    ilce: str,
    cat_key: str,
    sub_key: str,
    enable_tier2: bool,
    _schema: int = _POOL_SCHEMA_VERSION,
) -> PreparedPools:
    return prepare_pools(
        ilce=ilce, cat_key=cat_key, sub_key=sub_key,
        enable_tier2=enable_tier2,
    )


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_prepare_universal(ilce: str, _schema: int = _POOL_SCHEMA_VERSION) -> UniversalPool:
    return prepare_universal_pool(ilce=ilce)

log = get_logger("page.name_lookup")


# Match Status TR → EN for English-output Excel.
_STATUS_EN = {
    "Matched":          "Matched",
    "Possible match":   "Possible match",
    "Possible mistag":  "Possible mistag",
    "Ambiguous":        "Ambiguous",
    "Not found":        "Not found",
}

# Tag-match labels TR → EN (mixed mode)
_TAG_MATCH_EN = {
    "✅ Uyumlu":         "✅ Compatible",
    "⚠️ Destekleyici":   "⚠️ Supporting",
    "❌ Çelişkili":       "❌ Contradicts",
    "— (etiket yok)":    "— (no tag)",
}


# ════════════════════════════════════════════════════════════════════════════
# PAGE SETUP
# ════════════════════════════════════════════════════════════════════════════
configure_page(title="Name Lookup", icon="🔍")
init_state()

KEY_NAME_LOOKUP_RESULT = "name_lookup_result"
if KEY_NAME_LOOKUP_RESULT not in st.session_state:
    st.session_state[KEY_NAME_LOOKUP_RESULT] = None


# ════════════════════════════════════════════════════════════════════════════
# SIDEBAR — selection controls
# ════════════════════════════════════════════════════════════════════════════
cards.sidebar_brand()

st.sidebar.markdown("### 1 · District")
district = st.sidebar.selectbox(
    "District",
    ISTANBUL_ILCELER,
    index=ISTANBUL_ILCELER.index(
        st.session_state.get(KEY_SELECTED_DISTRICT, "Kadıköy")
    ),
    label_visibility="collapsed",
)
st.session_state[KEY_SELECTED_DISTRICT] = district

st.sidebar.markdown("---")

# ── Mode selection ─────────────────────────────────────────────────────────
st.sidebar.markdown("### 2 · Lookup mode")
mode = st.sidebar.radio(
    "Mode",
    options=["Single category", "Mixed list (auto-detect)"],
    index=1,  # default to mixed — generally more useful for real-world lists
    label_visibility="collapsed",
    help=(
        "Single category — pick one OSM category, all names searched in it.\n"
        "Mixed list — system auto-detects category per row from name suffix "
        "(park, cami, eczanesi, ilkokulu …). Right for assembly-point lists, "
        "BIMER POIs, or any heterogeneous list."
    ),
)
is_mixed = (mode == "Mixed list (auto-detect)")

st.sidebar.markdown("---")

# ── Category selection (Single mode only) ──────────────────────────────────
cat_key = sub_key = None
sub_labels: dict = {}
if not is_mixed:
    st.sidebar.markdown("### 3 · Category")
    cat_keys = [k for k in CATEGORY_REGISTRY if k != "admin_boundaries"]
    cat_labels = {k: f"{CATEGORY_REGISTRY[k].get('icon','')} {CATEGORY_REGISTRY[k]['label_en']}".strip()
                  for k in cat_keys}
    cat_key = st.sidebar.selectbox(
        "Main category",
        options=cat_keys,
        format_func=lambda k: cat_labels[k],
        index=cat_keys.index("health") if "health" in cat_keys else 0,
    )

    subs = get_subcategory_options_tr(cat_key)
    sub_options = [s["key"] for s in subs]
    sub_labels  = {s["key"]: s["label"] for s in subs}
    default_sub = "pharmacy" if cat_key == "health" and "pharmacy" in sub_options else sub_options[0]
    sub_key = st.sidebar.selectbox(
        "Sub-category",
        options=sub_options,
        format_func=lambda k: sub_labels[k],
        index=sub_options.index(default_sub),
    )
    st.sidebar.markdown("---")

# ── Excel upload ───────────────────────────────────────────────────────────
upload_step_n = "3" if is_mixed else "4"
st.sidebar.markdown(f"### {upload_step_n} · Name list (Excel/CSV)")
upload = st.sidebar.file_uploader(
    "Upload file",
    type=["xlsx", "xls", "csv"],
    label_visibility="collapsed",
    help="The file must contain a column with names (e.g. 'Name', 'Ad', 'isim').",
)

st.sidebar.markdown("---")

# ── Matching options ───────────────────────────────────────────────────────
match_step_n = "4" if is_mixed else "5"
st.sidebar.markdown(f"### {match_step_n} · Matching options")

enable_tier2 = True
tier1_threshold = TIER1_DEFAULT_THRESHOLD
tier2_threshold = TIER2_DEFAULT_THRESHOLD
mixed_threshold = MIXED_DEFAULT_THRESHOLD

if is_mixed:
    mixed_threshold = st.sidebar.slider(
        "Match threshold",
        50, 100, MIXED_DEFAULT_THRESHOLD,
        help="Acceptance score. With Jaccard penalty active, 80 is a "
             "well-calibrated default — lower lets through more "
             "near-misses (review them in Possible match), higher is "
             "stricter.",
    )
else:
    enable_tier2 = st.sidebar.checkbox(
        "Enable Tier 2 (mistag catcher)",
        value=True,
        help="Broadens search to all named OSM features in the district. "
             "Catches POIs missing the correct category tag. Slower for large districts.",
    )
    tier1_threshold = st.sidebar.slider(
        "Tier 1 threshold",
        50, 100, TIER1_DEFAULT_THRESHOLD,
        help="Acceptance score for the correctly-tagged pool (precision-first).",
    )
    tier2_threshold = st.sidebar.slider(
        "Tier 2 threshold",
        70, 100, TIER2_DEFAULT_THRESHOLD,
        disabled=not enable_tier2,
        help="Acceptance score for the wide mistag pool (false-positive guard — keep ≥85).",
    )

st.sidebar.markdown("---")

run_btn = st.sidebar.button(
    "🚀 Run Lookup",
    width="stretch",
    type="primary",
    disabled=upload is None,
)
if upload is None:
    st.sidebar.warning("Upload a name list to enable.")

st.sidebar.markdown(
    """
    <div style="font-size:0.75rem;color:#64748B;line-height:1.5;margin-top:1rem">
    Data: OpenStreetMap · Overpass API<br>
    © OSM Contributors, ODbL
    </div>
    """,
    unsafe_allow_html=True,
)


# ════════════════════════════════════════════════════════════════════════════
# MAIN — header + intro
# ════════════════════════════════════════════════════════════════════════════
cards.page_header(
    eyebrow="Workflow · Reverse Lookup",
    title="Name-based OSM Lookup",
    subtitle="Upload a list of place names — get back coordinates, "
             "neighborhood, and OSM metadata for each, including records "
             "that OSM tags incorrectly for this category.",
)

_strip_items = [
    {"label": "District:",  "value": district,                     "tone": "ok"},
    {"label": "Mode:",      "value": "Mixed (auto-detect)" if is_mixed else "Single category",
     "tone": "ok"},
]
if is_mixed:
    _strip_items.append({
        "label": "Threshold:", "value": str(mixed_threshold), "tone": "ok",
    })
else:
    _strip_items.append({
        "label": "Category:", "value": sub_labels.get(sub_key, sub_key or "—"), "tone": "ok",
    })
    _strip_items.append({
        "label": "Tier 2:",   "value": "On" if enable_tier2 else "Off",
        "tone": "ok" if enable_tier2 else None,
    })
_strip_items.append({
    "label": "Input:", "value": upload.name if upload else "—",
    "tone": "ok" if upload else "warn",
})
cards.status_strip(_strip_items)


# ════════════════════════════════════════════════════════════════════════════
# Excel column picker + preview
# ════════════════════════════════════════════════════════════════════════════
input_df: pd.DataFrame | None = None
name_col: str | None = None
mahalle_col: str | None = None  # optional spatial filter column

# Tokens that strongly suggest "this column holds POI names".
_NAME_COL_TOKENS = {
    "name", "names", "ad", "adi", "ad_", "isim", "isimler",
    "pharmacy_name", "place_name", "poi_name", "title",
}

# Tokens that suggest "this column holds neighborhood names".
_MAHALLE_COL_TOKENS = {
    "mahalle", "mahalle_adi", "mahallesi", "mahalleadi", "mh", "mah",
    "neighborhood", "neighbourhood", "district", "semt", "bolge",
}


def _looks_like_name_column(col: str) -> bool:
    return str(col).strip().lower() in _NAME_COL_TOKENS


def _looks_like_mahalle_column(col: str) -> bool:
    norm = str(col).strip().lower().replace(" ", "_")
    return norm in _MAHALLE_COL_TOKENS


def _pick_best_sheet(sheets: dict[str, pd.DataFrame]) -> str:
    """
    Score each sheet by:
      +10 if a column name looks like a name column
      + (non-empty unique strings in best name-like column) / 100
    Pick the highest-scoring sheet. Tie-breaker: original sheet order.
    """
    best_name, best_score = next(iter(sheets)), -1.0
    for sheet, df in sheets.items():
        if df is None or df.empty:
            continue
        score = 0.0
        # Find a name-like column (or fall back to any string column)
        name_like = [c for c in df.columns if _looks_like_name_column(c)]
        if name_like:
            score += 10.0
            target = name_like[0]
        else:
            # Heuristic fallback: first column with mostly strings
            target = None
            for c in df.columns:
                if df[c].dtype == object and df[c].astype(str).str.strip().ne("").mean() > 0.5:
                    target = c
                    break
        if target is not None:
            n_unique = df[target].astype(str).str.strip().replace("", pd.NA).dropna().nunique()
            score += n_unique / 100.0
        if score > best_score:
            best_score = score
            best_name = sheet
    return best_name


if upload is not None:
    try:
        if upload.name.lower().endswith(".csv"):
            input_df = pd.read_csv(upload)
            sheet_name: str | None = None
            sheet_options: list[str] = []
        else:
            # Multi-sheet aware: load all, auto-pick the most name-y sheet.
            xls = pd.ExcelFile(upload)
            sheet_options = list(xls.sheet_names)
            all_sheets = {s: pd.read_excel(xls, sheet_name=s) for s in sheet_options}

            # If the user already picked a sheet in this session, respect that.
            sheet_state_key = f"name_lookup_sheet::{upload.name}"
            default_sheet = st.session_state.get(sheet_state_key) \
                            or _pick_best_sheet(all_sheets)
            sheet_name = default_sheet
            input_df = all_sheets[sheet_name]
    except Exception as e:
        st.error(f"❌ File could not be read: {e}")
        input_df = None
        sheet_options = []
        sheet_name = None

if input_df is not None:
    cards.divider()
    cards.section_title(
        "Input file",
        f"{upload.name} — {len(input_df):,} rows · {len(input_df.columns)} columns",
    )

    # ── Sheet picker (only for multi-sheet Excel) ─────────────────────────
    if sheet_options and len(sheet_options) > 1:
        chosen_sheet = st.selectbox(
            "Sheet",
            options=sheet_options,
            index=sheet_options.index(sheet_name),
            help="Multi-sheet workbook detected. Auto-selected the sheet "
                 "most likely to contain a name column.",
        )
        if chosen_sheet != sheet_name:
            st.session_state[sheet_state_key] = chosen_sheet
            input_df = all_sheets[chosen_sheet]
            sheet_name = chosen_sheet

    # Auto-detect a likely name column inside the chosen sheet.
    candidates = [c for c in input_df.columns if _looks_like_name_column(c)]
    default_col = candidates[0] if candidates else input_df.columns[0]

    # Auto-detect a likely mahalle/neighborhood column.
    mh_candidates = [c for c in input_df.columns if _looks_like_mahalle_column(c)]
    mh_default = mh_candidates[0] if mh_candidates else None

    c1, c2 = st.columns([1, 2], gap="medium")
    with c1:
        name_col = st.selectbox(
            "Name column",
            options=list(input_df.columns),
            index=list(input_df.columns).index(default_col),
        )
        nonempty_n = int(input_df[name_col].astype(str).str.strip().ne("").sum())
        st.caption(f"{nonempty_n:,} non-empty values in this column")

        # Mahalle column — optional, but the highest-leverage accuracy boost.
        # When supplied, candidates outside the named mahalle are filtered
        # out before fuzzy matching runs (10K → ~100 candidate pool).
        mh_options = ["(none — no mahalle filter)"] + list(input_df.columns)
        mh_index = (
            mh_options.index(mh_default) if mh_default in mh_options else 0
        )
        mh_choice = st.selectbox(
            "Mahalle column (optional)",
            options=mh_options,
            index=mh_index,
            help=(
                "If your file has a column with the neighborhood for each "
                "POI (e.g. 'Mahalle', 'Neighborhood'), pick it here. "
                "The system will restrict candidates to that neighborhood "
                "before matching — biggest accuracy boost when the same "
                "name appears in multiple places (e.g. 'Merkez Eczanesi')."
            ),
        )
        mahalle_col = mh_choice if mh_choice in input_df.columns else None
        if mahalle_col:
            n_mh = int(input_df[mahalle_col].astype(str).str.strip().ne("").sum())
            st.caption(f"🏘️ Neighborhood filter active for {n_mh:,} rows")
        else:
            # Visible nudge — neighborhood column collapses the candidate pool
            # 10K → ~100 in mixed mode and is the single biggest accuracy lever.
            # Easy to miss if the input file has many columns; surface it here.
            st.markdown(
                '<div style="background:#FEF3C7;border:1px solid #FDE68A;'
                'border-radius:8px;padding:10px 14px;color:#92400E;'
                'font-size:0.8125rem;margin-top:8px">'
                '💡 <b>Tip:</b> Adding a neighborhood column to your file '
                '(e.g. <code>Mahalle</code>, <code>Neighborhood</code>) '
                'dramatically improves accuracy — it limits candidates to '
                'the named neighborhood before fuzzy matching, eliminating '
                'most same-name-elsewhere false positives.</div>',
                unsafe_allow_html=True,
            )
    with c2:
        st.dataframe(input_df.head(8), width="stretch", hide_index=True)


# ════════════════════════════════════════════════════════════════════════════
# RUN
# ════════════════════════════════════════════════════════════════════════════
if run_btn and input_df is not None and name_col is not None:
    cards.divider()
    st.markdown("### Lookup log")

    progress  = st.progress(0)
    status_ph = st.empty()
    log_ph    = st.empty()
    log_lines: list[str] = []

    def ui_log(msg: str) -> None:
        log_lines.append(f"• {msg}")
        log_ph.markdown(
            '<div style="background:#0F172A;color:#E2E8F0;padding:1rem;'
            'border-radius:10px;font-family:ui-monospace,monospace;'
            'font-size:0.8125rem;line-height:1.6;max-height:300px;overflow:auto">'
            + "<br>".join(log_lines[-18:]) +
            "</div>",
            unsafe_allow_html=True,
        )
        log.info(msg)

    try:
        t0 = time.time()
        progress.progress(10)
        names = input_df[name_col].astype(str).tolist()

        # Build per-row mahalle hint list when a mahalle column was picked.
        # None entries pass through as "no filter for this row" so mixed
        # files (some rows annotated, others bare) keep working.
        neighborhoods: list[str | None] | None = None
        if mahalle_col and mahalle_col in input_df.columns:
            neighborhoods = [
                (str(v).strip() if v is not None and not pd.isna(v) and str(v).strip() else None)
                for v in input_df[mahalle_col].tolist()
            ]
            n_mh = sum(1 for x in neighborhoods if x)
            ui_log(f"🏘️ Neighborhood filter active: {n_mh}/{len(neighborhoods)} rows")

        if is_mixed:
            # ── Mixed-list mode ──────────────────────────────────────────
            status_ph.markdown("**Running mixed-list lookup (auto-detect per row)…**")
            ui_log("Preparing universal pool (checking cache)...")
            upool: UniversalPool = _cached_prepare_universal(ilce=district)
            ui_log(f"Universal pool ready — {len(upool.candidates)} candidates")
            progress.progress(60)

            mresult: MixedLookupResult = match_mixed_list(
                pool=upool,
                names=names,
                neighborhoods=neighborhoods,
                threshold=float(mixed_threshold),
                progress_cb=ui_log,
            )
            progress.progress(100)

            elapsed = time.time() - t0
            st.session_state[KEY_NAME_LOOKUP_RESULT] = {
                "mode":     "mixed",
                "result":   mresult,
                "district": district,
                "elapsed":  elapsed,
            }
            n_total = len(mresult.df)
            status_ph.markdown(
                cards.status_banner(
                    f"Completed — {mresult.matched_count}/{n_total} matched · "
                    f"{mresult.tag_match_count} tag-aligned · "
                    f"{mresult.tag_mismatch_count} tag mismatch · "
                    f"{mresult.not_found_count} not found "
                    f"({elapsed:.1f}s)",
                    tone="success",
                ),
                unsafe_allow_html=True,
            )
        else:
            # ── Single-category mode ─────────────────────────────────────
            status_ph.markdown("**Running two-tier lookup…**")
            ui_log("Preparing candidate pools (checking cache)...")
            pools: PreparedPools = _cached_prepare_pools(
                ilce=district, cat_key=cat_key, sub_key=sub_key,
                enable_tier2=enable_tier2,
            )
            ui_log(
                f"Pools ready — Tier 1: {len(pools.tier1_candidates)} candidates · "
                f"Tier 2: {len(pools.tier2_candidates)} candidates"
            )
            progress.progress(60)

            result: NameLookupResult = match_names(
                pools=pools, names=names,
                tier1_threshold=float(tier1_threshold),
                tier2_threshold=float(tier2_threshold),
                progress_cb=ui_log,
            )
            progress.progress(100)

            elapsed = time.time() - t0
            st.session_state[KEY_NAME_LOOKUP_RESULT] = {
                "mode":           "single",
                "result":         result,
                "district":       district,
                "cat_key":        cat_key,
                "sub_key":        sub_key,
                "category_label": sub_labels[sub_key],
                "elapsed":        elapsed,
            }
            status_ph.markdown(
                cards.status_banner(
                    f"Completed — {result.tier1_count + result.tier2_count}/"
                    f"{len(result.df)} matched · {result.not_found_count} not found "
                    f"({elapsed:.1f}s)",
                    tone="success",
                ),
                unsafe_allow_html=True,
            )

    except Exception as e:
        # Tam traceback log'a, kullanıcıya yalnızca kısa mesaj.
        st.error(f"❌ Lookup failed: {type(e).__name__}: {e}")
        log.error("Name lookup error", exc_info=True)


# ════════════════════════════════════════════════════════════════════════════
# RESULTS
# ════════════════════════════════════════════════════════════════════════════
state = st.session_state.get(KEY_NAME_LOOKUP_RESULT)

def _styled_excel_bytes(df: pd.DataFrame, sheet: str = "Lookup") -> bytes:
    """Single-sheet styled Excel — used by both modes' download tabs."""
    from src.services.excel_utils import build_styled_workbook
    return build_styled_workbook(
        lambda w: df.to_excel(w, sheet_name=sheet, index=False)
    )


if state and state.get("result") is not None and state.get("mode") == "mixed":
    # ════════════════════════════════════════════════════════════════════════
    # MIXED-MODE RESULTS
    # ════════════════════════════════════════════════════════════════════════
    mres: MixedLookupResult = state["result"]
    df_tr = mres.df.copy()

    df_en = to_english(df_tr.rename(columns={
        "Input Row":              "Input Row",
        "Girdi Ad":               "Input Name",
        "Mahalle (Girdi)":        "Input Neighborhood",
        "Mahalle Filtresi":       "Neighborhood Filter",
        "Tespit Edilen Kategori": "Detected Category",
        "Eşleşme Durumu":         "Match Status",
        "Eşleşme Skoru":          "Match Score",
        "Skor: İsim":             "Score: Name",
        "Skor: Jaccard":          "Score: Jaccard",
        "Skor: Tag":              "Score: Tag",
        "Skor: Mahalle":          "Score: Neighborhood",
        "Eşleşme Açıklaması":     "Why Matched",
        "OSM Kategori":           "OSM Category",
        "Etiket Uyumu":           "Tag Match",
        "Eşleşen Kelimeler":      "Match Tokens",
        "Alternatif Eşleşmeler":  "Alternative Matches",
    }))
    if "Match Status" in df_en.columns:
        df_en["Match Status"] = df_en["Match Status"].map(
            lambda v: _STATUS_EN.get(v, v) if pd.notna(v) else v
        )
    if "Tag Match" in df_en.columns:
        df_en["Tag Match"] = df_en["Tag Match"].map(
            lambda v: _TAG_MATCH_EN.get(v, v) if pd.notna(v) else v
        )
    if "Neighborhood Filter" in df_en.columns:
        df_en["Neighborhood Filter"] = df_en["Neighborhood Filter"].map(
            lambda v: "Active" if v == "Aktif" else v
        )

    cards.divider()
    cards.section_title(
        "Lookup summary — mixed list",
        f"{state['district']} — auto-detect category per row",
    )

    k1, k2, k3, k4, k5 = st.columns(5, gap="small")
    with k1: cards.kpi_card("Inputs",       len(df_en))
    with k2: cards.kpi_card("Matched",      mres.matched_count)
    with k3: cards.kpi_card("✅ Tag aligned", mres.tag_match_count)
    with k4: cards.kpi_card("❌ Tag mismatch", mres.tag_mismatch_count)
    with k5: cards.kpi_card("Not found",    mres.not_found_count)

    # Second KPI row — neighborhood filter is the highest-leverage accuracy
    # mechanism (10K → ~100 candidate pool when active). Promoting it from
    # caption to a dedicated KPI so users can see at a glance whether their
    # file took advantage of it.
    if mres.mahalle_filter_rows or mres.mahalle_filter_empty:
        kk1, kk2, kk3 = st.columns(3, gap="small")
        with kk1:
            cards.kpi_card(
                "🏘️ Neighborhood-filtered rows",
                f"{mres.mahalle_filter_rows:,}",
            )
        with kk2:
            cards.kpi_card(
                "🏘️ Empty after filter",
                f"{mres.mahalle_filter_empty:,}",
            )
        with kk3:
            full_pool_rows = len(df_en) - mres.mahalle_filter_rows
            cards.kpi_card(
                "Full-pool rows (no hint)",
                f"{full_pool_rows:,}",
            )

    pool_caption = (
        f"Universal candidate pool: {mres.candidate_pool_size:,} named features · "
        f"{mres.not_detected_count} input(s) had no detectable category suffix "
        f"(matched via fuzzy fallback)"
    )
    st.caption(pool_caption)

    tab_all, tab_mismatch, tab_nf, tab_dl = st.tabs(
        ["📋 All results", "❌ Tag mismatches", "❌ Not found", "📥 Downloads"]
    )

    with tab_all:
        q = st.text_input("Filter by any text", "", placeholder="Filter…",
                          label_visibility="collapsed", key="mixed_filter")
        view = df_en
        if q:
            patt = re.escape(q.strip())
            mask = view.apply(
                lambda c: c.astype(str).str.contains(patt, case=False, na=False, regex=True)
            ).any(axis=1)
            view = view[mask]
        st.dataframe(view, width="stretch", height=520, hide_index=True)
        st.caption(f"{len(view):,} of {len(df_en):,} rows")

    with tab_mismatch:
        if "Tag Match" in df_en.columns:
            mismatch_df = df_en[df_en["Tag Match"] == "❌ Contradicts"]
            if mismatch_df.empty:
                cards.empty_state(
                    "No tag contradictions",
                    "Every matched candidate's OSM tags align with the "
                    "detected category, or are missing (which is fine).",
                    icon="✅",
                )
            else:
                st.caption(
                    "These input names matched on name similarity, but the "
                    "matched OSM record's tags **contradict** the detected "
                    "category (e.g. expected `amenity=pharmacy`, found "
                    "`amenity=cafe`). Treat with caution — the candidate may "
                    "be a homonym or the OSM tag may be wrong; verify "
                    "before relying on the coordinates downstream."
                )
                st.dataframe(mismatch_df, width="stretch", height=520, hide_index=True)
        else:
            st.info("Run the lookup first.")

    with tab_nf:
        if "Match Status" in df_en.columns:
            nf_df = df_en[df_en["Match Status"].isin(["Not found", "Possible match"])]
            if nf_df.empty:
                cards.empty_state("Nothing here",
                                  "Every input name matched something.", icon="✅")
            else:
                st.caption(
                    "‘Not found’ — nothing in the universal pool was similar enough. "
                    "‘Possible match’ — closest candidate scored below threshold; "
                    "kept as diagnostic."
                )
                st.dataframe(nf_df, width="stretch", height=520, hide_index=True)
        else:
            st.info("Run the lookup first.")

    with tab_dl:
        st.markdown("Download uses English column names and translated values.")
        d1, d2 = st.columns(2, gap="medium")
        with d1:
            st.markdown("**Excel (English)**")
            st.download_button(
                "⬇️ Download Excel",
                data=_styled_excel_bytes(df_en),
                file_name=f"{state['district']}_mixed_name_lookup.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )
            st.caption(
                "Includes Detected Category, OSM Category, Tag Match columns "
                "plus the standard pipeline schema."
            )
        with d2:
            st.markdown("**CSV (English)**")
            st.download_button(
                "⬇️ Download CSV",
                data=df_en.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
                file_name=f"{state['district']}_mixed_name_lookup.csv",
                mime="text/csv",
                width="stretch",
            )

elif state and state.get("result") is not None and state.get("mode") == "single":
    # ════════════════════════════════════════════════════════════════════════
    # SINGLE-CATEGORY RESULTS (existing flow)
    # ════════════════════════════════════════════════════════════════════════
    res: NameLookupResult = state["result"]
    df_tr = res.df.copy()
    df_en = to_english(df_tr.rename(columns={
        "Input Row":             "Input Row",
        "Girdi Ad":              "Input Name",
        "Eşleşme Durumu":        "Match Status",
        "Eşleşme Skoru":         "Match Score",
        "Skor: İsim":            "Score: Name",
        "Skor: Jaccard":         "Score: Jaccard",
        "Skor: Tag":             "Score: Tag",
        "Skor: Mahalle":         "Score: Neighborhood",
        "Eşleşme Açıklaması":    "Why Matched",
        "Eşleşme Katmanı":       "Match Tier",
        "Eşleşen Kelimeler":     "Match Tokens",
        "Alternatif Eşleşmeler": "Alternative Matches",
    }))
    if "Match Status" in df_en.columns:
        df_en["Match Status"] = df_en["Match Status"].map(
            lambda v: _STATUS_EN.get(v, v) if pd.notna(v) else v
        )

    cards.divider()
    cards.section_title(
        "Lookup summary",
        f"{state['district']} — {state['category_label']}",
    )

    k1, k2, k3, k4, k5 = st.columns(5, gap="small")
    with k1: cards.kpi_card("Inputs", len(df_en))
    with k2: cards.kpi_card("Tier 1 (correct tag)", res.tier1_count)
    with k3: cards.kpi_card("Tier 2 (mistag)", res.tier2_count)
    with k4: cards.kpi_card("Ambiguous", res.ambiguous_count)
    with k5: cards.kpi_card("Not found", res.not_found_count)

    st.caption(
        f"Candidate pools — Tier 1: {res.candidate_pool_t1:,} · "
        f"Tier 2: {res.candidate_pool_t2:,}"
    )

    tab_all, tab_mistag, tab_nf, tab_dl = st.tabs(
        ["📋 All results", "⚠️ Possible mistags", "❌ Not found", "📥 Downloads"]
    )

    with tab_all:
        q = st.text_input("Filter by any text", "", placeholder="Filter…",
                          label_visibility="collapsed", key="single_filter")
        view = df_en
        if q:
            patt = re.escape(q.strip())
            mask = view.apply(
                lambda c: c.astype(str).str.contains(patt, case=False, na=False, regex=True)
            ).any(axis=1)
            view = view[mask]
        st.dataframe(view, width="stretch", height=480, hide_index=True)
        st.caption(f"{len(view):,} of {len(df_en):,} rows")

    with tab_mistag:
        if "Match Status" in df_en.columns:
            mistag_df = df_en[df_en["Match Status"] == "Possible mistag"]
            if mistag_df.empty:
                cards.empty_state(
                    "No mistag candidates",
                    "All matches came from POIs that OSM tags correctly "
                    "for this category, or no Tier 2 hits passed the threshold.",
                    icon="✅",
                )
            else:
                st.caption(
                    "These input names were NOT found among correctly-tagged POIs, "
                    "but a high-similarity name was found among other named OSM features. "
                    "Likely an OSM data-quality gap — review whether the matched "
                    "feature represents the same real-world POI; if so, OSM is "
                    "missing the correct category tag for it."
                )
                st.dataframe(mistag_df, width="stretch", height=480, hide_index=True)

    with tab_nf:
        if "Match Status" in df_en.columns:
            nf_df = df_en[df_en["Match Status"].isin(["Not found", "Possible match"])]
            if nf_df.empty:
                cards.empty_state("Nothing here",
                                  "Every input name matched something.", icon="✅")
            else:
                st.caption(
                    "‘Not found’ — no usable similarity in either tier. "
                    "‘Possible match’ — closest candidate scored below threshold; "
                    "kept as diagnostic."
                )
                st.dataframe(nf_df, width="stretch", height=480, hide_index=True)

    with tab_dl:
        st.markdown("Download uses English column names and translated values.")
        d1, d2 = st.columns(2, gap="medium")
        with d1:
            st.markdown("**Excel (English)**")
            st.download_button(
                "⬇️ Download Excel",
                data=_styled_excel_bytes(df_en),
                file_name=f"{state['district']}_{state['sub_key']}_name_lookup.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )
            st.caption("Mirrors the standard pipeline schema + match metadata columns.")
        with d2:
            st.markdown("**CSV (English)**")
            st.download_button(
                "⬇️ Download CSV",
                data=df_en.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
                file_name=f"{state['district']}_{state['sub_key']}_name_lookup.csv",
                mime="text/csv",
                width="stretch",
            )

else:
    cards.divider()
    cards.empty_state(
        title="No lookup yet",
        text="Pick a district, choose a mode (mixed list is recommended for "
             "heterogeneous data), upload a name list, and press “Run Lookup”. "
             "Results appear here with the standard pipeline schema plus "
             "match-status columns.",
        icon="🔍",
    )


cards.footer()
