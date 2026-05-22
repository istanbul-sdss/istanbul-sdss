"""
optimizer_steps/step1_data.py — Step 1: Data loading.

Sprint 2 #8 (phase 3): 585-line Step 1 block (file uploaders + format
selection + population method + KPI summary + neighborhood breakdown
table) extracted from Optimization_Tool.py into a standalone
`render_step1_data()` function.

Step 1 has two halves:
  • Pre-load UI: file uploaders, population method selector, Load button.
    All side effects go through session_state.
  • Post-load summary: KPI cards + uniform-method audit table +
    non-residential warning + estimated-area warning. Runs only when
    `st.session_state.opt_buildings` is populated.

Both halves render in one function call. Behaviour byte-for-byte
identical to the inline version.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from components import cards
from components.domain_config import DomainConfig
from components.translations import to_english
from src.config.settings import CACHE_DIR
from src.logger import get_logger
from src.optimizer.data_loader import (
    POP_METHOD_AUTO,
    POP_METHOD_FOOTPRINT,
    POP_METHOD_UNIFORM,
    list_excel_sheets,
    load_from_excel,
    load_from_geojson,
)
from src.optimizer.templates import (
    build_data_template_xlsx,
    build_tuik_template_xlsx,
)

log = get_logger(__name__)


def _have(key: str) -> bool:
    return st.session_state.get(key) is not None


def render_step1_data(domain: DomainConfig) -> None:
    """
    Step 1 — Data: file uploaders + format selection + population method
    + Load button + (after load) KPI summary + neighborhood breakdown.
    Reads/writes via st.session_state.
    """
    cards.section_title(
        "1 · Load data",
        "Upload buildings and assembly areas — either the Excel output of the "
        "data-extraction tool, or two GeoJSON files.",
    )

    with st.container(border=True):
        # ── Template indirme butonları ───────────────────────────────────────
        # Bağımsız kullanıcılar (veri çekme aracını kullanmayanlar) için doğru
        # kolon yapısını gösteren styled Excel şablonları. Her ikisi de
        # build_styled_workbook ile aynı brand-renkli header + autofilter +
        # freeze pane stil katmanından geçer ("pivot-table benzeri" görünüm).
        with st.expander("📥 Need a template? Download blank Excel"):
            dl_c1, dl_c2 = st.columns(2)
            with dl_c1:
                st.download_button(
                    "⬇️ Buildings + Assembly Excel template",
                    data=build_data_template_xlsx(),
                    file_name="istanbul_sdss_data_template.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
                    key="opt_dl_data_template",
                    help=(
                        "Three sheets (Buildings + Assembly + README), 1 example "
                        "row + field descriptions. Coloured header + autofilter."
                    ),
                )
            with dl_c2:
                st.download_button(
                    "⬇️ TÜİK population Excel template",
                    data=build_tuik_template_xlsx(),
                    file_name="istanbul_sdss_tuik_template.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
                    key="opt_dl_tuik_template",
                    help=(
                        "For Uniform per-building mode: Excel with mahalle_adi + "
                        "nufus columns. 5 example Kadıköy neighborhoods; update "
                        "for your own district."
                    ),
                )
        # ─────────────────────────────────────────────────────────────────────

        # Upload temp dosyalarını session başına benzersizleştir (paylaşımlı
        # Streamlit dağıtımında dosya çakışması olmasın). Kimlik üst tarafta
        # st.session_state["_session_id"] olarak UUID ile üretildi.
        _session_id = st.session_state["_session_id"]

        # ═══════════════════════════════════════════════════════════════════
        # 📊 DEMAND WEIGHT — Domain-aware
        # Earthquake + Custom presets both expose the full population-method
        # radio (Auto / Footprint / Uniform) + TÜİK upload. Section header
        # changes per preset (e.g. "Population data" vs "Demand weights").
        # ═══════════════════════════════════════════════════════════════════
        _weight_section_title = domain.step1_weight_section_title
        st.markdown(
            '<div style="background:#EFF6FF;border-left:4px solid #2563EB;'
            'padding:8px 12px;margin:8px 0 4px 0;border-radius:4px;'
            'font-weight:600;color:#1E40AF;font-size:0.95rem">'
            f'📊 {_weight_section_title}'
            '</div>',
            unsafe_allow_html=True,
        )
        if domain.show_population_methods:
            pop_method_label = st.radio(
                "Method",
                [
                    "🤖 Auto (recommended)",
                    "📐 Footprint-based (footprint × levels × 0.025)",
                    "👥 Uniform per-building (TÜİK / building count)",
                ],
                index=0,
                horizontal=False,
                key="opt_pop_method",
                label_visibility="collapsed",
                help=(
                    "**Auto:** Uses footprint-based if your data has a footprint "
                    "column; otherwise uniform per-building.\n\n"
                    "**Footprint-based:** Building population ≈ footprint × levels "
                    "× 0.025 (TÜİK 2023 coefficient). Footprint and levels columns "
                    "are required.\n\n"
                    "**Uniform per-building:** Building population = neighborhood "
                    "population / number of buildings in the neighborhood. No "
                    "footprint needed; a TÜİK neighborhood population file is required."
                ),
            )
            if pop_method_label.startswith("📐"):
                pop_method_choice = POP_METHOD_FOOTPRINT
            elif pop_method_label.startswith("👥"):
                pop_method_choice = POP_METHOD_UNIFORM
            else:
                pop_method_choice = POP_METHOD_AUTO
        else:
            # Non-earthquake domain: footprint formülü ve TÜİK upload meaningful
            # değil. Auto seçili kabul edip kullanıcının veri tablosunda doğrudan
            # weight kolonu olmasını bekliyoruz.
            st.info(
                f"**{domain.display_name}** mode: the loader will read the "
                f"`{domain.weight_concept}` column directly from your data file "
                f"(or fall back to footprint estimate if available). The earthquake-"
                f"specific TÜİK/Uniform method is disabled in this mode — switch "
                f"back to Earthquake to enable it."
            )
            pop_method_choice = POP_METHOD_AUTO

        # Uniform mode TÜİK dosyası şart; bu dosyayı yine load anına kadar tut.
        pop_csv_df: pd.DataFrame | None = None
        pop_name_col_pick = "mahalle_adi"
        pop_value_col_pick = "nufus"
        needs_tuik = pop_method_choice == POP_METHOD_UNIFORM
        if needs_tuik:
            st.info(
                "ℹ Uniform per-building method selected — upload a TÜİK "
                "neighborhood population file (CSV or Excel)."
            )
            tuik_file = st.file_uploader(
                "TÜİK neighborhood population file (CSV/Excel)",
                type=["csv", "xlsx", "xls"],
                key="opt_tuik_for_uniform",
            )
            if tuik_file is not None:
                try:
                    if tuik_file.name.lower().endswith(".csv"):
                        pop_csv_df = pd.read_csv(tuik_file)
                    else:
                        pop_csv_df = pd.read_excel(tuik_file)
                    from src.optimizer.population_estimator import (
                        detect_population_columns,
                    )
                    _ndef, _pdef = detect_population_columns(pop_csv_df)
                    cols = list(pop_csv_df.columns)
                    cc1, cc2 = st.columns(2)
                    with cc1:
                        pop_name_col_pick = st.selectbox(
                            "Neighborhood name column",
                            options=cols,
                            index=(cols.index(_ndef) if _ndef in cols else 0),
                            key="opt_tuik_name_col",
                        )
                    with cc2:
                        _pidx = cols.index(_pdef) if _pdef in cols else (1 if len(cols) > 1 else 0)
                        pop_value_col_pick = st.selectbox(
                            "Population column",
                            options=cols,
                            index=_pidx,
                            key="opt_tuik_pop_col",
                        )
                    st.dataframe(pop_csv_df.head(), width="stretch", hide_index=True)
                except Exception as e:
                    st.error(f"Could not read TÜİK file: {type(e).__name__}: {e}")
                    pop_csv_df = None

        # Load butonlarına forward edilecek kwargs paketi.
        # population_method == AUTO ise load_* fonksiyonları kendi içinde
        # detect edip karar verir; ihtimal uniform'a düştüğünde mahalle_pop
        # yoksa ValueError döner — UI bunu yakalar.
        _load_kwargs = dict(
            population_method=pop_method_choice,
            mahalle_pop=pop_csv_df,
            pop_name_col=pop_name_col_pick,
            pop_value_col=pop_value_col_pick,
        )

        # ═══════════════════════════════════════════════════════════════════
        # 🏢 DEMAND POINTS & FACILITIES — Veri dosyası seçimi + yükleme
        # ═══════════════════════════════════════════════════════════════════
        import html as _h
        _data_section_title = _h.escape(domain.step1_data_section_title)
        st.markdown(
            '<div style="background:#F0FDF4;border-left:4px solid #16A34A;'
            'padding:8px 12px;margin:16px 0 4px 0;border-radius:4px;'
            'font-weight:600;color:#166534;font-size:0.95rem">'
            f'🏢 {_data_section_title}'
            '</div>',
            unsafe_allow_html=True,
        )
        source = st.radio(
            "Data source",
            ["Excel (from Data Extraction tool)", "GeoJSON (two files)"],
            horizontal=True,
            key="opt_source_radio",
        )

        if source.startswith("Excel"):
            excel_file = st.file_uploader(
                "Excel workbook (.xlsx)",
                type=["xlsx"],
                key="opt_up_excel",
            )
            if excel_file:
                tmp_path = CACHE_DIR / f"upload_{_session_id}.xlsx"
                tmp_path.write_bytes(excel_file.read())

                try:
                    sheets = list_excel_sheets(tmp_path)
                    col1, col2 = st.columns(2)
                    with col1:
                        bina_sheet = st.selectbox(
                            "Buildings sheet", sheets, key="opt_bina_sheet"
                        )
                    with col2:
                        top_sheet = st.selectbox(
                            "Assembly areas sheet", sheets, key="opt_top_sheet"
                        )

                    if st.button("✅ Load", key="opt_btn_load_xlsx", type="primary"):
                        try:
                            with st.spinner("Loading data…"):
                                b, t = load_from_excel(
                                    tmp_path, bina_sheet, top_sheet, **_load_kwargs
                                )
                            st.session_state.opt_buildings = b
                            st.session_state.opt_assembly  = t
                            st.session_state.opt_od_matrix = None
                            st.session_state.opt_result    = None
                            tmp_path.unlink(missing_ok=True)
                            method_used = b.attrs.get("population_method", "?")
                            st.success(
                                f"✅ Loaded {len(b):,} buildings · {len(t):,} assembly "
                                f"areas · population method: **{method_used}**"
                            )
                            st.rerun()
                        except ValueError as ve:
                            st.error(f"⚠ {ve}")
                        except Exception as e:
                            st.error(f"Load error: {type(e).__name__}: {e}")
                except Exception as e:
                    st.error(f"Load error: {e}")

        else:  # GeoJSON
            col1, col2 = st.columns(2)
            with col1:
                bina_file = st.file_uploader(
                    "Buildings GeoJSON",
                    type=["geojson", "json"],
                    key="opt_up_bina",
                )
            with col2:
                top_file = st.file_uploader(
                    "Assembly areas GeoJSON",
                    type=["geojson", "json"],
                    key="opt_up_top",
                )

            if bina_file and top_file:
                b_path = CACHE_DIR / f"upload_bina_{_session_id}.geojson"
                t_path = CACHE_DIR / f"upload_top_{_session_id}.geojson"
                b_path.write_bytes(bina_file.read())
                t_path.write_bytes(top_file.read())

                if st.button("✅ Load", key="opt_btn_load_gj", type="primary"):
                    with st.spinner("Loading data…"):
                        try:
                            b, t = load_from_geojson(b_path, t_path, **_load_kwargs)
                            st.session_state.opt_buildings = b
                            st.session_state.opt_assembly  = t
                            st.session_state.opt_od_matrix = None
                            st.session_state.opt_result    = None
                            b_path.unlink(missing_ok=True)
                            t_path.unlink(missing_ok=True)
                            method_used = b.attrs.get("population_method", "?")
                            st.success(
                                f"✅ Loaded {len(b):,} buildings · {len(t):,} assembly "
                                f"areas · population method: **{method_used}**"
                            )
                            st.rerun()
                        except ValueError as ve:
                            st.error(f"⚠ {ve}")
                        except Exception as e:
                            st.error(f"Load error: {type(e).__name__}: {e}")

    # Loaded-data summary
    if _have("opt_buildings"):
        b = st.session_state.opt_buildings
        t = st.session_state.opt_assembly

        k1, k2, k3, k4 = st.columns(4, gap="small")
        with k1:
            cards.kpi_card(domain.demand_label, len(b))
        with k2:
            cards.kpi_card(domain.facility_label, len(t))
        with k3:
            try:
                if len(b) and "weight" in b.columns and b["weight"].notna().any():
                    avg_w = float(b["weight"].mean(skipna=True))
                else:
                    avg_w = 0.0
            except Exception:
                avg_w = 0.0
            cards.kpi_card(domain.weight_label, f"{avg_w:.0f}")
        with k4:
            method_used = b.attrs.get("population_method", "?")
            method_short = {
                "footprint_based": "Footprint",
                "uniform_per_building": "Uniform",
            }.get(method_used, method_used)
            # Earthquake/Custom dışı domain'lerde "Population method" yerine
            # daha generic bir başlık.
            _method_card_title = (
                "Population method"
                if domain.show_population_methods
                else "Weight source"
            )
            cards.kpi_card(_method_card_title, method_short)

        # Uniform mode'da TÜİK'te bulunamayan mahalle binaları yükleme
        # sırasında zaten düşürüldü (attrs.dropped_missing_weight*). Kullanıcıya
        # şeffaf olarak bildir — kaç satır neden düştü ve nasıl düzeltebilir.
        n_dropped = int(b.attrs.get("dropped_missing_weight_count", 0))
        if n_dropped > 0:
            dropped_df = b.attrs.get("dropped_missing_weight")
            sample_mahalleler = ""
            if dropped_df is not None and len(dropped_df):
                uniq = dropped_df["mahalle"].dropna().unique().tolist()
                sample_mahalleler = ", ".join(map(str, uniq[:5])) + (
                    f" (+{len(uniq)-5} more)" if len(uniq) > 5 else ""
                )
            st.warning(
                f"⚠️ **{n_dropped:,} buildings dropped from the optimization "
                f"because their neighborhood is missing from the TÜİK file.** "
                f"Missing neighborhoods: {sample_mahalleler}. "
                f"Add the missing rows to the TÜİK file and re-upload."
            )

        # Uniform mode audit: mahalle bazlı dağıtımı şeffaf göster — hocaların
        # "mahalle nüfusu / o mahalledeki bina sayısı" istediğinin canlı kanıtı.
        uniform_audit = b.attrs.get("uniform_audit")
        if uniform_audit is not None and len(uniform_audit) > 0:
            with st.expander(
                f"👥 Population breakdown by neighborhood "
                f"({len(uniform_audit)} mahalle, uniform per-building)",
                expanded=False,
            ):
                st.caption(
                    "Each row is one neighborhood. "
                    "**bina_basi = tuik_nufus / bina_sayisi** — every building "
                    "in that neighborhood gets the same weight. Different "
                    "bina_basi values across neighborhoods are evidence that "
                    "per-neighborhood distribution is used, not a single "
                    "district-wide average."
                )
                # Sıralama: bina_basi azalan (en yoğun ilk)
                audit_sorted = uniform_audit.sort_values(
                    "bina_basi", ascending=False, na_position="last"
                ).reset_index(drop=True)
                st.dataframe(
                    audit_sorted,
                    width="stretch",
                    hide_index=True,
                    height=min(420, 38 * (len(audit_sorted) + 1)),
                )
                # Hızlı özet metrikleri
                valid = audit_sorted.dropna(subset=["bina_basi"])
                if len(valid) > 0:
                    bp_min = float(valid["bina_basi"].min())
                    bp_max = float(valid["bina_basi"].max())
                    bp_mean = float(valid["bina_basi"].mean())
                    st.caption(
                        f"📊 Population per building range: "
                        f"**{bp_min:.1f} – {bp_max:.1f}** (mean {bp_mean:.1f}). "
                        f"This spread shows that each neighborhood's own "
                        f"population density is preserved."
                    )

        # P2.6: konut-dışı bina varsayım uyarısı.
        # population_estimator hanehalkı × daire alanı bazlı çalışır; ticari /
        # endüstriyel / okul / depo gibi binalar için sistematik fazla tahmin
        # üretir ve toplam talebi şişirir. Karar destek raporlarının yanlış
        # yorumlanmasını önlemek için kullanıcıya görünür hale getiriyoruz.
        #
        # Sprint 2 #11: warning artık opsiyonel bir acknowledgement checkbox'ı
        # ile birlikte. %5'in üzerinde non-residential bina varsa kullanıcı
        # CHECKBOX'I işaretlemeden Step 3'e devam edemez. Düşük orana sahip
        # senaryolarda sadece bilgi notu olarak kalır.
        n_nr = int(b.attrs.get("non_residential_count", 0))
        pct_nr = (n_nr / len(b) * 100) if (n_nr and len(b)) else 0.0
        st.session_state["opt_non_residential_pct"] = pct_nr
        # %5 eşik — altında sistematik etki ihmal edilebilir (statistical noise);
        # üstünde karar destek raporu yanlış yorumlanır → blok zorunlu.
        nr_block_threshold_pct = 5.0
        requires_ack = n_nr > 0 and pct_nr >= nr_block_threshold_pct

        if n_nr > 0:
            st.warning(
                f"⚠️ **Non-residential building assumption warning:** {n_nr:,}/{len(b):,} "
                f"({pct_nr:.0f}%) buildings are NON-residential (commercial, office, "
                f"school, warehouse, civic, place of worship, etc.). The population "
                f"estimate is based on TÜİK household × dwelling-area assumptions; "
                f"non-residential buildings are **systematically over-estimated** → "
                f"total demand inflates, coverage / capacity KPIs may be misleading.\n\n"
                f"**Recommendation:** In the Data Extraction tool, regenerate the "
                f"buildings sheet selecting only residential subcategories "
                f"(`Residential`, `Apartments`, `House`, `Detached House`, `Terrace`, "
                f"`Unspecified Building (yes)`)."
            )

        if requires_ack:
            # Eşiği aşan dataset: kullanıcı bilinçli kabul etmeden ilerleme yok.
            # session_state'e flag yazıyoruz; Step 3 "Run optimization" butonu
            # bunu okuyarak disabled olur.
            ack_ok = st.checkbox(
                (
                    f"☑ I acknowledge the **{pct_nr:.0f}%** non-residential mix and "
                    f"accept that demand estimates will be inflated. Reports must "
                    f"label this dataset as 'mixed-use' rather than 'residential'."
                ),
                value=False,
                key="opt_nr_acknowledged",
                help=(
                    "When non-residential ratio is ≥5%, the population estimator "
                    "produces a systematically inflated demand. By checking this "
                    "box you confirm that you understand the limitation and your "
                    "downstream report will reflect this caveat."
                ),
            )
            st.session_state["opt_non_residential_acknowledged"] = bool(ack_ok)
            if not ack_ok:
                st.info(
                    "ℹ Optimization is **paused** until the acknowledgement above "
                    "is checked. This guard protects academic reports from silent "
                    "demand inflation in mixed-use datasets."
                )
        else:
            # Eşik altında: ack zorunlu değil, default True yazıyoruz ki Step 3
            # bloğu engellenmesin.
            st.session_state["opt_non_residential_acknowledged"] = True

        # ── Estimated capacity warning (area_source='estimated' assembly areas) ──
        if "area_source" in t.columns:
            n_est = int((t["area_source"] == "estimated").sum())
            if n_est > 0:
                pct = n_est / len(t) * 100 if len(t) else 0.0
                st.warning(
                    f"⚠️ **Estimated capacity warning:** {n_est}/{len(t)} "
                    f"({pct:.0f}%) assembly areas have no m² information in OSM "
                    f"(or it came in as 0). A **1000 m² fallback** was applied and "
                    f"capacity was derived using the AFAD standard (1.5 m²/person). "
                    f"For decision-support use, downloading the real polygon areas "
                    f"is recommended. See the **`area_source`** column in the table "
                    f"below for per-row provenance."
                )

        with st.expander("Preview: first 5 buildings"):
            prev = b.drop(columns="geometry", errors="ignore").head()
            st.dataframe(to_english(prev), width="stretch", hide_index=True)
        with st.expander("Preview: assembly areas"):
            prev = t.drop(columns="geometry", errors="ignore")
            st.dataframe(to_english(prev), width="stretch", hide_index=True)

        # ── Mahalle bazlı nüfus override (TÜİK kalibrasyonu) ─────────────────────
        # Bina başına nüfus tahmini footprint × kat × katsayı ile yapılır;
        # bu sistematik bias taşır (DEFAULT_LEVELS, konut/ticari ayrımı yok).
        # Kullanıcı TÜİK mahalle nüfus tablosunu yüklerse, footprint dağılımı
        # *anahtar* olarak korunur ama mahalle TOPLAMI TÜİK'e ölçeklenir.
        with st.expander("👥 Population override — TÜİK neighborhood calibration (optional)"):
            st.markdown(
                "**Why?** Footprint × floors × 0.025 estimates carry systematic "
                "bias. If you upload TÜİK neighborhood populations, the "
                "intra-neighborhood distribution key is preserved but the total "
                "population per neighborhood is calibrated to the TÜİK figure — "
                "recommended for defensible decision support.\n\n"
                "**Expected format:** CSV/Excel with one **name** column and one "
                "**population** column. Common header names "
                "(`mahalle_adi`, `mahalle`, `Neighborhood`, `name`, "
                "`nufus`, `nüfus`, `population`, ...) are auto-detected; "
                "you can override below if needed. Typographic differences "
                "(e.g. `Zühütpaşa` vs `Zühtüpaşa`, `CAFERAGA MAH.` vs "
                "`Caferağa Mahallesi`) are handled by a fuzzy fallback."
            )
            pop_file = st.file_uploader(
                "TÜİK neighborhood population file (CSV/Excel)",
                type=["csv", "xlsx", "xls"],
                key="opt_pop_override_file",
            )
            if pop_file is not None:
                try:
                    if pop_file.name.lower().endswith(".csv"):
                        mahalle_pop_df = pd.read_csv(pop_file)
                    else:
                        mahalle_pop_df = pd.read_excel(pop_file)
                    st.dataframe(mahalle_pop_df.head(), hide_index=True, width="stretch")

                    # Auto-detect kolon eşleştirmesi + kullanıcının override
                    # imkânı. Auto-detect rapid önerge sunar; kullanıcı yanlış
                    # tahmini selectbox'tan düzeltir.
                    from src.optimizer.population_estimator import (
                        apply_neighbourhood_population_override,
                        detect_population_columns,
                    )
                    _name_default, _pop_default = detect_population_columns(mahalle_pop_df)
                    cols = list(mahalle_pop_df.columns)
                    cc1, cc2 = st.columns(2)
                    with cc1:
                        name_col_pick = st.selectbox(
                            "Neighborhood name column",
                            options=cols,
                            index=(cols.index(_name_default) if _name_default in cols else 0),
                            key="opt_pop_name_col",
                            help="Auto-detected from header; override here if wrong.",
                        )
                    with cc2:
                        # pop kolonu varsayılanı name kolonu DEĞİL olmalı
                        _pop_idx = cols.index(_pop_default) if _pop_default in cols else (
                            1 if len(cols) > 1 else 0
                        )
                        pop_col_pick = st.selectbox(
                            "Population column",
                            options=cols,
                            index=_pop_idx,
                            key="opt_pop_value_col",
                            help="Auto-detected from header; override if wrong.",
                        )
                    if name_col_pick == pop_col_pick:
                        st.warning(
                            "⚠ Name and population columns are the same — pick "
                            "two different columns."
                        )

                    fuzzy_thr = st.slider(
                        "Fuzzy match threshold",
                        min_value=70, max_value=100, value=85, step=5,
                        key="opt_pop_fuzzy_thr",
                        help=(
                            "Below 85: more names matched but higher false-positive "
                            "risk. Above 90: stricter, may miss legitimate "
                            "transliteration variants. 85 is the calibrated default."
                        ),
                    )

                    disabled = (name_col_pick == pop_col_pick)
                    if st.button(
                        "📐 Apply calibration",
                        key="opt_apply_pop_override",
                        disabled=disabled,
                    ):
                        try:
                            cal_b, audit = apply_neighbourhood_population_override(
                                st.session_state.opt_buildings,
                                mahalle_pop_df,
                                name_col=name_col_pick,
                                pop_col=pop_col_pick,
                                fuzzy_threshold=float(fuzzy_thr),
                            )
                            st.session_state.opt_buildings = cal_b
                            # OD ve sonuç eski ağırlıklarla hesaplandıysa geçersizleşir
                            st.session_state.opt_od_matrix = None
                            st.session_state.opt_result = None
                            st.session_state.opt_pop_audit = audit

                            # Calibrated sayımı: 'durum' fuzzy variant da içerir
                            n_cal = int(
                                audit["durum"].astype(str).str.startswith("Kalibre edildi").sum()
                            )
                            n_fuzzy = int(
                                audit["eslesme"].astype(str).str.startswith("fuzzy").sum()
                            ) if "eslesme" in audit.columns else 0
                            n_total = len(audit)
                            msg = (
                                f"✅ {n_cal}/{n_total} neighborhoods calibrated to TÜİK. "
                                f"OD matrix and results were reset; please re-run."
                            )
                            if n_fuzzy:
                                msg += (
                                    f" ({n_fuzzy} matched via fuzzy fallback — "
                                    f"see audit table below.)"
                                )
                            st.success(msg)
                        except ValueError as e:
                            st.error(f"Format error: {e}")
                        except Exception as e:
                            st.error(f"Unexpected error: {type(e).__name__}: {e}")
                except Exception as e:
                    st.error(f"Could not read file: {type(e).__name__}: {e}")

            # Önceden uygulanmış kalibrasyon raporu varsa göster
            if "opt_pop_audit" in st.session_state and st.session_state.opt_pop_audit is not None:
                st.markdown("**Calibration audit:**")
                st.dataframe(
                    st.session_state.opt_pop_audit,
                    hide_index=True, width="stretch",
                )


