# Style & Convention Notes

Short reference for keeping the codebase consistent. Read once when joining
the project; revisit when adding a new module or page.

## Language layering: backend Turkish, UI English

The project uses a **two-language convention** that has emerged through
iteration:

- **Backend (Python identifiers, comments, log messages, raw column
  names)**: Turkish or domain-Turkish. Examples — `binalar_gdf`, `kapasite`,
  `mahalle`, `coz()`, `fizibilite_uyarisi`, `acik_alanlar`, `label_tr`,
  `boundary_status="ilçe_içi"`. This reflects the project's domain (Istanbul
  earthquake assembly planning) and keeps the rule registry (`tag_rules.py`,
  `category_registry.py`) honest about its primary audience.

- **User-facing UI (Streamlit pages, button labels, KPI labels, status
  banners, help tooltips, Excel headers)**: English. Examples — "Run
  optimization", "Pop coverage <5 min", "All categories failed", "Why
  Matched", "Outside district". This is for paydaş/decision-maker
  presentation; the project is positioned as decision support, not just an
  internal tool.

- **The translation layer**: `components/translations.py` (`to_english`,
  `translate_category_label`, `_STATUS_EN`, `_TAG_MATCH_EN`). Backend
  produces Turkish-keyed DataFrames; pages call `to_english(df)` at the
  display/export boundary. **Never** translate inside business logic —
  always at the page edge.

### Concrete rules

1. **Errors and exceptions raised from backend modules** that bubble up to
   the UI: prefer English. Reason: they end up in `st.error(f"... {e}")`
   strings on screen. Examples:
   - `raise ValueError("No buildings — optimization cannot run.")` ✓
   - `raise ValueError("Bina sayısı 0 — optimizasyon çalıştırılamaz.")` ✗

2. **Log messages routed through `cb()` callbacks** that get rendered in
   the UI log box: English. They are user-visible.

3. **Internal log messages** (file logger only, not shown in UI): Turkish
   is fine. Example: `log.debug("union sorgulanıyor: ...")`.

4. **DataFrame column names produced by the pipeline**: Turkish (`Mahalle`,
   `Enlem`, `Boylam`, `Alan (m²)`, `Sınır Durumu`). The Turkish ExcelExporter
   writes them as-is; pages call `to_english(df)` and the rename map flips
   them at display time.

5. **DataFrame **values** that surface to the user** (Confidence,
   Boundary Status, Access Quality): backend produces Turkish; the EN map
   in `translations.py` flips them. **New value-domains** that ship to the
   UI should add a `_EN` map in `translations.py` rather than translating
   inline.

6. **Excel sheet names**: Turkish for the legacy `ExcelExporter` (📊 Özet,
   🗺️ Mahalle Özeti, 🔍 Veri Kalitesi); English for the Data Extraction
   page workbook ("Summary", "Neighborhood Pivot", "Data Quality") and the
   optimization workbook ("1. Summary", "2. Methodology", ...). When in
   doubt, English.

7. **Proper nouns stay**: TÜİK, AFAD, OSM, OD, ILP, p95,
   AFAD m²/person — these are not translated. Surrounding sentence
   structure should match the host language.

8. **Comments**: Turkish dominates because the project's audit history is
   Turkish (P1.x, P2.x notes). Long-form comments, rationale, and
   "DÜZELTME"/"audit bulgusu" markers stay in Turkish. New code can use
   either; mixed is fine inside a single comment block.

## Caching conventions

- `@st.cache_resource`: NetworkX graphs, ML models, "single shared
  instance" objects.
- `@st.cache_data`: pure functions whose inputs are cheap to hash and
  whose outputs are pickle-safe (DataFrames, numpy arrays, dicts).
- Module-level Python `dict` caches (e.g. `_EXCEL_BYTES_CACHE`): only when
  Streamlit cache wouldn't apply (e.g. inputs aren't hashable in a useful
  way, or the cache key needs to be derived from `id(df)`). Bound the
  cache size; document the cross-session/cross-tenant assumption.

## Map / popup safety

- Any user-supplied or OSM-supplied string written into a folium popup or
  tooltip must go through `components.map_builder.safe_field()`.
- Any `color` value rendered into a `style="..."` attribute must go
  through `components.map_builder.safe_hex_color()`.
- Never inline f-string a raw column value into folium HTML.

## Provenance columns

When a derived value can come from multiple sources (measured vs.
estimated vs. inherited), surface the source in a `*_source` /
`*_status` column. Existing examples: `area_source` ("measured" /
"polygon_overlay" / "capacity_derived" / "estimated"),
`boundary_status` ("ilçe_içi" / "sınır_üstü" / "ilçe_dışı"),
`nufus_kaynak` ("estimated" / "neighbourhood_calibrated"). The user
can then filter on these in Excel/CSV, and the audit trail stays
transparent.

## Accessibility (a11y)

- Streamlit widget'larında `label_visibility="collapsed"` görsel
  olarak label'ı gizler ama label argümanını **aria-label** olarak
  korur — yani screen-reader bunu duyar. Bu yüzden `collapsed` modda
  bile label string'i **anlamlı ve betimleyici** olmalı:
  - ✅ `st.selectbox("District", ..., label_visibility="collapsed")`
  - ❌ `st.selectbox("x", ..., label_visibility="collapsed")`
  - ❌ `st.selectbox("", ..., label_visibility="collapsed")`
- Minimum 3 karakter, "x"/"…"/"label" gibi placeholder'lar yasak.
  `tests/test_a11y_widget_labels.py` bu kuralı otomatik denetler.
- Renk kontrastı için: `components/styles.py` token paleti WCAG AA
  hedefini tutar (KPI/sticky banner ≈ 7:1).

## Tests

- Whenever you change a user-visible string that a test asserts on,
  update the test to accept BOTH the old and new wording (TR fallback or
  EN fallback). Reason: future re-translation campaigns shouldn't leave
  a trail of broken assertions; tests should care about the *content
  signal*, not the exact phrasing.
- New features land with a regression test under `tests/`. The CI
  matrix runs Python 3.10/3.11/3.12.
