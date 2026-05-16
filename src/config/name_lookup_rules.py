"""
src/config/name_lookup_rules.py — Name-based lookup normalization rules.

Used by name_lookup_service to match user-supplied name lists against
OSM-extracted POI names for a given (district, category).

Why this file exists:
    Naive fuzzy matching on Turkish POI names fails because every POI
    name carries a category-specific suffix ("Eczanesi", "İlkokulu",
    "Camii"). "Şifa" vs "Şifa Eczanesi" gets a low fuzzy score even
    though they're the same place. Stripping category-specific tokens
    BEFORE matching lifts hit-rates from ~50% to ~90%.

Key per code returns the exact rule code from tag_rules.py
(get_subcategory_code(cat_key, sub_key)).
"""

from __future__ import annotations

import re
import unicodedata

# ─────────────────────────────────────────────────────────────────────────────
# TURKISH NORMALIZATION
# ─────────────────────────────────────────────────────────────────────────────
_TR_TRANSLITERATE = str.maketrans({
    "ı": "i", "İ": "i", "I": "i",
    "ş": "s", "Ş": "s",
    "ç": "c", "Ç": "c",
    "ğ": "g", "Ğ": "g",
    "ö": "o", "Ö": "o",
    "ü": "u", "Ü": "u",
})

_PUNCT_RE = re.compile(r"[^\w\s]+", flags=re.UNICODE)
_WS_RE    = re.compile(r"\s+")


def normalize_tr(s: str | None) -> str:
    """
    Turkish-aware lowercase + transliterate + punctuation strip.

    "Şifa Eczanesi"  → "sifa eczanesi"
    "Dr. Ali's Pharmacy" → "dr alis pharmacy"
    """
    if s is None:
        return ""
    s = str(s)
    s = s.translate(_TR_TRANSLITERATE)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


# ─────────────────────────────────────────────────────────────────────────────
# STOPWORDS — generic (always stripped) + per rule_code
# ─────────────────────────────────────────────────────────────────────────────
# Generic noise: tokens that appear across all categories AND are
# vanishingly unlikely to be the distinguishing token of a POI.
# Be CONSERVATIVE here — this set is applied to every rule. Removing a
# token the user actually relies on for matching ("Merkez Eczanesi" →
# if "merkez" is generic-stripped, the candidate pool collapses) breaks
# recall silently. Only add when the token is BOTH common across
# categories AND nearly never the distinguishing element.
GENERIC_STOPWORDS: set[str] = {
    # Conjunctions / articles
    "ve", "and", "the", "of",
    # Corporate / legal — appear in chains/franchises
    "ltd", "sti", "san", "tic", "as", "a.s",
    # Academic / professional honorifics — never the distinguishing token,
    # often present in formal park/building names but absent from short
    # popular names. ("Prof. Dr. Kriton Curi Parkı" vs "Kriton Curi Parkı"
    # are the same park; the title is noise that crashed Jaccard otherwise.)
    "prof", "dr", "doc", "op", "av",
    # NOT included: "sehit", "gazi", "hz", "aziz" — these CAN be
    # distinguishing in Turkish POI naming and stripping them would
    # falsely merge different places.
}

# Per rule_code stopword sets (after normalize_tr).
# Keep these short — each token here is something the *category itself*
# adds that doesn't help disambiguate two POIs of the same category.
RULE_STOPWORDS: dict[str, set[str]] = {
    # ── Health ────────────────────────────────────────────────────────────
    "pharmacy":           {"eczane", "eczanesi", "ecz"},
    "hospital":           {"hastane", "hastanesi", "hospital"},
    "private_hospital":   {"hastane", "hastanesi", "ozel"},
    "public_hospital":    {"hastane", "hastanesi", "devlet", "kamu"},
    "clinic":             {"klinik", "kliniği", "poliklinik", "polikliniği", "tip", "merkezi"},
    "family_health":      {"asm", "aile", "sagligi", "saglik", "ocagi", "ocak", "merkezi", "hekimi", "hekimligi"},
    "dentist":            {"dis", "hekim", "hekimi", "klinik", "kliniği"},
    "emergency":          {"acil", "servis", "servisi"},
    "veterinary":         {"veteriner", "klinik", "kliniği"},
    "ambulance_station":  {"ambulans", "istasyon", "istasyonu", "112"},
    "optician":           {"optik", "gozluk", "gozlukcu"},

    # ── Education ─────────────────────────────────────────────────────────
    "primary_school":     {"ilkokul", "ilkokulu", "okul", "okulu", "ilk"},
    "middle_school":      {"ortaokul", "ortaokulu", "okul", "okulu"},
    "high_school":        {"lise", "lisesi", "anadolu", "fen", "meslek", "meslegi"},
    "public_school":      {"okul", "okulu", "devlet", "ilkokul", "ilkokulu", "ortaokul", "ortaokulu", "lise", "lisesi"},
    "private_school":     {"okul", "okulu", "ozel", "kolej", "koleji"},
    "education_university": {"universite", "universitesi", "fakulte", "fakultesi"},
    "student_dormitory":  {"yurt", "yurdu", "kyk", "ogrenci"},
    "kindergarten":       {"anaokul", "anaokulu", "kres", "kresi", "anasinifi"},
    "college_course":     {"dershane", "dershanesi", "kurs", "kursu", "egitim"},
    "library":            {"kutuphane", "kutuphanesi"},

    # ── Religious buildings ───────────────────────────────────────────────
    "building_mosque":    {"cami", "camii", "mescit", "mescidi"},
    "building_church":    {"kilise", "kilisesi"},
    "building_synagogue": {"sinagog", "sinagogu", "havra", "havrasi"},

    # ── Public / civic ────────────────────────────────────────────────────
    "building_police":         {"karakol", "karakolu", "polis", "merkezi", "amirligi"},
    "infrastructure_police":   {"karakol", "karakolu", "polis", "merkezi", "amirligi"},
    "building_fire_station":   {"itfaiye", "itfaiyesi", "istasyon", "istasyonu"},
    "infrastructure_fire_station": {"itfaiye", "itfaiyesi", "istasyon", "istasyonu"},
    "building_civic":          {"belediye", "belediyesi", "muhtarlik", "muhtar"},

    # ── Green areas ───────────────────────────────────────────────────────
    "park":               {"park", "parki", "bahce", "bahcesi"},
    "playground":         {"oyun", "alani", "park", "parki"},
    "pitch":              {"saha", "sahasi", "spor"},
    "assembly_point":     {"toplanma", "alani", "alan", "afet"},
    "garden":             {"bahce", "bahcesi", "botanik"},
    "forest":             {"orman", "ormani", "koruluk", "korulugu"},
    "cemetery":           {"mezarlik", "mezarligi", "kabristan"},
    "beach":              {"sahil", "plaj", "plaji"},
    "sports_centre":      {"spor", "kompleksi", "merkezi", "salonu", "salon"},
    "stadium":            {"stadyum", "stadyumu", "stat", "stadi"},

    # ── Transport ─────────────────────────────────────────────────────────
    "bus_stop":           {"otobus", "duragi", "durak"},
    "metro_station":      {"metro", "istasyonu", "istasyon"},
    "metrobus_stop":      {"metrobus", "duragi", "durak"},
    "tram_stop":          {"tramvay", "duragi", "durak"},
    "ferry_terminal":     {"vapur", "iskele", "iskelesi", "feribot"},
    "bus_station":        {"otogar", "otogari", "terminal", "terminali"},
    "parking":            {"otopark", "otoparki", "park"},
    "taxi":               {"taksi", "duragi", "durak"},
    "bridge":             {"kopru", "koprusu"},

    # ── Commerce ──────────────────────────────────────────────────────────
    "supermarket":        {"market", "marketi", "supermarket", "supermarketi"},
    "market":             {"market", "marketi", "bakkal", "bakkali"},
    "mall":               {"avm", "alisveris", "merkezi"},
    "bank":               {"bank", "bankasi"},
    "atm":                {"atm"},
    "restaurant":         {"restoran", "restorani", "lokanta", "lokantasi"},
    "cafe":               {"cafe", "kafe", "kafesi"},
    "post_office":        {"postane", "ptt"},
    "commerce_hotel":     {"otel", "oteli", "hotel"},
    "fuel":               {"benzin", "istasyonu", "akaryakit", "petrol"},

    # ── Infrastructure ────────────────────────────────────────────────────
    "power_substation":   {"trafo", "trafosu", "elektrik"},
    "water_tower":        {"su", "deposu", "depo"},
    "communication_tower": {"iletisim", "kule", "kulesi"},
    "waste_disposal":     {"cop", "atik", "toplama", "merkezi"},
    "recycling":          {"geri", "donusum", "merkezi", "kutusu"},

    # ── Culture ───────────────────────────────────────────────────────────
    "museum":             {"muze", "muzesi"},
    "historic_building":  {"tarihi", "yapi", "yapisi", "bina", "binasi"},
    "monument":           {"anit", "aniti"},
    "castle":             {"kale", "kalesi", "sur", "surlari"},
    "theatre":            {"tiyatro", "tiyatrosu", "sahne", "sahnesi"},
    "cinema":             {"sinema", "sinemasi"},
    "arts_centre":        {"kultur", "merkezi", "sanat"},
    "public_bath":        {"hamam", "hamami"},
}


def get_stopwords_for_rule(rule_code: str) -> set[str]:
    """Generic stopwords ∪ rule-specific stopwords (lowercased, normalized)."""
    return GENERIC_STOPWORDS | RULE_STOPWORDS.get(rule_code, set())


def tokenize_for_match(name: str | None, rule_code: str) -> list[str]:
    """
    Normalize → split → drop stopwords → drop tokens shorter than 2 chars.

    Returns the canonical token list used for matching.
    """
    norm = normalize_tr(name)
    if not norm:
        return []
    stops = get_stopwords_for_rule(rule_code)
    return [t for t in norm.split() if len(t) >= 2 and t not in stops]


def canonical_form(name: str | None, rule_code: str) -> str:
    """Joined canonical token form, useful for exact-after-normalize comparison."""
    return " ".join(tokenize_for_match(name, rule_code))


def tokenize_lite(name: str | None) -> list[str]:
    """
    Lighter tokenization that ONLY drops generic stopwords.

    Used for Tier 2 (mistag) matching where candidates are arbitrary named
    OSM features — not all of category X — so applying X's category-specific
    stopwords creates an asymmetry: stripping "eczanesi" from input but
    keeping "berber" in candidate.

    Both sides use this same lite tokenization in Tier 2, so stopword
    application is symmetric and Jaccard / token-set scoring stay honest.
    """
    norm = normalize_tr(name)
    if not norm:
        return []
    return [t for t in norm.split()
            if len(t) >= 2 and t not in GENERIC_STOPWORDS]


def canonical_form_lite(name: str | None) -> str:
    """Joined lite canonical (Tier 2 use)."""
    return " ".join(tokenize_lite(name))


# ─────────────────────────────────────────────────────────────────────────────
# CATEGORY AUTO-DETECTION (mixed-list mode)
# ─────────────────────────────────────────────────────────────────────────────
# Some rule_codes act as umbrellas — their patterns overlap with more
# specific siblings (e.g. building_school covers everything school-shaped,
# but primary_school/middle_school/high_school are sharper). When the
# longest pattern matches multiple rules, prefer non-umbrella ones.
_UMBRELLA_RULES: set[str] = {
    "building_school",
    "building_religious",
    "public_school",        # generic by virtue of `anadolu` matching every Anatolian school
}


def _build_rule_to_category_map() -> dict[str, tuple[str, str]]:
    """rule_code → (cat_key, sub_key) from CATEGORY_REGISTRY."""
    # Local import: avoid module-import cycle at top of name_lookup_rules.
    from src.config.category_registry import CATEGORY_REGISTRY
    m: dict[str, tuple[str, str]] = {}
    for ck, cv in CATEGORY_REGISTRY.items():
        for sub in cv.get("subcategories", []):
            m[sub["code"]] = (ck, sub["key"])
    return m


def _build_pattern_index() -> list[tuple[str, str]]:
    """
    Flatten all (pattern, rule_code) pairs from TAG_RULES.name_patterns
    sorted by pattern length DESCENDING so longest matches win.
    """
    from src.config.tag_rules import TAG_RULES
    pairs: list[tuple[str, str]] = []
    for rc, rule in TAG_RULES.items():
        for p in rule.get("name_patterns", []) or []:
            pairs.append((normalize_tr(p), rc))
    # Longest first — sub-patterns ("okul") never override ("ilkokul")
    pairs.sort(key=lambda x: (-len(x[0]), x[1]))
    # Drop empty patterns from edge-case rules
    return [(p, rc) for p, rc in pairs if p]


# Memoize once — TAG_RULES is static during process lifetime.
_PATTERN_INDEX: list[tuple[str, str]] | None = None
_RULE_TO_CAT: dict[str, tuple[str, str]] | None = None

# Maximum Turkish suffix length for word-prefix matching.
# Covers common cases: "park"→"parkı"(+1), "okul"→"okulu"(+1),
# "okul"→"okulları"(+4), "ev"→"evlerinin"(+7 — too long, rejected as
# expected — that's not category lexeme anyway).
_MAX_TR_SUFFIX = 4


def _pattern_matches(pattern: str, normalized: str) -> bool:
    """
    Pattern → input matching with word-aware semantics.

    Multi-word pattern  ("tıp merkezi", "halı saha") → substring match.
    Single-word pattern → token must equal pattern OR start with pattern
                          and have ≤ _MAX_TR_SUFFIX extra chars (Turkish
                          suffix). This prevents false positives like
                          "kurs" matching token "kursunoglu".
    """
    if " " in pattern:
        return pattern in normalized
    for tok in normalized.split():
        if tok == pattern:
            return True
        if tok.startswith(pattern) and (len(tok) - len(pattern)) <= _MAX_TR_SUFFIX:
            return True
    return False


def detect_category(name: str | None) -> tuple[str, str, str] | None:
    """
    Auto-detect (cat_key, sub_key, rule_code) from a POI name's suffix
    or keyword. Returns None when nothing matches confidently.

    Algorithm:
        1. Normalize the input name.
        2. Walk the pre-built pattern index (longest patterns first).
        3. The first rule whose pattern is a substring of the normalized
           name wins, EXCEPT umbrella rules — if a non-umbrella rule with
           the same-length pattern also matches, the non-umbrella one wins.
        4. Returns (cat_key, sub_key, rule_code) or None.

    Examples:
        "Atatürk İlkokulu"        → ("education", "primary_school", "primary_school")
        "Şifa Camii"              → ("buildings", "mosque",         "building_mosque")
        "19 Mayıs Parkı"          → ("green_area", "park",          "park")
        "Mehmet Eczanesi"         → ("health",    "pharmacy",       "pharmacy")
        "Kadıköy Meydanı"         → None  (no suffix match → fuzzy fallback)
    """
    global _PATTERN_INDEX, _RULE_TO_CAT
    if _PATTERN_INDEX is None:
        _PATTERN_INDEX = _build_pattern_index()
    if _RULE_TO_CAT is None:
        _RULE_TO_CAT = _build_rule_to_category_map()

    norm = normalize_tr(name)
    if not norm:
        return None

    last_tok = norm.split()[-1] if norm.split() else ""

    def _matches_last_token(pat: str) -> bool:
        if " " in pat:
            return pat in last_tok
        return last_tok == pat or (
            last_tok.startswith(pat)
            and (len(last_tok) - len(pat)) <= _MAX_TR_SUFFIX
        )

    best: tuple[str, str, bool] | None = None    # (pattern, rule_code, hits_last)
    best_len = 0
    for pat, rc in _PATTERN_INDEX:
        if len(pat) < best_len:
            # Index sorted desc; remaining are shorter
            break
        if not _pattern_matches(pat, norm):
            continue
        hits_last = _matches_last_token(pat)
        if best is None:
            best = (pat, rc, hits_last); best_len = len(pat); continue
        # Same-length collision: priority order
        #   (1) pattern that matches LAST token (Turkish suffix position)
        #   (2) non-umbrella over umbrella
        if len(pat) == best_len:
            if hits_last and not best[2]:
                best = (pat, rc, hits_last)
            elif hits_last == best[2]:
                if best[1] in _UMBRELLA_RULES and rc not in _UMBRELLA_RULES:
                    best = (pat, rc, hits_last)

    if best is None:
        return None
    rule_code = best[1]
    if rule_code not in _RULE_TO_CAT:
        return None
    cat_key, sub_key = _RULE_TO_CAT[rule_code]
    return (cat_key, sub_key, rule_code)
