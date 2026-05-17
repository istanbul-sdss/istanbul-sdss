"""
name_lookup_service._pools — candidate-pool data structures + builders.

Two flavours of pool live here, intentionally side-by-side because they
share an enrich/build pattern:

  PreparedPools         — single-mode (one category): Tier 1 = pipeline
                          output, Tier 2 = all named features inside the
                          boundary minus what Tier 1 already matched.
  UniversalPool         — mixed-mode (auto-detect per row): one Overpass
                          fetch of every named feature in the district,
                          lazily augmented with per-rule tokenisations
                          when match_mixed_list sees a new category.

Candidate dataclasses (_Candidate, _UniversalCandidate) and the prepare
functions are all here so the matchers module can be pure orchestration
without knowing how the pool was built.

Imports kept thin: this file pulls from _scoring (for the alt-name
column list + variant extractor) but never from _tag_compat or _matchers
— the dep direction stays scoring → pools → matchers.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import geopandas as gpd
import pandas as pd

from src.config.name_lookup_rules import (
    normalize_tr,
    tokenize_for_match,
    tokenize_lite,
)
from src.config.tag_rules import get_rule
from src.logger import get_logger
from src.services.neighbourhood_loader import load_mahalleleri
from src.services.osm_service import (
    EMPTY_GDF,
    fetch_boundary,
    fetch_features_from_polygon,
)
from src.services.spatial_service import (
    add_footprint_area,
    add_lat_lon_from_point,
    assign_neighbourhoods,
    ensure_wgs84,
)

from ._scoring import _ALT_NAME_COLUMNS, _extract_name_variants

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
TIER1_DEFAULT_THRESHOLD = 80   # POIs already tagged correctly — relaxed
TIER2_DEFAULT_THRESHOLD = 85   # Wide named-feature pool — strict (false-pos guard)
MIXED_DEFAULT_THRESHOLD = 80

# Keep these tag columns on each candidate — they drive the OSM-Category
# inference and the tag-compatibility check.
_KEEP_TAG_COLUMNS = [
    "amenity", "building", "shop", "office", "leisure", "landuse",
    "natural", "tourism", "historic", "religion", "denomination",
    "healthcare", "public_transport", "railway", "highway",
    "man_made", "emergency",
]


# ─────────────────────────────────────────────────────────────────────────────
# CANDIDATE DATACLASSES
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class _Candidate:
    """A single OSM candidate row prepared for matching."""
    tokens: set[str]       # primary (Ad) tokens — kept for backward compat
    canonical: str         # joined sorted token string for primary
    variants: list[tuple[set[str], str]]  # (tokens, canonical) for every name source
    payload: dict          # column → value (already in pipeline schema)


@dataclass
class _UniversalCandidate:
    """A named OSM feature retained with all category-relevant tag columns.

    `lite_variants` carries the lite-tokenized form of every non-empty
    name source (`Ad`, `name:tr`, `alt_name`, `loc_name`, `official_name`,
    `short_name`, `brand`, `operator`). Scoring takes the max across
    variants so a POI whose user-supplied label only matches `alt_name`
    still surfaces. `raw_name_variants` is kept so rule-aware tokenization
    (per-category stopwords) can be re-run lazily inside `_get_rule_view`.
    """
    lite_variants:     list[tuple[set[str], str]]
    raw_name_variants: list[str]
    payload:           dict

    @property
    def lite_tokens(self) -> set[str]:
        return self.lite_variants[0][0] if self.lite_variants else set()

    @property
    def lite_canonical(self) -> str:
        return self.lite_variants[0][1] if self.lite_variants else ""


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC POOL TYPES
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class PreparedPools:
    """Frozen pools of candidates plus the boundary/mahalle context."""
    rule_code:        str
    cat_key:          str
    sub_key:          str
    ilce:             str
    tier1_candidates: list[_Candidate]
    tier2_candidates: list[_Candidate]


@dataclass
class UniversalPool:
    """All named features in a district plus boundary/mahalle context."""
    ilce:        str
    candidates:  list[_UniversalCandidate]
    # Lazy per-rule token caches: rule_code → list (parallel to .candidates)
    # where each entry is the list of (rule_tokens, canonical) variants for
    # that candidate's name sources (Ad, name:tr, alt_name…). Filled on
    # first detection of that rule.
    rule_token_cache: dict[str, list[list[tuple[set[str], str]]]]
    # Place-context stopwords: district + neighborhood names. These appear
    # as prefixes in OSM POI names ("Kadıköy Ahmet Sani Gezici …" or
    # "Kozyatağı Şükran Karabelli İlkokulu") and would otherwise create
    # spurious token gaps between user input (which omits them) and OSM
    # candidates. Computed once at pool prep time.
    place_stopwords: set[str]


# ─────────────────────────────────────────────────────────────────────────────
# CANDIDATE BUILDERS (Tier 1: rule-aware, Tier 2: lite)
# ─────────────────────────────────────────────────────────────────────────────
def _build_tier1_candidates(df: pd.DataFrame, rule_code: str) -> list[_Candidate]:
    if df.empty or "Ad" not in df.columns:
        return []
    cands: list[_Candidate] = []
    for _, row in df.iterrows():
        raw_variants = _extract_name_variants(row)
        if not raw_variants:
            continue
        variants: list[tuple[set[str], str]] = []
        for raw in raw_variants:
            toks = set(tokenize_for_match(raw, rule_code))
            if toks:
                variants.append((toks, " ".join(sorted(toks))))
        if not variants:
            continue
        primary_tokens, primary_canonical = variants[0]
        cands.append(_Candidate(
            tokens=primary_tokens,
            canonical=primary_canonical,
            variants=variants,
            payload={c: row[c] for c in df.columns if c in row.index},
        ))
    return cands


def _build_tier2_candidates(df: pd.DataFrame) -> list[_Candidate]:
    """
    Tier 2 uses LITE tokenization — generic stopwords only — applied
    symmetrically on both sides so the Jaccard / set-ratio math stays
    honest against arbitrary named features.
    """
    if df.empty or "Ad" not in df.columns:
        return []
    cands: list[_Candidate] = []
    for _, row in df.iterrows():
        raw_variants = _extract_name_variants(row)
        if not raw_variants:
            continue
        variants: list[tuple[set[str], str]] = []
        for raw in raw_variants:
            toks = set(tokenize_lite(raw))
            if toks:
                variants.append((toks, " ".join(sorted(toks))))
        if not variants:
            continue
        primary_tokens, primary_canonical = variants[0]
        cands.append(_Candidate(
            tokens=primary_tokens,
            canonical=primary_canonical,
            variants=variants,
            payload={c: row[c] for c in df.columns if c in row.index},
        ))
    return cands


# ─────────────────────────────────────────────────────────────────────────────
# TIER 2 — fetch + enrich named features
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_named_features(
    boundary_gdf: gpd.GeoDataFrame,
    progress_cb: Callable | None = None,
) -> gpd.GeoDataFrame:
    if boundary_gdf.empty:
        return EMPTY_GDF.copy()
    polygon = ensure_wgs84(boundary_gdf).geometry.iloc[0]
    if progress_cb:
        progress_cb("Tier 2: fetching all named OSM features...")
    try:
        gdf = fetch_features_from_polygon(polygon, tags={"name": True})
    except Exception as exc:
        log.warning(f"Tier 2 fetch failed: {exc}")
        return EMPTY_GDF.copy()
    if gdf.empty:
        return EMPTY_GDF.copy()
    if "rep_point" not in gdf.columns:
        gdf = gdf.copy()
        gdf["rep_point"] = gdf.geometry.representative_point()
    return gdf


def _enrich_tier2_features(
    gdf: gpd.GeoDataFrame,
    mahalleleri: gpd.GeoDataFrame | None,
    rule_code: str,
) -> pd.DataFrame:
    """
    Lift tier-2 GDF into the Turkish-named pipeline schema.
    Confidence is forced to 'Belirsiz' (mistag candidates are by
    definition not category-classified).
    """
    if gdf.empty:
        return pd.DataFrame()

    g = gdf.copy()
    g = add_lat_lon_from_point(g, point_col="rep_point")

    if mahalleleri is not None and not mahalleleri.empty:
        g = assign_neighbourhoods(g, mahalleleri, point_col="rep_point")

    # Real UTM area + point→polygon overlay fallback (see universal pool).
    g = add_footprint_area(g)

    if isinstance(g.index, pd.MultiIndex):
        g = g.reset_index()
        renames = {}
        if "element_type" in g.columns: renames["element_type"] = "element"
        if "osmid"        in g.columns: renames["osmid"]        = "id"
        if renames:
            g = g.rename(columns=renames)
    else:
        g = g.reset_index(drop=False)
        if "osmid" in g.columns and "id" not in g.columns:
            g = g.rename(columns={"osmid": "id"})
        if "element" not in g.columns:
            g["element"] = None

    rule  = get_rule(rule_code)
    label = rule.get("label_tr", rule_code)
    cgroup = rule.get("category_group", "")
    sub   = rule.get("subcategory", "")

    elem_map = {"node": "Nokta", "way": "Yol/Alan", "relation": "İlişki"}

    out = pd.DataFrame({
        "OSM Tipi":      g.get("element", pd.Series([None]*len(g))).astype(str)
                         .str.lower().map(lambda x: elem_map.get(x, x)),
        "OSM ID":        g.get("id"),
        "Ad":            g.get("name"),
        "Kategori":      cgroup,
        "Alt Kategori":  sub,
        "Kategori (TR)": label,
        "Kural Kodu":    rule_code,
        "Güven":         "Belirsiz",
        "Eşleşme Nedeni": "Ad eşleşmesi (mistag adayı)",
        "Enlem":         g.get("latitude"),
        "Boylam":        g.get("longitude"),
        "Mahalle":       g.get("neighbourhood") if "neighbourhood" in g.columns else None,
        "Sınır Durumu":  g.get("boundary_status") if "boundary_status" in g.columns else "ilçe_içi",
        "Tesis":         g.get("amenity"),
        "Sağlık Tipi":   g.get("healthcare"),
        "Bina Tipi":     g.get("building"),
        "Dükkan":        g.get("shop"),
        "Alan (m²)":     pd.to_numeric(g["footprint_m2"], errors="coerce").round(1)
                         if "footprint_m2" in g.columns else None,
        "Alan Kaynağı":  g.get("area_source") if "area_source" in g.columns else "",
    })
    # Preserve alt-name OSM tag columns when present so candidate building
    # can score against every name variant (name:tr, alt_name, loc_name…).
    for col in _ALT_NAME_COLUMNS:
        if col in g.columns:
            out[col] = g[col]
    return out


# ─────────────────────────────────────────────────────────────────────────────
# UNIVERSAL POOL — enrich + place-context stopword extractor
# ─────────────────────────────────────────────────────────────────────────────
def _enrich_universal_features(
    gdf: gpd.GeoDataFrame,
    mahalleleri: gpd.GeoDataFrame | None,
) -> pd.DataFrame:
    """
    Lift the raw name=* GDF into a uniform DataFrame, retaining tag
    columns that drive category inference (vs. _enrich_tier2_features
    which collapses to a single fixed schema).
    """
    if gdf.empty:
        return pd.DataFrame()

    g = gdf.copy()
    g = add_lat_lon_from_point(g, point_col="rep_point")
    if mahalleleri is not None and not mahalleleri.empty:
        g = assign_neighbourhoods(g, mahalleleri, point_col="rep_point")

    # Real UTM area for polygons; point→polygon overlay fallback uses the
    # SAME fetch's polygons as the overlay source. OSM commonly carries a
    # park as both a polygon (the actual geometry) AND a label Point (with
    # the name); the helper joins the two so the label inherits the parent
    # park's footprint. Output column: footprint_m2.
    g = add_footprint_area(g)

    if isinstance(g.index, pd.MultiIndex):
        g = g.reset_index()
        renames = {}
        if "element_type" in g.columns: renames["element_type"] = "element"
        if "osmid"        in g.columns: renames["osmid"]        = "id"
        if renames:
            g = g.rename(columns=renames)
    else:
        g = g.reset_index(drop=False)
        if "osmid" in g.columns and "id" not in g.columns:
            g = g.rename(columns={"osmid": "id"})
        if "element" not in g.columns:
            g["element"] = None

    elem_map = {"node": "Nokta", "way": "Yol/Alan", "relation": "İlişki"}

    base_cols = {
        "OSM Tipi":     g.get("element", pd.Series([None]*len(g))).astype(str)
                        .str.lower().map(lambda x: elem_map.get(x, x)),
        "OSM ID":       g.get("id"),
        "Ad":           g.get("name"),
        "Enlem":        g.get("latitude"),
        "Boylam":       g.get("longitude"),
        "Mahalle":      g.get("neighbourhood") if "neighbourhood" in g.columns else None,
        "Sınır Durumu": g.get("boundary_status") if "boundary_status" in g.columns else "ilçe_içi",
        "Alan (m²)":    pd.to_numeric(g["footprint_m2"], errors="coerce").round(1)
                        if "footprint_m2" in g.columns else None,
        "Alan Kaynağı": g.get("area_source") if "area_source" in g.columns else "",
    }
    out = pd.DataFrame(base_cols)
    # Preserve raw tag columns for downstream category inference & tag-compat.
    for col in _KEEP_TAG_COLUMNS:
        if col in g.columns:
            out[col] = g[col]
    # Preserve alt-name OSM tag columns when present so candidate building
    # can score against every name variant (name:tr, alt_name, loc_name…).
    for col in _ALT_NAME_COLUMNS:
        if col in g.columns:
            out[col] = g[col]
    return out


def _build_place_stopwords(ilce: str, mahalleleri: gpd.GeoDataFrame | None) -> set[str]:
    """
    Tokens that should be silently stripped during matching because they
    are pure place context (district / neighborhood prefixes), not the
    distinguishing element of a POI name.

    Examples this fixes:
        Input  "Şükran Karabelli İlkokulu"
        OSM    "Kozyatağı Şükran Karabelli İlkokulu"
        → Without place-stopwords: Jaccard penalty drops score to ~81.
        → With   place-stopwords: tokens equalize, score → 100.
    """
    stops: set[str] = set()
    # District itself
    for tok in normalize_tr(ilce).split():
        if len(tok) >= 2:
            stops.add(tok)
    # Each neighborhood name (split on whitespace; "Mahallesi" is generic noise)
    if mahalleleri is not None and not mahalleleri.empty:
        # neighbourhood_name is the canonical column produced by
        # neighbourhood_loader; keep the older candidate names as a fallback
        # for any custom GeoJSONs the project may pick up.
        name_col = next(
            (c for c in ["neighbourhood_name", "mahalle_adi", "mahalle",
                         "name", "Ad", "Adı", "AD"]
             if c in mahalleleri.columns),
            None,
        )
        if name_col is not None:
            for raw in mahalleleri[name_col].dropna().astype(str).tolist():
                # Strip the universal "Mahallesi" token; keep the actual name
                norm = normalize_tr(raw)
                for tok in norm.split():
                    if tok in {"mahallesi", "mahalle"}:
                        continue
                    if len(tok) >= 3:
                        stops.add(tok)
    return stops


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC PREP ENTRYPOINTS
# ─────────────────────────────────────────────────────────────────────────────
def prepare_pools(
    ilce: str,
    cat_key: str,
    sub_key: str,
    *,
    enable_tier2: bool = True,
    progress_cb: Callable | None = None,
) -> PreparedPools:
    """
    Heavy step — runs the existing pipeline (Tier 1) and optionally
    fetches all named features in the boundary (Tier 2). Pure of input
    names so the UI layer can cache it across multiple lookup runs.
    """
    # Local import: pipeline imports several services and would otherwise
    # create a tall import-time graph (some heavy modules import logger
    # which imports settings…). Local keeps name_lookup_service._pools
    # cheap to import when only the dataclasses are needed.
    from src.config.category_registry import get_subcategory_code
    from src.pipelines.pipeline import run_pipeline

    def cb(msg: str) -> None:
        log.info(msg)
        if progress_cb:
            progress_cb(msg)

    # category_registry.get_subcategory_code raises ValueError on miss; the
    # earlier `if rule_code is None` branch was unreachable. Re-raise with a
    # local context so callers see "<cat>/<sub>" together rather than only
    # the inner registry message.
    try:
        rule_code = get_subcategory_code(cat_key, sub_key)
    except ValueError as ve:
        raise ValueError(
            f"Invalid category/subcategory: {cat_key}/{sub_key} ({ve})"
        ) from ve

    # ── Tier 1: existing pipeline ────────────────────────────────────────
    cb(f"Tier 1: running pipeline for {ilce} / {get_rule(rule_code).get('label_tr', rule_code)}...")
    pr = run_pipeline(
        ilce=ilce,
        secimler=[(cat_key, sub_key)],
        progress_cb=progress_cb,
    )
    boundary    = pr["boundary"]
    mahalleleri = pr["mahalleleri"]
    t1_df = pd.DataFrame()
    if rule_code in pr["results"]:
        t1_df = pr["results"][rule_code].get("df", pd.DataFrame())

    t1_cands = _build_tier1_candidates(t1_df, rule_code)
    cb(f"Tier 1 pool: {len(t1_cands)} candidates")

    # ── Tier 2 (optional) ────────────────────────────────────────────────
    t2_cands: list[_Candidate] = []
    if enable_tier2:
        used_t1_ids = (
            set(t1_df["OSM ID"].dropna().astype(str))
            if "OSM ID" in t1_df.columns else set()
        )
        named_gdf = _fetch_named_features(boundary, progress_cb=progress_cb)
        if not named_gdf.empty:
            cb(f"Tier 2: {len(named_gdf)} raw named features, enriching with neighborhood/coordinates...")
            t2_df = _enrich_tier2_features(named_gdf, mahalleleri, rule_code)
            if not t2_df.empty and "OSM ID" in t2_df.columns:
                t2_df = t2_df[~t2_df["OSM ID"].astype(str).isin(used_t1_ids)].copy()
            t2_cands = _build_tier2_candidates(t2_df)
        cb(f"Tier 2 pool: {len(t2_cands)} candidates (excluding Tier 1)")

    return PreparedPools(
        rule_code=rule_code,
        cat_key=cat_key,
        sub_key=sub_key,
        ilce=ilce,
        tier1_candidates=t1_cands,
        tier2_candidates=t2_cands,
    )


def prepare_universal_pool(
    ilce: str,
    *,
    progress_cb: Callable | None = None,
) -> UniversalPool:
    """
    Single Overpass fetch of every named feature in the district boundary.
    Fast in-process; meant to be cached across UI runs.
    """
    def cb(msg: str) -> None:
        log.info(msg)
        if progress_cb:
            progress_cb(msg)

    cb(f"Universal pool: fetching {ilce} boundary...")
    boundary = fetch_boundary(f"{ilce}, İstanbul, Türkiye")

    cb(f"Universal pool: loading {ilce} neighborhoods...")
    mahalleleri = load_mahalleleri(ilce)

    cb("Universal pool: fetching all named OSM features (name=*)...")
    polygon = ensure_wgs84(boundary).geometry.iloc[0]
    try:
        gdf = fetch_features_from_polygon(polygon, tags={"name": True})
    except Exception as exc:
        log.warning(f"Universal pool fetch failed: {exc}")
        gdf = EMPTY_GDF.copy()

    place_stopwords = _build_place_stopwords(
        ilce, mahalleleri if not mahalleleri.empty else None
    )
    cb(f"Universal pool: marked {len(place_stopwords)} place-context tokens as stopwords")

    cands: list[_UniversalCandidate] = []
    if not gdf.empty:
        if "rep_point" not in gdf.columns:
            gdf = gdf.copy()
            gdf["rep_point"] = gdf.geometry.representative_point()
        cb(f"Universal pool: enriching {len(gdf)} raw records...")
        df = _enrich_universal_features(
            gdf, mahalleleri if not mahalleleri.empty else None
        )
        for _, row in df.iterrows():
            raw_variants = _extract_name_variants(row)
            if not raw_variants:
                continue
            # Lite tokens already strip GENERIC_STOPWORDS; subtract place
            # stopwords here too so the lite path agrees with the rule view.
            lite_variants: list[tuple[set[str], str]] = []
            for raw in raw_variants:
                tokens = set(tokenize_lite(raw)) - place_stopwords
                if tokens:
                    lite_variants.append((tokens, " ".join(sorted(tokens))))
            if not lite_variants:
                continue
            cands.append(_UniversalCandidate(
                lite_variants=lite_variants,
                raw_name_variants=raw_variants,
                payload={c: row[c] for c in df.columns if c in row.index},
            ))
    cb(f"Universal pool: {len(cands)} candidates ready")

    return UniversalPool(
        ilce=ilce,
        candidates=cands,
        rule_token_cache={},
        place_stopwords=place_stopwords,
    )
