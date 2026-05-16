"""
pages/1_Data_Extraction.py — Run the OSM extraction pipeline.

Workflow:
    1. Select district
    2. Select categories (preset, all, or manual)
    3. Choose export formats
    4. Run — results land in st.session_state for all other pages to use
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
from components.state import (
    KEY_EXCEL_PATH,
    KEY_PIPELINE_RESULT,
    KEY_SELECTED_CATEGORIES,
    KEY_SELECTED_DISTRICT,
    get_nonempty_results,
    has_data,
    init_state,
)
from components.styles import configure_page
from components.translations import (
    get_main_category_options_en,
    get_subcategory_options_en,
    to_english,
    translate_category_label,
)
from src.config.category_registry import get_subcategory_code
from src.config.settings import ISTANBUL_ILCELER, MAH_DIR_STR, OUTPUT_DIR
from src.config.tag_rules import get_rule
from src.logger import get_logger
from src.pipelines.pipeline import run_pipeline
from src.services.excel_exporter import ExcelExporter
from src.services.neighbourhood_loader import dosya_adi, get_overpass_query, list_available
from src.utils import df_content_hash, nonempty_signature

log = get_logger("page.data_extraction")


# ── Excel/CSV bytes cache ──────────────────────────────────────────────────
# Streamlit her widget tıklamasında script'i baştan çalıştırır → Downloads
# tab'ındaki Excel workbook (style, autosize, multi-sheet) ve CSV bytes
# her seferinde yeniden inşa edilir. Şişli/Esenyurt gibi büyük ilçelerde
# 1-3 saniyelik gözle görülür gecikme. Süreç-içi bounded cache: aynı
# extraction için bytes yeniden üretilmez.
_EXCEL_BYTES_CACHE: dict[tuple, bytes] = {}
_CSV_BYTES_CACHE:   dict[tuple, bytes] = {}
_BYTES_CACHE_MAX = 2  # her tip için son 2 farklı extraction yeter


# Cache key helpers `src/utils.py` altında; H3 düzeltmesi orada belgelendi.
# Bu sayfada yerel alias bırakıyoruz çünkü 2 yerden çağrılıyor ve isim
# tutarlılığı (`_nonempty_signature`) korunsun istiyoruz.
_nonempty_signature = nonempty_signature
_df_content_hash = df_content_hash


def _build_excel_bytes_cached(
    nonempty: dict,
    all_df_en: pd.DataFrame,
    district: str,
) -> bytes:
    """Excel workbook bytes — cache hit'te O(1). Bkz. _BYTES_CACHE_MAX."""
    key = (district, _nonempty_signature(nonempty), _df_content_hash(all_df_en))
    cached = _EXCEL_BYTES_CACHE.get(key)
    if cached is not None:
        return cached
    bytes_out = _build_excel_bytes(nonempty, all_df_en, district)
    if len(_EXCEL_BYTES_CACHE) >= _BYTES_CACHE_MAX:
        _EXCEL_BYTES_CACHE.pop(next(iter(_EXCEL_BYTES_CACHE)))
    _EXCEL_BYTES_CACHE[key] = bytes_out
    return bytes_out


def _build_excel_bytes(
    nonempty: dict,
    all_df_en: pd.DataFrame,
    district: str,
) -> bytes:
    """
    Çok-sayfalı stilize Excel workbook üretir; cache miss'te tek seferlik
    pahalı iş. Stil katmanı src/services/excel_utils.py'a taşındı.
    """
    from src.services.excel_utils import build_styled_workbook

    def _write_sheets(writer: pd.ExcelWriter) -> None:
        # ── 1 · Summary ─────────────────────────────────────────────
        summary_rows = []
        for kat, res in nonempty.items():
            df_en = to_english(res["df"])
            summary_rows.append({
                "Category":      translate_category_label(res.get("label_tr") or kat),
                "Records":       len(df_en),
                "Neighborhoods": df_en["Neighborhood"].nunique() if "Neighborhood" in df_en.columns else 0,
                "With coords":   int(df_en["Latitude"].notna().sum()) if "Latitude" in df_en.columns else 0,
                "With area":     int(df_en["Area (m²)"].notna().sum()) if "Area (m²)" in df_en.columns else 0,
                "High conf.":    int((df_en["Confidence"] == "High").sum()) if "Confidence" in df_en.columns else 0,
                "Medium conf.":  int((df_en["Confidence"] == "Medium").sum()) if "Confidence" in df_en.columns else 0,
            })
        summary_df = pd.DataFrame(summary_rows)
        if not summary_df.empty:
            total_row = {"Category": "TOTAL"}
            for c in summary_df.columns:
                if c == "Category":
                    continue
                total_row[c] = int(summary_df[c].sum())
            summary_df = pd.concat(
                [summary_df, pd.DataFrame([total_row])], ignore_index=True
            )
        summary_df.to_excel(writer, sheet_name="Summary", index=False)

        # ── 2 · Neighborhood × Category pivot ───────────────────────
        if "Neighborhood" in all_df_en.columns and "Category" in all_df_en.columns:
            pivot = (
                all_df_en.groupby(["Neighborhood", "Category"])
                .size()
                .unstack(fill_value=0)
            )
            pivot["TOTAL"] = pivot.sum(axis=1)
            pivot = pivot.sort_values("TOTAL", ascending=False)
            col_totals = pivot.sum(axis=0).to_frame().T
            col_totals.index = ["TOTAL"]
            pivot_out = pd.concat([pivot, col_totals])
            pivot_out.to_excel(writer, sheet_name="Neighborhood Pivot")

        # ── 3 · Per-category detail sheets ──────────────────────────
        used_names: set[str] = {"Summary", "Neighborhood Pivot", "Data Quality"}
        for kat, res in nonempty.items():
            df_en = to_english(res["df"])
            base = translate_category_label(res.get("label_tr") or kat)[:28]
            base = re.sub(r"[\\/\*\?\[\]:]", "-", base).strip() or "Category"
            name, i = base, 1
            while name in used_names:
                i += 1
                name = f"{base[:26]} {i}"
            used_names.add(name)
            df_en.to_excel(writer, sheet_name=name, index=False)

        # ── 4 · Data Quality ────────────────────────────────────────
        quality_rows = []
        for kat, res in nonempty.items():
            df_en = to_english(res["df"])
            n = len(df_en)
            if n == 0:
                continue

            # B023: loop'ta `df_en` her iterasyonda yeniden atanıyor → closure
            # late binding tehlikesi. Default-arg capture ile çağrı anındaki
            # df_en'i bağla; çağrı senkron olduğu için pratik fark yok ama
            # best practice.
            def pct(col, _df=df_en):
                return round(_df[col].notna().mean() * 100, 1) \
                       if col in _df.columns else 0.0

            mah_pct   = pct("Neighborhood")
            coord_pct = pct("Latitude")
            area_pct  = pct("Area (m²)")
            conf_high = round(
                (df_en["Confidence"] == "High").mean() * 100, 1
            ) if "Confidence" in df_en.columns else 0.0

            quality_rows.append({
                "Category":          translate_category_label(res.get("label_tr") or kat),
                "Records":           n,
                "Neighborhood %":    mah_pct,
                "Coordinates %":     coord_pct,
                "Area %":            area_pct,
                "High confidence %": conf_high,
                "Overall %":         round((mah_pct + coord_pct + area_pct) / 3, 1),
            })
        if quality_rows:
            pd.DataFrame(quality_rows).to_excel(
                writer, sheet_name="Data Quality", index=False
            )

    return build_styled_workbook(
        _write_sheets,
        total_row_sheets=("Summary", "Neighborhood Pivot"),
        skip_autofilter_sheets=("Neighborhood Pivot",),
        highlight_last_column_sheets=("Neighborhood Pivot",),
    )


def _build_csv_bytes_cached(nonempty: dict) -> bytes:
    """CSV unified bytes — aynı extraction için cache hit."""
    key = _nonempty_signature(nonempty)
    cached = _CSV_BYTES_CACHE.get(key)
    if cached is not None:
        return cached
    df = pd.concat(
        [to_english(v["df"]) for v in nonempty.values()],
        ignore_index=True,
    ) if nonempty else pd.DataFrame()
    bytes_out = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    if len(_CSV_BYTES_CACHE) >= _BYTES_CACHE_MAX:
        _CSV_BYTES_CACHE.pop(next(iter(_CSV_BYTES_CACHE)))
    _CSV_BYTES_CACHE[key] = bytes_out
    return bytes_out

# ════════════════════════════════════════════════════════════════════════════
# PAGE SETUP
# ════════════════════════════════════════════════════════════════════════════
configure_page(title="Data Extraction", icon="📊")
init_state()


# ════════════════════════════════════════════════════════════════════════════
# SIDEBAR — selection controls
# ════════════════════════════════════════════════════════════════════════════
cards.sidebar_brand()

# ── District ────────────────────────────────────────────────────────────────
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

avail = list_available()
if district in avail:
    # A1 kontrast düzeltmesi: koyu sidebar zemini üzerinde açık-yeşil
    # arka plan + koyu-yeşil yazı düşük kontrast veriyordu (pill nerdeyse
    # okunmuyordu). Şimdi koyu-yeşil pill + beyaz yazı + parlak yeşil
    # border ile sidebar arka planından net ayrışıyor.
    st.sidebar.markdown(
        f'<div style="background:#065F46;color:#FFFFFF;padding:8px 12px;'
        f'border-radius:8px;font-size:0.8125rem;margin:6px 0;'
        f'border-left:3px solid #10B981">'
        f'✅ Neighbourhood data available for <b style="color:#A7F3D0">{district}</b></div>',
        unsafe_allow_html=True,
    )
else:
    # A1: aynı kontrast düzeltmesi sarı/uyarı pill için.
    st.sidebar.markdown(
        f'<div style="background:#78350F;color:#FFFFFF;padding:8px 12px;'
        f'border-radius:8px;font-size:0.8125rem;margin:6px 0;'
        f'border-left:3px solid #F59E0B">'
        f'⚠️ Missing neighbourhood data for <b style="color:#FDE68A">{district}</b></div>',
        unsafe_allow_html=True,
    )
    with st.sidebar.expander("Overpass Turbo query"):
        st.code(get_overpass_query(district), language="text")
        st.caption(f"Target path: `{MAH_DIR_STR}/{dosya_adi(district)}.geojson`")

st.sidebar.markdown("---")

# ── Categories ──────────────────────────────────────────────────────────────
st.sidebar.markdown("### 2 · Categories")
quick = st.sidebar.radio(
    "Preset",
    ["Essential Set", "Manual Select"],
    index=0,
    label_visibility="collapsed",
)

ESSENTIAL_SET = [
    ("health",         "hospital"),
    ("health",         "pharmacy"),
    ("education",      "primary_school"),
    ("green_area",     "park"),
    ("green_area",     "assembly_point"),
    ("infrastructure", "police"),
    ("infrastructure", "fire_station"),
]

selections: list[tuple[str, str]] = []

if quick == "Essential Set":
    selections = ESSENTIAL_SET
    with st.sidebar.expander("Included in Essential Set", expanded=False):
        chips_html = []
        for ck, sk in ESSENTIAL_SET:
            rc = get_subcategory_code(ck, sk)
            tr_label = get_rule(rc).get("label_tr", sk) if rc else sk
            en_label = translate_category_label(tr_label)
            chips_html.append(
                f'<span style="display:inline-block;'
                f'padding:4px 10px;margin:3px 4px 3px 0;'
                f'background:rgba(59,130,246,0.12);'
                f'border:1px solid rgba(59,130,246,0.35);'
                f'border-radius:999px;color:#BFDBFE;'
                f'font-size:0.78rem;font-weight:500;'
                f'white-space:nowrap;">{en_label}</span>'
            )
        st.markdown(
            f'<div style="line-height:1.9">{"".join(chips_html)}</div>',
            unsafe_allow_html=True,
        )

else:  # Manual Select
    # "Categories" başlığı — manuel seçim listesinin üstünde görsel
    # ayrım. Streamlit nested expander'a izin vermediği için outer
    # element bir markdown başlığı (alt-kategori expander'ları onun
    # altında zaten kategori-bazlı açılıp kapanıyor).
    st.sidebar.markdown(
        '<div style="font-size:0.82rem;font-weight:600;color:#94A3B8;'
        'text-transform:uppercase;letter-spacing:0.04em;margin:8px 0 4px">'
        'Categories</div>',
        unsafe_allow_html=True,
    )
    for cat in get_main_category_options_en():
        ck = cat["key"]
        if ck == "admin_boundaries":
            continue
        subs = get_subcategory_options_en(ck)
        all_flag = st.session_state.get(f"all_{ck}", False)
        n_sel = (
            len(subs) if all_flag
            else sum(1 for s in subs if st.session_state.get(f"cb_{s['code']}", False))
        )
        lbl = f"{cat['label']}  ✓{n_sel}" if n_sel else cat["label"]

        with st.sidebar.expander(lbl, expanded=(n_sel > 0)):
            all_checked = st.checkbox("Select all", key=f"all_{ck}")
            if all_checked:
                st.caption(f"→ {len(subs)} sub-categories selected")
                for sub in subs:
                    selections.append((ck, sub["key"]))
            else:
                for sub in subs:
                    if st.checkbox(sub["label"], key=f"cb_{sub['code']}"):
                        selections.append((ck, sub["key"]))

st.session_state[KEY_SELECTED_CATEGORIES] = selections

st.sidebar.markdown("---")

# ── Outputs ─────────────────────────────────────────────────────────────────
st.sidebar.markdown("### 3 · Output formats")
out_excel   = st.sidebar.checkbox("Excel (.xlsx)", value=True)
out_csv     = st.sidebar.checkbox("CSV",           value=False)
out_geojson = st.sidebar.checkbox("GeoJSON",       value=False)

st.sidebar.markdown("---")

run_btn = st.sidebar.button(
    "🚀 Run Extraction",
    width="stretch",
    type="primary",
    disabled=not selections,
)
if not selections:
    st.sidebar.warning("Select at least one category.")

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
# MAIN — page header + stepper
# ════════════════════════════════════════════════════════════════════════════
cards.page_header(
    eyebrow="Workflow · Step 1 of 4",
    title="Data Extraction",
    subtitle="Select a district and data categories, then run the extraction pipeline.",
)

# Step indicator (computed from current state)
current_step = 2 if has_data() else (1 if selections else 0)
cards.stepper(
    ["Configure", "Extract", "Export", "Analyze"],
    current=current_step,
)

# Context strip
cards.status_strip([
    {"label": "District:",    "value": district,                 "tone": "ok" if district in avail else "warn"},
    {"label": "Categories:",  "value": f"{len(selections)}",     "tone": "ok" if selections else "warn"},
    {"label": "Data status:", "value": "Loaded" if has_data() else "Not run",
     "tone": "ok" if has_data() else None},
])


# ════════════════════════════════════════════════════════════════════════════
# PIPELINE EXECUTION
# ════════════════════════════════════════════════════════════════════════════
if run_btn and selections:
    cards.divider()
    st.markdown("### Extraction log")

    progress = st.progress(0)
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
        status_ph.markdown("**[1/2] Fetching OSM data…**")
        t0 = time.time()

        pr = run_pipeline(ilce=district, secimler=selections, progress_cb=ui_log)
        progress.progress(60)
        st.session_state[KEY_PIPELINE_RESULT] = pr

        results  = pr["results"]
        nonempty = {k: v for k, v in results.items() if not v["df"].empty}
        total    = sum(len(v["df"]) for v in nonempty.values())

        # P2.4: failure semantics — tam başarısızlık vs. kısmi başarı vs. başarı
        failed_categories = pr.get("failed_categories", [])
        error_count       = pr.get("error_count", 0)
        all_failed        = pr.get("all_failed", False)

        if all_failed:
            ui_log(f"❌ OSM TOTAL FAILURE: {error_count}/{len(selections)} categories errored, no records fetched")
        elif error_count > 0:
            ui_log(
                f"⚠️ OSM partial success: {len(nonempty)} categories OK, "
                f"{error_count} failed, {total:,} records total "
                f"({time.time()-t0:.1f}s)"
            )
        else:
            ui_log(f"✅ OSM complete: {total:,} records across {len(nonempty)} categories ({time.time()-t0:.1f}s)")

        # Hata alan kategorileri yapısal uyarı bloğu olarak göster
        if failed_categories:
            err_lines = []
            for fc in failed_categories:
                err_lines.append(
                    f"- **{fc['cat_key']}/{fc['sub_key']}** "
                    f"({fc['error_type']}): {fc['message']}"
                )
            err_block = "\n".join(err_lines)
            if all_failed:
                st.error(
                    "❌ **All categories failed — no data was fetched.**\n\n"
                    f"{err_block}\n\n"
                    "Possible causes: Overpass service may be down, no internet "
                    "connection, or the district name / boundary could not be "
                    "resolved. Wait a few minutes and try again."
                )
            else:
                st.warning(
                    f"⚠️ **{error_count} categories failed** — the others completed.\n\n"
                    f"{err_block}"
                )

        # P2.3: kısmi OSM başarısızlıklarını kullanıcıya yapısal uyarı olarak göster.
        # Pipeline her kategori sonucuna `partial_failure` ve `failed_tags` ekleyebiliyor;
        # burada toplayıp tek bir warning bloğuna dönüştürüyoruz. Aksi halde bilgi
        # log'da kayboluyordu, kullanıcı eksik veriyi "tamamlandı" olarak yorumluyordu.
        partial_categories = {
            k: v for k, v in results.items() if v.get("partial_failure")
        }
        if partial_categories:
            lines = []
            for cat, res in partial_categories.items():
                failed = res.get("failed_tags", [])
                net    = res.get("network_failed_count", 0)
                lines.append(
                    f"- **{cat}** — {len(failed)} queries failed "
                    f"({net} network errors, {len(failed)-net} other)"
                )
            st.warning(
                "⚠️ **Some OSM queries failed — results may be incomplete.**\n\n"
                + "\n".join(lines)
                + "\n\nRecord counts in these categories may be lower than "
                  "reality; check your connection / Overpass status and retry."
            )

        # Sınır dışı (komşu ilçeden sızmış) kayıtları kullanıcıya bildir.
        # Excel'de "Sınır Durumu" / "Boundary Status" kolonundan filtrelenebilir.
        outside_categories = {
            k: v.get("outside_count", 0)
            for k, v in results.items()
            if v.get("outside_count", 0) > 0
        }
        if outside_categories:
            outside_lines = [
                f"- **{cat}** — {n} records"
                for cat, n in outside_categories.items()
            ]
            total_outside = sum(outside_categories.values())
            st.info(
                f"ℹ️ **{total_outside} records appear OUTSIDE the selected "
                f"district boundary** — likely Overpass leakage from "
                f"neighbouring districts (e.g. polygons crossing the boundary, "
                f"or small differences between the OSM admin boundary and the "
                f"Nominatim boundary).\n\n"
                + "\n".join(outside_lines)
                + "\n\nThe records were kept in the dataset; you can filter "
                  "them out in Excel/CSV by the **Boundary Status** column "
                  "(values **`Outside district`** / `ilçe_dışı`)."
            )

        progress.progress(85)
        status_ph.markdown("**[2/2] Preparing exports…**")

        if nonempty and out_excel:
            exp = ExcelExporter()
            epath = exp.export(results=nonempty, ilce=district)
            st.session_state[KEY_EXCEL_PATH] = epath
            ui_log(f"✅ Excel saved: {Path(epath).name}")

        if nonempty and out_geojson:
            from src.services.export_service import prepare_gdf_for_file_export
            for kat, res in nonempty.items():
                if not res["gdf"].empty:
                    safe = kat.replace("/", "_").replace(" ", "_")
                    fpath = OUTPUT_DIR / f"{district}_{safe}.geojson"
                    prepare_gdf_for_file_export(res["gdf"]).to_file(
                        str(fpath), driver="GeoJSON"
                    )
            ui_log("✅ GeoJSON files saved")

        if nonempty and out_csv:
            all_df = pd.concat(
                [to_english(v["df"]) for v in nonempty.values()],
                ignore_index=True,
            )
            csv_p = OUTPUT_DIR / f"{district}_all_data.csv"
            all_df.to_csv(csv_p, index=False, encoding="utf-8-sig")
            ui_log(f"✅ CSV saved: {csv_p.name}")

        progress.progress(100)
        elapsed = time.time() - t0
        # P2.4: durum kutusu rengi failure state'e göre seçilir.
        if all_failed:
            status_ph.markdown(
                cards.status_banner(
                    f"Failed — 0 records, all {len(selections)} categories errored "
                    f"({elapsed:.1f}s)",
                    tone="error",
                ),
                unsafe_allow_html=True,
            )
        elif error_count > 0:
            status_ph.markdown(
                cards.status_banner(
                    f"Partial success — {total:,} records, "
                    f"{len(nonempty)}/{len(selections)} categories OK, "
                    f"{error_count} failed ({elapsed:.1f}s)",
                    tone="warning",
                ),
                unsafe_allow_html=True,
            )
        else:
            status_ph.markdown(
                cards.status_banner(
                    f"Completed — {total:,} records, {len(nonempty)} categories "
                    f"({elapsed:.1f}s)",
                    tone="success",
                ),
                unsafe_allow_html=True,
            )

    except Exception as e:
        # Kullanıcıya yalnızca kısa hata mesajı; tam traceback log dosyasına gider.
        # st.exception(e) iç dosya yollarını ve sistem detaylarını ifşa ediyordu.
        st.error(f"❌ Pipeline failed: {type(e).__name__}: {e}")
        log.error("Pipeline error", exc_info=True)


# ════════════════════════════════════════════════════════════════════════════
# RESULTS (always visible when data is present)
# ════════════════════════════════════════════════════════════════════════════
if has_data():
    nonempty = get_nonempty_results()

    # Merge all results for aggregate metrics (keep TR for backend compatibility,
    # translate only at display/export time).
    all_df_tr = pd.concat([v["df"] for v in nonempty.values()], ignore_index=True)
    all_df_en = to_english(all_df_tr)

    cards.divider()
    cards.section_title("Extraction summary", f"{district} — aggregate view")

    # KPI row
    k1, k2, k3, k4, k5 = st.columns(5, gap="small")
    with k1:
        cards.kpi_card("Total records", len(all_df_en))
    with k2:
        cards.kpi_card("Categories", len(nonempty))
    with k3:
        cards.kpi_card(
            "Neighborhoods",
            all_df_en["Neighborhood"].nunique() if "Neighborhood" in all_df_en.columns else 0,
        )
    with k4:
        cards.kpi_card(
            "With area",
            int(all_df_en["Area (m²)"].notna().sum()) if "Area (m²)" in all_df_en.columns else 0,
        )
    with k5:
        hi = int((all_df_en["Confidence"] == "High").sum()) if "Confidence" in all_df_en.columns else 0
        cards.kpi_card("High confidence", hi)

    # Tabs: Data · Downloads · Neighborhood pivot
    tab_data, tab_dl, tab_pivot = st.tabs(
        ["📋 Data", "📥 Downloads", "🏘️ Neighborhood Pivot"]
    )

    # ── Data tab ────────────────────────────────────────────────────────────
    with tab_data:
        cat_labels = [
            f"{translate_category_label(res.get('label_tr') or k)} ({len(res['df']):,})"
            for k, res in nonempty.items()
        ]
        cat_tabs = st.tabs(cat_labels)

        for ct, (kat, res) in zip(cat_tabs, nonempty.items()):
            df_en = to_english(res["df"])
            with ct:
                # Confidence distribution
                if "Confidence" in df_en.columns:
                    c1, c2, c3 = st.columns(3, gap="small")
                    dist = df_en["Confidence"].value_counts().to_dict()
                    with c1: cards.kpi_card("High",    int(dist.get("High", 0)))
                    with c2: cards.kpi_card("Medium",  int(dist.get("Medium", 0)))
                    with c3: cards.kpi_card("Low / Unknown",
                                            int(dist.get("Low", 0) + dist.get("Unknown", 0)))

                left, right = st.columns([3, 1], gap="medium")
                with left:
                    query = st.text_input(
                        "Search",
                        key=f"search_{kat}",
                        placeholder="Search across name, neighborhood, type…",
                        label_visibility="collapsed",
                    )
                    dshow = df_en
                    if query:
                        patt = re.escape(query.strip())
                        # B023: outer-scope `patt` lambda'da late-bind olur;
                        # apply senkron olduğu için pratik bug değil ama
                        # default-arg capture en sade düzeltme.
                        mask = dshow.apply(
                            lambda c, _patt=patt: c.astype(str).str.contains(
                                _patt, case=False, na=False, regex=True
                            )
                        ).any(axis=1)
                        dshow = dshow[mask]
                    st.dataframe(dshow, width="stretch", height=380, hide_index=True)
                    st.caption(f"{len(dshow):,} of {len(df_en):,} records")

                with right:
                    if "Neighborhood" in df_en.columns:
                        st.markdown("**Top neighborhoods**")
                        top = df_en["Neighborhood"].value_counts().head(12).reset_index()
                        top.columns = ["Neighborhood", "Count"]
                        st.dataframe(top, width="stretch", height=380, hide_index=True)

    # ── Downloads tab ───────────────────────────────────────────────────────
    with tab_dl:
        st.markdown(
            "All downloads use English column names and translated values "
            "(High / Medium / Low confidence, etc.)."
        )

        d1, d2, d3 = st.columns(3, gap="medium")

        # Excel (English) — cache'lenmiş builder; aynı extraction için
        # rerun'larda bytes yeniden üretilmez.
        with d1:
            st.markdown("**Excel workbook (English)**")
            excel_bytes = _build_excel_bytes_cached(
                nonempty, all_df_en, district
            )
            st.download_button(
                "⬇️ Download Excel",
                data=excel_bytes,
                file_name=f"{district}_OSM_en.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )
            st.caption(
                "Sheets: Summary · Neighborhood Pivot · per-category · Data Quality"
            )

        # CSV (English) — cache'lenmiş builder
        with d2:
            st.markdown("**Unified CSV (English)**")
            csv_data = _build_csv_bytes_cached(nonempty)
            st.download_button(
                "⬇️ Download CSV",
                data=csv_data,
                file_name=f"{district}_all_data_en.csv",
                mime="text/csv",
                width="stretch",
            )

        # GeoJSON (per category)
        with d3:
            st.markdown("**GeoJSON (per category)**")
            from src.services.export_service import prepare_gdf_for_file_export
            offered = 0
            for kat, res in nonempty.items():
                if not res["gdf"].empty and offered < 3:
                    gj = prepare_gdf_for_file_export(res["gdf"]).to_json()
                    label = translate_category_label(res.get("label_tr") or kat)[:24]
                    safe = re.sub(r"[^A-Za-z0-9_-]", "_", label)
                    st.download_button(
                        f"⬇️ {label}",
                        data=gj,
                        file_name=f"{district}_{safe}.geojson",
                        mime="application/geo+json",
                        width="stretch",
                        key=f"gj_{kat}",
                    )
                    offered += 1
            if offered == 0:
                st.caption("No geometric data available in current results.")

    # ── Neighborhood pivot tab ──────────────────────────────────────────────
    with tab_pivot:
        if "Neighborhood" in all_df_en.columns and "Category" in all_df_en.columns:
            pivot = (
                all_df_en.groupby(["Neighborhood", "Category"])
                .size().unstack(fill_value=0)
            )
            pivot["TOTAL"] = pivot.sum(axis=1)
            pivot = pivot.sort_values("TOTAL", ascending=False)
            st.dataframe(pivot, width="stretch", height=500)
            st.caption(f"{len(pivot)} neighborhoods · {len(pivot.columns) - 1} categories")
        else:
            cards.empty_state(
                "No neighborhood-level pivot available",
                "The current dataset doesn't contain both neighborhood and category columns.",
                icon="📭",
            )

else:
    # ── No data yet ─────────────────────────────────────────────────────────
    cards.divider()
    cards.empty_state(
        title="No extraction yet",
        text="Configure your selection in the sidebar and press "
             "\"Run Extraction\" to start. Results will appear here and on the "
             "Map & Analytics pages.",
        icon="🚀",
    )


cards.footer()
