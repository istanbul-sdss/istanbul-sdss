"""
Optimization_Tool.py — Assignment Optimization (English UI)

Professional, step-based Streamlit app for generic P-Median facility-location
optimization. Pre-configured for earthquake assembly area planning but the
underlying math (Hakimi 1964) handles any "assign demand points to a chosen
number of facilities" problem — schools, clinics, depots, service centers.

Workflow:
  1. Data      — upload buildings (demand) + assembly areas (facilities)
                 from Excel or GeoJSON
  2. OD Matrix — build a walking or driving OD matrix via OSMnx
  3. Optimize  — solve P-Median (ILP or K-Medoids) with optional capacity
  4. Results   — KPIs, coverage chart, assignments, map, exports

Generic-use note (for non-earthquake contexts):
  • "Buildings" → swap in any demand points (population centers, customer
    locations). Weight column = demand magnitude.
  • "Assembly areas" → swap in any facilities (schools, hospitals, depots).
    area_m² + density slider together define capacity.
  • Driving mode + arbitrary speed slider supports non-walk contexts.

Transport mode (Step 2): Walking is the AFAD default for emergency assembly
planning; Driving is offered for comparative analysis.

Run:
    streamlit run Optimization_Tool.py
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from components import cards
from components.domain_config import DEFAULT_DOMAIN_KEY, DOMAINS, get_domain
from components.styles import TOKENS, configure_page
from components.translations import to_english
from src.config.settings import CACHE_DIR, ISTANBUL_ILCELER
from src.logger import get_logger
from src.optimizer.data_loader import (
    POP_METHOD_AUTO,
    POP_METHOD_FOOTPRINT,
    POP_METHOD_UNIFORM,
    list_excel_sheets,
    load_from_excel,
    load_from_geojson,
)
from src.optimizer.map_renderer import render_atama_haritasi
from src.optimizer.od_matrix import (
    DEFAULT_SPEED_KPH,
    MODE_DRIVE,
    MODE_WALK,
    compute_od_matrix,
    compute_od_matrix_haversine,
    get_graph,
    validate_graph,
)
from src.optimizer.p_median import PMedianResult, coz, duyarlilik_analizi
from src.optimizer.population_estimator import assumptions_table
from src.optimizer.templates import (
    build_data_template_xlsx,
    build_tuik_template_xlsx,
)

log = get_logger("optimizer_app")


# ════════════════════════════════════════════════════════════════════════════
# STREAMLIT CACHE WRAPPERS
# ════════════════════════════════════════════════════════════════════════════
# Streamlit her UI etkileşiminde betiği baştan çalıştırır. Yürüme grafı diskten
# ~1-2s sürer, OD matrisi büyük ilçelerde 5-15dk. Bu wrapper'lar tekrar tekrar
# yüklemeyi/hesaplamayı önler — kütüphane modülleri (src/optimizer/*) Streamlit'e
# bağımlı kalmasın diye burada tutuluyor.

@st.cache_resource(show_spinner=False)
def _cached_graph(ilce: str, mode: str = MODE_WALK, force_download: bool = False):
    """
    @st.cache_resource: NetworkX grafı tekil ve büyük (paylaşılan kaynak).
    Aynı (ilçe, mode) için yalnızca bir kez yüklenir, rerun'larda bellekten
    döner. Walking ve driving cache'leri AYRI tutulur — biri diğerini
    invalidate etmez.

    `force_download=True` cache'i bypass eder ve yeniden indirir.
    """
    return get_graph(ilce, mode=mode, force_download=force_download)

# NOTE: An earlier `_cached_od_haversine` wrapper used to live here. It was
# never actually called — the haversine fallback path computes the OD matrix
# inline and stores the result in `st.session_state.opt_od_matrix`, which
# already provides cross-rerun reuse without paying the cost of hashing
# large coordinate tuples on every cache lookup. Removed to avoid the
# misleading dead code (audit follow-up).


# ════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ════════════════════════════════════════════════════════════════════════════
configure_page(title="Assembly Area Optimization", icon="⭐")

# P2-02 düzeltmesi: Optimizer ayrı bir Streamlit app olarak çalıştırıldığında
# (run_optimizer.bat / streamlit run Optimization_Tool.py) ana projede
# `pages/` klasörü olduğu için Streamlit native nav otomatik olarak Data
# Extraction / Map / Analytics / vb. sayfaları listeliyor. Bu, optimizer'ın
# bağımsız bir araç olduğu kullanıcı algısını bozuyor (UI review bulgusu).
#
# Çözüm: native sidebar nav'ı yalnızca **bu uygulama için** CSS ile gizle.
# Ana app (`streamlit run Spatial_Data_Collection_Tool.py`) etkilenmez.
st.markdown(
    """
    <style>
      /* Streamlit'in otomatik pages/ listesini gizle — Optimizer
         bağımsız bir araç olarak konumlanır. */
      [data-testid="stSidebarNav"] { display: none !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ════════════════════════════════════════════════════════════════════════════
_DEFAULTS = {
    "opt_buildings":   None,    # GeoDataFrame of buildings
    "opt_assembly":    None,    # GeoDataFrame of assembly areas
    "opt_od_matrix":   None,    # numpy array (np.inf for unreachable)
    "opt_result":      None,    # PMedianResult
    "opt_district":    "",      # district used for OSMnx graph
    "opt_logs":        [],      # list[str]
    # Cutoff politikası kaldırıldı: tüm bina-alan çiftleri admissible.
    # Bu alan artık kullanılmıyor (always None); backward-compat ve audit
    # için saklanıyor — Excel meta sheet "Cutoff" satırını okur.
    "opt_max_minutes": None,
    "opt_graph_info":  None,    # dict from validate_graph
    "opt_pop_audit":   None,    # nüfus override audit DataFrame
    "opt_od_mode":     None,    # "street_network" | "haversine_fallback"
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Upload temp dosyalarının çakışmaması için session-başına benzersiz kimlik.
# Why: Streamlit private API (st.runtime.scriptrunner.get_script_run_ctx) minor
# sürümlerde değişebilir ve yoksa "local" string'ine düşüp paylaşımlı senaryoda
# tekrar çakışma yaratır. UUID kütüphane garantili ve self-contained.
if "_session_id" not in st.session_state:
    st.session_state["_session_id"] = uuid.uuid4().hex[:8]


def log_cb(msg: str) -> None:
    """Progress callback: push to logger + session logs."""
    log.info(msg)
    st.session_state.opt_logs.append(msg)


def _have(key: str) -> bool:
    return st.session_state.get(key) is not None


# ════════════════════════════════════════════════════════════════════════════
# CURRENT STEP (for stepper)
# ════════════════════════════════════════════════════════════════════════════
if _have("opt_result"):
    current_step = 3                # Results
elif _have("opt_od_matrix"):
    current_step = 2                # Optimize
elif _have("opt_buildings"):
    current_step = 1                # OD Matrix
else:
    current_step = 0                # Data


# ════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════════════════════
cards.sidebar_brand()

# Domain selector — UI'ın ne hakkında olduğunu söyleyen kök ayar. Etiket
# sözlüğü components/domain_config.py'da. Earthquake default, değiştirilince
# tüm KPI/section/help string'leri yeniden render olur. Math katmanı
# (p_median, od_matrix) dokunulmaz — sadece görsel uyarlama.
st.sidebar.markdown("### Use case")
_domain_options = list(DOMAINS.keys())
_domain_labels = {k: f"{DOMAINS[k].icon} {DOMAINS[k].display_name}" for k in _domain_options}
_active_domain_key = st.sidebar.selectbox(
    "Scenario",
    options=_domain_options,
    format_func=lambda k: _domain_labels[k],
    index=_domain_options.index(
        st.session_state.get("opt_domain", DEFAULT_DOMAIN_KEY)
    ),
    key="opt_domain",
    help=(
        "Earthquake is the primary configuration and the methodology "
        "is fully documented for it. The Custom preset switches the UI "
        "vocabulary to generic facility-location terms so the same "
        "p-Median engine can be applied to other use cases. "
        "Data preparation (weights, capacities) is the user's "
        "responsibility for non-earthquake domains."
    ),
)
domain = get_domain(_active_domain_key)
# Non-earthquake domain'lerde scope sınırını şeffaf belirt
if _active_domain_key != "earthquake":
    st.sidebar.info(
        f"**{domain.display_name}** mode: solver is identical, but "
        f"weights and capacities must come from your own data preparation. "
        f"Switching back to Earthquake re-enables AFAD-specific helpers."
    )

st.sidebar.markdown("### Workflow")
st.sidebar.markdown(
    f"""
    <div style="font-size:0.875rem;color:#CBD5E1;line-height:1.9">
      {"✅" if current_step >= 1 else "⬜"} &nbsp; 1 · Load data<br>
      {"✅" if current_step >= 2 else "⬜"} &nbsp; 2 · OD matrix<br>
      {"✅" if current_step >= 3 else "⬜"} &nbsp; 3 · Optimize<br>
      {"✅" if current_step >= 4 else "⬜"} &nbsp; 4 · Review results
    </div>
    """,
    unsafe_allow_html=True,
)

st.sidebar.markdown("---")

if _have("opt_buildings"):
    b = st.session_state.opt_buildings
    t = st.session_state.opt_assembly
    st.sidebar.markdown("### Loaded data")
    # P2-01 escape düzeltmesi: `opt_district` kullanıcı serbest girdisi
    # olabilir (custom district), HTML render'ında escape ZORUNLU. Sayısal
    # değerler güvenli ama tutarlılık için yine de format string'leri
    # numeric formatlama ile koruyoruz.
    import html as _html
    _safe_district = _html.escape(str(st.session_state.opt_district or "—"))
    st.sidebar.markdown(
        f"""
        <div style="font-size:0.875rem;color:#CBD5E1;line-height:1.8">
          • <b>{len(b):,}</b> buildings<br>
          • <b>{len(t):,}</b> assembly areas<br>
          • District: <b>{_safe_district}</b>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.sidebar.markdown("---")

with st.sidebar.expander("🔄 Reset session"):
    # Confirmation guard (UI review P3): Reset bütün yüklü veriyi +
    # OD matrisini + sonucu siler. Yanlışlıkla tek tıklamayla
    # tetiklenmesin diye onay checkbox + ikincil buton.
    st.caption(
        "Clears all loaded data (buildings, assembly areas, OD matrix, "
        "results) and temporary upload files."
    )
    _confirm_reset = st.checkbox(
        "I confirm I want to reset the session",
        key="opt_confirm_reset",
    )
    if st.button(
        "🗑 Reset session — confirm",
        disabled=not _confirm_reset,
        width="stretch",
        key="opt_btn_reset_confirmed",
    ):
        for k in _DEFAULTS:
            st.session_state[k] = _DEFAULTS[k]
        # Geçici yükleme dosyalarını da temizle (session'a özel)
        sid = st.session_state.get("_session_id", "")
        if sid:
            for stem in (f"upload_{sid}.xlsx",
                         f"upload_bina_{sid}.geojson",
                         f"upload_top_{sid}.geojson"):
                (CACHE_DIR / stem).unlink(missing_ok=True)
        # Confirm checkbox'ını da resetle
        st.session_state["opt_confirm_reset"] = False
        st.rerun()

# ── Cache disk panel (Sprint 2 #10) ──────────────────────────────────────────
# Operations hygiene: cache klasörü (OSM Overpass yanıtları + ilçe graph'leri
# + Streamlit output'ları) zamanla GB'lere ulaşabilir. Sidebar'a görünür bir
# boyut göstergesi + selective cleanup buton koyuyoruz ki kullanıcı
# manuel `rmdir /S` adımına ihtiyaç duymadan yönetebilsin.
with st.sidebar.expander("💾 Cache & disk"):
    import shutil as _shutil
    from pathlib import Path as _Path

    def _folder_size_bytes(folder: _Path) -> tuple[int, int]:
        """Returns (toplam_byte, dosya_sayısı). Klasör yoksa (0, 0)."""
        if not folder.exists():
            return 0, 0
        total, count = 0, 0
        for f in folder.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                    count += 1
                except OSError:
                    pass
        return total, count

    def _fmt_size(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"

    _ROOT = _Path(__file__).parent
    _CACHE_DIR_PATH = _ROOT / "cache"
    _GRAPHS_DIR = _CACHE_DIR_PATH / "graphs"
    _OVERPASS_DIR = _CACHE_DIR_PATH  # cache/ root holds JSON; graphs/ alt-klasör
    _OUTPUT_DIR = _ROOT / "output"
    _LOGS_DIR = _ROOT / "logs"

    # cache/ root içindeki *.json (Overpass) — graphs/ alt klasörü hariç
    _overpass_size = 0
    _overpass_count = 0
    if _CACHE_DIR_PATH.exists():
        for f in _CACHE_DIR_PATH.glob("*.json"):
            try:
                _overpass_size += f.stat().st_size
                _overpass_count += 1
            except OSError:
                pass
    _graphs_size, _graphs_count = _folder_size_bytes(_GRAPHS_DIR)
    _output_size, _output_count = _folder_size_bytes(_OUTPUT_DIR)
    _logs_size, _logs_count = _folder_size_bytes(_LOGS_DIR)

    st.markdown(
        f"""
        <div style="font-size:0.8125rem;color:#CBD5E1;line-height:1.7">
        • Overpass cache: <b>{_fmt_size(_overpass_size)}</b> ({_overpass_count} files)<br>
        • Graphs: <b>{_fmt_size(_graphs_size)}</b> ({_graphs_count} files)<br>
        • Output: <b>{_fmt_size(_output_size)}</b> ({_output_count} files)<br>
        • Logs: <b>{_fmt_size(_logs_size)}</b> ({_logs_count} files)
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption(
        "Cleanup removes only **reproducible** artifacts. Source code, "
        "configs, and user data are never touched."
    )
    # 3-yollu temizlik — her biri ayrı checkbox + buton (yanlışlıkla
    # tıklanmaması için confirm guard). Streamlit native rerun beklenir.
    _target = st.selectbox(
        "Target to clear",
        options=[
            "Overpass JSON cache",
            "Graph cache (OSMnx GraphML)",
            "Output (Excel/CSV exports)",
            "All reproducible caches",
        ],
        key="opt_cache_clear_target",
    )
    _confirm_clear = st.checkbox(
        "I confirm I want to delete the selected cache",
        key="opt_confirm_clear_cache",
    )
    if st.button(
        "🗑 Clear selected",
        disabled=not _confirm_clear,
        width="stretch",
        key="opt_btn_clear_cache",
    ):
        removed_bytes = 0
        removed_files = 0
        targets: list[_Path] = []
        if _target in ("Overpass JSON cache", "All reproducible caches"):
            targets.extend(_CACHE_DIR_PATH.glob("*.json"))
        if _target in ("Graph cache (OSMnx GraphML)", "All reproducible caches"):
            if _GRAPHS_DIR.exists():
                targets.extend(_GRAPHS_DIR.glob("*"))
        if _target in ("Output (Excel/CSV exports)", "All reproducible caches"):
            if _OUTPUT_DIR.exists():
                targets.extend(_OUTPUT_DIR.rglob("*"))
        for f in targets:
            if f.is_file():
                try:
                    sz = f.stat().st_size
                    f.unlink()
                    removed_bytes += sz
                    removed_files += 1
                except OSError:
                    pass
        # Empty directories left behind in output/ → temizle
        if _target in ("Output (Excel/CSV exports)", "All reproducible caches"):
            if _OUTPUT_DIR.exists():
                import contextlib as _ctx
                for d in sorted(
                    [p for p in _OUTPUT_DIR.rglob("*") if p.is_dir()],
                    key=lambda p: -len(p.parts),  # derinden yüzeye
                ):
                    with _ctx.suppress(OSError):
                        d.rmdir()
        st.session_state["opt_confirm_clear_cache"] = False
        st.success(
            f"Removed {removed_files} files ({_fmt_size(removed_bytes)})."
        )
        # `_shutil` import edildi, gelecekte tüm-klasör operasyonları için
        # kullanılabilir; şu an file-by-file ilerliyoruz çünkü size raporlama
        # için her dosyayı saymamız lazım. Linter F401 önlemek için:
        _ = _shutil

st.sidebar.markdown(
    """
    <div style="font-size:0.75rem;color:#64748B;line-height:1.5;margin-top:1rem">
    P-Median via PuLP/CBC or K-Medoids<br>
    Walk graph: OSMnx · OpenStreetMap<br>
    © OSM Contributors, ODbL
    </div>
    """,
    unsafe_allow_html=True,
)


# ════════════════════════════════════════════════════════════════════════════
# HERO
# ════════════════════════════════════════════════════════════════════════════
cards.hero(
    eyebrow=domain.hero_eyebrow,
    title="Assignment Optimization (p-Median)",
    subtitle=domain.hero_subtitle,
)

# Stepper
cards.stepper(
    ["Load data", "OD matrix", "Optimize", "Results"],
    current=current_step,
)


# ════════════════════════════════════════════════════════════════════════════
# STEP 1 — DATA LOADING
# ════════════════════════════════════════════════════════════════════════════
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


# ════════════════════════════════════════════════════════════════════════════
# STEP 2 — OD MATRIX
# ════════════════════════════════════════════════════════════════════════════
if _have("opt_buildings"):
    cards.section_title(
        "2 · Transport OD matrix",
        "Computes travel time between every building and every assembly area "
        "over the OpenStreetMap network. Choose walking (AFAD default) or "
        "driving (comparative analysis).",
    )

    with st.container(border=True):
        # District seçici: önce 39 İstanbul ilçesinden selectbox; "Other"
        # seçilirse text input açılır (akademik özgürlük: ilçe dışı bölge
        # de denenebilir). Serbest text'in tipografik hata riskini
        # (örn. "Kadıkoy" → Overpass timeout) eler.
        district_options = ["— Select —", *ISTANBUL_ILCELER, "Other (custom)"]
        # Mevcut session değerine göre default index'i hesapla
        _prev = st.session_state.opt_district or ""
        if _prev in ISTANBUL_ILCELER:
            _default_idx = district_options.index(_prev)
        elif _prev:
            _default_idx = district_options.index("Other (custom)")
        else:
            _default_idx = 0

        district_pick = st.selectbox(
            "District (for OSMnx graph download)",
            options=district_options,
            index=_default_idx,
            key="opt_district_pick",
            help=(
                "Pick one of Istanbul's 39 districts. Use 'Other (custom)' "
                "to try an area that isn't in the list."
            ),
        )

        if district_pick == "Other (custom)":
            district = st.text_input(
                "Custom district name (advanced)",
                value=_prev if _prev not in ISTANBUL_ILCELER else "",
                placeholder="e.g. Kadıköy, İstanbul, Türkiye",
                key="opt_district_inp",
                help=(
                    "Typos are on you. OSMnx geocodes via Nominatim; if the "
                    "name isn't resolvable the graph download will fail."
                ),
            )
        elif district_pick == "— Select —":
            district = ""
        else:
            district = district_pick

        # ── Transport mode (walk / drive) ─────────────────────────────────
        # Akademik tercih: AFAD acil toplanma planlaması yaya senaryosu
        # üzerine kuruludur (deprem sonrası araç pratik değildir). Driving
        # mode COMPARATIVE ANALYSIS amaçlı sunulur — politika yapıcı
        # "araç erişimi olsaydı kapsama nasıl değişirdi?" sorusunu
        # doğrulayabilir. Cutoff yok: tüm bina-alan çiftleri admissible.
        transport_label = st.radio(
            "Transport mode",
            options=[
                "🚶 Walking (AFAD default)",
                "🚗 Driving (comparative analysis)",
            ],
            horizontal=True,
            key="opt_transport_mode",
            help=(
                "**Walking:** AFAD emergency assembly standard — walking "
                "speed assumption (4.8 km/h). The official decision-support "
                "mode.\n\n"
                "**Driving:** Comparative analysis — vehicle speed (30 km/h, "
                "typical city centre). Remember that, contrary to AFAD "
                "practice, driving is not practical right after an "
                "earthquake; this mode is only for evaluating "
                "'what if vehicle access were available?' scenarios."
            ),
        )
        is_drive = transport_label.startswith("🚗")
        mode = MODE_DRIVE if is_drive else MODE_WALK
        speed_default = DEFAULT_SPEED_KPH[mode]
        speed_min, speed_max = (15.0, 60.0) if is_drive else (2.0, 8.0)
        speed_step = 1.0 if is_drive else 0.1
        speed_label = "Vehicle speed (km/h)" if is_drive else "Walking speed (km/h)"

        c1, c2 = st.columns([3, 1], gap="medium")
        with c1:
            # NOT: widget key her mode için aynı kalır (`opt_travel_speed`) →
            # mode değişince varsayılan otomatik atanır ama kullanıcı zaten
            # bir değer girdiyse Streamlit korur. Mode-aware default için
            # widget yeniden mount edilmeli — key'i mode'a göre değiştir.
            travel_speed = st.number_input(
                speed_label,
                min_value=speed_min,
                max_value=speed_max,
                value=speed_default,
                step=speed_step,
                key=f"opt_travel_speed_{mode}",
                help=(
                    "Adult walking speed. Default 4.8 km/h (AFAD / "
                    "international decision-support practice). Lower to "
                    "3.5-4.0 for neighborhoods skewed toward elderly/"
                    "children; raise to 5.5+ for younger populations."
                    if not is_drive else
                    "City-centre vehicle speed. Default 30 km/h reflects "
                    "typical traffic; 50+ on empty highways, 15-20 in heavy "
                    "congestion. Changing this does not invalidate the "
                    "graph cache."
                ),
            )
        with c2:
            force_dl = st.checkbox(
                "Force re-download graph",
                value=False,
                help=(
                    "Bypasses the cached street network. Each mode has its "
                    "OWN cache (walking ↔ driving don't affect each other)."
                ),
            )

        if is_drive:
            st.warning(
                "⚠️ **Comparative analysis mode** — AFAD emergency assembly "
                "planning assumes a walking scenario. KPIs computed in this "
                "mode are **for comparison only**; base actual assignment "
                "decisions on Walking mode."
            )
        else:
            st.caption(
                "ℹ Walking time is computed for every building–assembly area "
                "pair (no cutoff). The optimization step excludes no pairs."
            )

        if st.button(
            "🚀 Compute OD matrix",
            key="opt_btn_od",
            type="primary",
            disabled=not district.strip(),
            width="stretch",
        ):
            st.session_state.opt_district = district.strip()
            st.session_state.opt_logs = []

            # Street network — cache_resource ile rerun'larda bellekten yüklenir.
            # Mode'a göre AYRI cache (kadikoy_walk_v2 vs kadikoy_drive_v2).
            G = None
            _network_label = "driving" if is_drive else "pedestrian"
            with st.spinner(f"Preparing {_network_label} network…"):
                try:
                    G = _cached_graph(
                        st.session_state.opt_district,
                        mode=mode,
                        force_download=force_dl,
                    )
                    log_cb(
                        f"Graph ({mode}): {G.number_of_nodes():,} nodes · "
                        f"{G.number_of_edges():,} edges"
                    )
                    try:
                        gi = validate_graph(G)
                        st.session_state.opt_graph_info = gi
                        log_cb(
                            f"Graph health: {gi['connected_components']} components · "
                            f"largest covers {gi['ratio_in_largest']*100:.1f}% of nodes"
                        )
                    except Exception as e:
                        log_cb(f"Graph health check skipped: {e}")
                    st.session_state.opt_od_mode = "street_network"
                except Exception as e:
                    # Street network couldn't be loaded → offer haversine fallback
                    st.warning(
                        f"⚠ Could not load street network: {e}\n\n"
                        "Falling back to Haversine (straight-line × 1.4 detour) "
                        "OD estimation. Accuracy may drop 20-40%; this is "
                        "surfaced explicitly in the report."
                    )
                    st.session_state.opt_od_mode = "haversine_fallback"

            # OD computation
            with st.spinner("Computing OD matrix…"):
                progress = st.progress(0)
                n_top = len(st.session_state.opt_assembly)

                def od_cb(msg: str):
                    log_cb(msg)
                    if "/" in msg and "Dijkstra" in msg:
                        try:
                            num = int(msg.split("[")[1].split("/")[0])
                            progress.progress(num / n_top)
                        except Exception:
                            pass

                try:
                    # Akademik tercih: cutoff yok — tüm mesafeler hesaplanır.
                    if G is not None:
                        od = compute_od_matrix(
                            G,
                            st.session_state.opt_buildings,
                            st.session_state.opt_assembly,
                            max_dakika=float("inf"),
                            travel_speed_kph=float(travel_speed),
                            transport_mode=mode,
                            progress_cb=od_cb,
                        )
                    else:
                        # Fallback mode: haversine × detour (mode-aware speed)
                        log_cb(
                            f"Street network unavailable — Haversine fallback "
                            f"({mode}, {travel_speed:.1f} km/h)"
                        )
                        od = compute_od_matrix_haversine(
                            st.session_state.opt_buildings,
                            st.session_state.opt_assembly,
                            travel_speed_kph=float(travel_speed),
                            transport_mode=mode,
                            progress_cb=od_cb,
                        )
                    st.session_state.opt_od_matrix = od
                    # Cutoff kalktığından opt_max_minutes her zaman None
                    # → solver tarafında hard limit kısıtı uygulanmaz.
                    st.session_state.opt_max_minutes = None
                    # Compute anındaki travel mode + speed'i AYRI bir state
                    # alanında saklıyoruz (widget key'leri override edilemez,
                    # widget'lara kontrolsüz erişim sorunlu). Bu alanlar OD
                    # download, Excel meta sheet ve Results başlığı tarafından
                    # okunur.
                    st.session_state["opt_transport_mode_used"] = mode
                    st.session_state["opt_walk_speed_used"] = float(travel_speed)
                    # Stale-result banner için OD'nin hangi parametrelerle
                    # üretildiğini bir signature'da tut. Kullanıcı sonradan
                    # speed/district/mode değiştirirse banner gösterilir.
                    st.session_state["opt_od_signature"] = (
                        st.session_state.opt_district,
                        mode,
                        float(travel_speed),
                    )
                    st.session_state.opt_result    = None
                    progress.progress(1.0)
                    reachable_vals = od[np.isfinite(od)]
                    avg_min = float(reachable_vals.mean()) if reachable_vals.size else float("nan")
                    avg_txt = f"{avg_min:.1f}" if not np.isnan(avg_min) else "—"
                    fallback_txt = (
                        "" if st.session_state.get("opt_od_mode") == "street_network"
                        else " (haversine fallback)"
                    )
                    mode_emoji = "🚗" if is_drive else "🚶"
                    mode_human = "driving" if is_drive else "walking"
                    st.success(
                        f"✅ OD matrix ready — {od.shape[0]:,} × {od.shape[1]} · "
                        f"{mode_emoji} {mode_human} @ {travel_speed:.1f} km/h · "
                        f"avg reachable {avg_txt} min{fallback_txt}"
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"OD computation error: {e}")

    # OD summary
    if _have("opt_od_matrix"):
        # Stale-result banner: OD hesaplandığı andaki (district, mode, speed)
        # signature ile UI'daki güncel değerleri karşılaştır. Fark varsa
        # kullanıcı parametre değiştirmiş ama "Compute OD matrix"i tekrar
        # tetiklememiş → mevcut OD eski → uyar.
        _od_sig = st.session_state.get("opt_od_signature")
        _current_sig = (
            st.session_state.opt_district,
            mode,
            float(travel_speed),
        )
        if _od_sig is not None and _od_sig != _current_sig:
            _changed_bits = []
            # Eski signature 2-tuple olabilir (walking-only zamanları); mode
            # alanı yoksa "walk" varsayalım — geriye dönük güvenli.
            _old_district = _od_sig[0]
            _old_mode = _od_sig[1] if len(_od_sig) >= 3 else MODE_WALK
            _old_speed = _od_sig[-1]
            if _old_district != _current_sig[0]:
                _changed_bits.append(
                    f"district ({_old_district!r} → {_current_sig[0]!r})"
                )
            if _old_mode != _current_sig[1]:
                _changed_bits.append(
                    f"transport mode ({_old_mode} → {_current_sig[1]})"
                )
            if abs(_old_speed - _current_sig[2]) > 1e-6:
                _changed_bits.append(
                    f"speed ({_old_speed:.2f} → {_current_sig[2]:.2f} km/h)"
                )
            st.warning(
                "⚠ **OD matrix is stale.** Parameters changed: "
                + ", ".join(_changed_bits)
                + ". The KPIs below reflect the old computation — "
                "do not run optimization without re-running "
                "**Compute OD matrix**."
            )

        od = st.session_state.opt_od_matrix
        finite_mask = np.isfinite(od)
        reached = int(finite_mask.sum())
        total = od.size
        vals = od[finite_mask]
        avg = float(vals.mean()) if vals.size else float("nan")
        avg_txt = f"{avg:.1f}" if not np.isnan(avg) else "—"
        coverage_pct = 100.0 * reached / total if total else 0.0

        k1, k2, k3, k4 = st.columns(4, gap="small")
        with k1:
            cards.kpi_card("Avg reachable time (min)", avg_txt)
        with k2:
            cards.kpi_card("Reachable cells", f"{reached:,}")
        with k3:
            cards.kpi_card("Cell coverage", f"{coverage_pct:.1f}%")
        with k4:
            cards.kpi_card("Matrix size", f"{od.shape[0]:,} × {od.shape[1]}")

        gi = st.session_state.get("opt_graph_info")
        if gi and gi.get("connected_components", 1) > 1 and gi.get("ratio_in_largest", 1) < 0.95:
            _used_mode = st.session_state.get("opt_transport_mode_used", "walk")
            _net_human = "Driving network" if _used_mode == MODE_DRIVE else "Pedestrian network"
            st.warning(
                f"⚠ {_net_human} is fragmented — {gi['connected_components']} components, "
                f"largest covers only {gi['ratio_in_largest']*100:.1f}% of nodes. "
                f"Buildings on isolated fragments will appear in the 'unreachable' list."
            )

        # ── OD matrix indir (Madde 1.8) ──────────────────────────────────
        # Kullanıcı oluşan OD matrisini Excel olarak indirip inceleyebilir.
        # Satırlar = binalar (bina_etiketi), kolonlar = toplanma alanları (ad).
        # +inf değerler "Unreachable" string'ine çevrilir, Excel'de okunabilir.
        with st.expander("📥 Download OD matrix"):
            buildings_df = st.session_state.opt_buildings
            assembly_df  = st.session_state.opt_assembly
            row_labels = (
                buildings_df["bina_etiketi"].astype(str).tolist()
                if "bina_etiketi" in buildings_df.columns
                else [f"Bina {i+1}" for i in range(od.shape[0])]
            )
            col_labels = (
                assembly_df["ad"].astype(str).tolist()
                if "ad" in assembly_df.columns
                else [f"Alan {j+1}" for j in range(od.shape[1])]
            )
            # NaN/+inf'i Excel-okunabilir hâle getir
            od_display = pd.DataFrame(od, index=row_labels, columns=col_labels)
            od_display = od_display.round(2)
            od_display = od_display.where(np.isfinite(od_display), "Unreachable")

            from io import BytesIO as _BIO
            buf = _BIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                od_display.to_excel(writer, sheet_name="OD Matrix (minutes)")
                # Meta sheet — yöntem + parametreler
                _used_mode_str = st.session_state.get(
                    "opt_transport_mode_used", "walk"
                )
                _used_speed = st.session_state.get("opt_walk_speed_used", "?")
                _mode_human = (
                    "Driving (comparative analysis)"
                    if _used_mode_str == MODE_DRIVE
                    else "Walking (AFAD default)"
                )
                meta = pd.DataFrame([
                    {"Parameter": "Buildings",     "Value": od.shape[0]},
                    {"Parameter": "Assembly areas","Value": od.shape[1]},
                    {"Parameter": "Transport mode",
                     "Value": _mode_human},
                    {"Parameter": "Travel speed (km/h)",
                     "Value": _used_speed},
                    {"Parameter": "Cutoff (min)",
                     "Value": (st.session_state.get("opt_max_minutes") or "Unbounded")},
                    {"Parameter": "OD source",
                     "Value": st.session_state.get("opt_od_mode", "?")},
                    {"Parameter": "Reachable cells",
                     "Value": f"{reached:,} / {total:,} ({coverage_pct:.1f}%)"},
                ])
                meta.to_excel(writer, sheet_name="Meta", index=False)
            # Dosya adı mode-aware: walking ve driving OD matrislerini
            # yan yana koyduğunda kullanıcı kolayca ayırt edebilsin.
            _district_slug = (st.session_state.opt_district or "output").replace(" ", "_")
            _mode_suffix = (
                "drive" if _used_mode_str == MODE_DRIVE else "walk"
            )
            st.download_button(
                "⬇️ Download OD matrix (Excel)",
                data=buf.getvalue(),
                file_name=f"od_matrix_{_district_slug}_{_mode_suffix}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="opt_dl_od_xlsx",
                width="stretch",
                help=(
                    "Excel: Sheet 1 = the matrix itself (row=building, "
                    "col=area, value=minutes), 'Unreachable' = +∞. "
                    "Sheet 2 = parameter summary (incl. transport mode + speed)."
                ),
            )


# ════════════════════════════════════════════════════════════════════════════
# STEP 3 — OPTIMIZATION
# ════════════════════════════════════════════════════════════════════════════
if _have("opt_od_matrix"):
    cards.section_title(
        "3 · P-Median optimization",
        "Select the number of assembly areas to open and (optionally) enforce "
        "capacity. The solver auto-picks ILP or K-Medoids by problem size.",
    )

    n_area     = len(st.session_state.opt_assembly)
    n_building = len(st.session_state.opt_buildings)

    # ── Solver sabitlerini erkenden import et (UI'da ihtiyaç var) ────────
    from src.optimizer.p_median import ILP_THRESHOLD, ILP_TIME_LIMIT_SN

    with st.container(border=True):
        # ── Solver radio'sunu ana panele çıkar (Madde 1.5) ───────────────
        # Akademik terminoloji: Exact (ILP) / Heuristic (K-Medoids) / Auto.
        # Tezdeki "exact vs heuristic" karşılaştırmasını UI ile hizalar.
        st.markdown("**Solver method**")
        solver_label = st.radio(
            "Solver method",
            [
                f"🤖 Auto — Exact if ≤{ILP_THRESHOLD:,} buildings, else Heuristic",
                "🎯 Exact (ILP, PuLP/CBC) — mathematical optimum",
                "⚡ Heuristic (K-Medoids) — fast, approximate",
            ],
            index=0,
            horizontal=True,
            key="opt_solver_choice",
            label_visibility="collapsed",
            help=(
                "**Auto:** Picks by building count (ILP below the threshold, "
                "K-Medoids above). The `min_p95` objective always uses "
                "Heuristic.\n\n"
                "**Exact (ILP):** Mathematical optimum via PuLP/CBC. "
                "Preferred for small data sets. Large problems may hit the "
                "time limit.\n\n"
                "**Heuristic (K-Medoids):** Greedy init + 1-swap local "
                "search. Fast, ~1-5% optimality gap. Use for large data."
            ),
        )
        if "Auto" in solver_label:
            solver_mode = "auto"
        elif "Exact" in solver_label:
            solver_mode = "ilp"
        else:
            solver_mode = "kmedoids"

        c1, c2, c3 = st.columns([2, 1.2, 1], gap="medium")
        with c1:
            p = st.number_input(
                "Number of assembly areas to open (p)",
                min_value=1,
                max_value=n_area,
                value=min(5, n_area),
                step=1,
                key="opt_p_input",
            )
        with c2:
            objective_label = st.selectbox(
                "Objective",
                [
                    "Minimize total weighted time (efficiency)",
                    "Minimize worst-case time (fairness)",
                    "Minimize population-weighted p95 (robust fairness)",
                ],
                help=(
                    "• **Efficiency (min-sum):** classic p-median — minimizes "
                    "total weighted walking time.\n"
                    "• **Fairness (min-max):** minimizes the single worst walk; "
                    "average may rise slightly. Sensitive to a single outlier "
                    "building.\n"
                    "• **Robust fairness (p95):** population-weighted 95th "
                    "percentile. Outlier-resistant; recommended for AFAD "
                    "decision support. (Solved only by K-Medoids.)"
                ),
                key="opt_objective",
            )
            label_low = objective_label.lower()
            if "p95" in label_low:
                amac = "min_p95"
            elif "fairness" in label_low and "robust" not in label_low:
                amac = "min_max"
            else:
                amac = "min_sum"
        with c3:
            # Madde 1.6: alan bilgisi yoksa kapasite kısıtı anlamsız.
            area_available = bool(
                st.session_state.opt_assembly.attrs.get("area_available", True)
            )
            capacity = st.checkbox(
                "Capacity constraint" + ("" if area_available else " (no area data)"),
                value=False,
                disabled=(not area_available),
                help=(
                    "Capacity is derived from assembly area m² via the "
                    "density parameter (next field); assignments exceeding "
                    "it are forbidden.\n\n"
                    "**This option is disabled** because the loaded assembly "
                    "areas have no valid m² data — capacity cannot be computed."
                    if not area_available else
                    "Uses the configurable density (m²/person, default 1.5) "
                    "to forbid assignments that exceed each area's capacity."
                ),
            )

        # Yoğunluk varsayımı (m²/kişi) — kapasite kapasitesinin temelini oluşturur.
        # AFAD literatürü:
        #   • 1.0 m²/kişi — yüksek-yoğunluk acil (kısa süreli, max kapsama)
        #   • 1.5 m²/kişi — AFAD pratik acil toplanma (default — eski sabit davranış)
        #   • 2.5 m²/kişi — AFAD uzun süreli barınma standardı (daha rahat)
        # Karşılaştırmalı analiz: aynı problemi farklı yoğunluklarla çöz, kapasite
        # yetmezliği nerelerde ortaya çıkıyor incele.
        m2_per_person = 1.5  # disabled iken bile downstream'e şeffaf sabit gönder
        if area_available:
            from src.config.settings import AFAD_M2_PER_PERSON as _AFAD_DEFAULT
            m2_per_person = st.number_input(
                domain.capacity_method_label,
                min_value=0.5,
                max_value=5.0,
                value=float(_AFAD_DEFAULT),
                step=0.1,
                key="opt_m2_per_person",
                help=(
                    f"{domain.capacity_method_help_short}\n\n"
                    + (
                        "• **1.0** — high-density emergency (short-term, max coverage)\n"
                        "• **1.5** — AFAD assembly standard (default)\n"
                        "• **2.5** — AFAD long-term shelter standard (more comfort)\n\n"
                        if domain.show_afad_methodology
                        else "Default 1.5 is the AFAD value; tune to your domain.\n\n"
                    )
                    + "Only used when Capacity constraint is ON."
                ),
                disabled=(not capacity),
            )

        # Akademik tercih: hard walking-time limit kaldırıldı. Tüm
        # bina-alan çiftleri optimizasyonda admissible — uzun-yürüyüş
        # atamalar sonuçta görünür, karar verici yorumlar.
        # Aşağıdaki iki sabit değer downstream tüketicilerle (max_sure_dk,
        # enforce_cap argümanları) sözleşmeyi koruyor.
        max_walk_cap = None    # cutoff yok
        enforce_cap  = False   # solver tarafında hard limit kısıtı uygulanmaz

        # Stale-banner için CANLI girdi imzası — Step 3 her render olduğunda
        # güncellenir. Step 4 bu key'i okuyup `opt_result_signature` (solve
        # anındaki snapshot) ile karşılaştırarak parametre değişikliğini
        # tespit eder. Önceki sürüm `dir()` ile yerel scope'u kontrol
        # ediyordu — Streamlit script rerun'da scope kaybolduğunda
        # `solver_mode in dir() == False` döndüğünden imza diff'i
        # false-positive üretebiliyordu (H-Opt-2). Session_state daha
        # deterministik.
        # Stale-banner signature. Density sadece capacity ON iken anlamlı —
        # OFF iken None'a normalize ediyoruz ki density slider değişimi
        # capacity OFF iken stale uyarısı tetiklemesin.
        _live_density = float(m2_per_person) if capacity else None
        st.session_state["opt_current_inputs"] = (
            int(p), amac, bool(capacity), solver_mode, _live_density,
        )

        st.markdown(
            f'<div style="background:#F1F5F9;border:1px solid #E2E8F0;'
            f'border-radius:8px;padding:10px 14px;color:#334155;'
            f'font-size:0.8125rem">'
            f'ℹ <b>Travel-time limit:</b> none (all pairs admissible) · '
            f'<b>Objective:</b> {amac} · '
            f'<b>Capacity:</b> {"on" if capacity else "off"}'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Conflict: Exact (ILP) + min_p95 (p95 doğrusal değil)
        if solver_mode == "ilp" and amac == "min_p95":
            st.error(
                "⚠ The Exact (ILP) solver cannot be used with the P95 "
                "objective (P95 is non-linear). Set Solver to 'Auto' or "
                "'Heuristic (K-Medoids)', or change the Objective."
            )

        # ── Gelişmiş: ILP detayları (sadece ILP veya Auto modunda anlamlı) ──
        with st.expander("⚙️ Advanced ILP options"):
            ilp_unlimited = st.checkbox(
                "Unlimited time (run until proven optimal/infeasible)",
                value=False,
                key="opt_ilp_unlimited",
                help=(
                    "**Off (default):** CBC stops at the time limit below and "
                    "returns the best feasible integer solution found (or "
                    "falls back to K-Medoids, depending on the next option).\n\n"
                    "**On:** No time limit is sent to CBC — the solver runs "
                    "until it proves optimality or infeasibility. Useful for "
                    "academic comparison; **may take hours** on large problems."
                ),
                disabled=(solver_mode == "kmedoids"),
            )
            time_limit_sn = st.number_input(
                "ILP time limit (seconds)",
                min_value=10, max_value=86400, value=int(ILP_TIME_LIMIT_SN), step=30,
                key="opt_time_limit_sn",
                help=(
                    "Only meaningful in Exact (ILP) mode. Increase for large "
                    "problems. Tick 'Unlimited time' above to disable the "
                    "limit entirely. Max here is 86 400 s (24 h)."
                ),
                disabled=(solver_mode == "kmedoids") or ilp_unlimited,
            )
            # Sprint 2 #13: `unlimited` artık ayrı bir kwarg. UI'dan iki
            # değer paslıyoruz: effective_time_limit (her zaman int>0) +
            # ilp_unlimited (bool). coz() unlimited=True ise time_limit'i
            # yoksayar. Backward-compat: 0 sentinel'i hâlâ desteklenir ama
            # UI artık temiz API kullanıyor.
            effective_time_limit = int(time_limit_sn)
            allow_fallback = st.checkbox(
                "Fall back to Heuristic if Exact fails",
                value=True,
                key="opt_allow_fallback",
                help=(
                    "**On (default):** if ILP is infeasible or times out, "
                    "fall back to K-Medoids approximate.\n\n"
                    "**Off:** ILP failure raises — useful for academic "
                    "comparison / root-cause analysis. Combine with "
                    "'Unlimited time' above to insist on a proven ILP optimum."
                ),
                disabled=(solver_mode == "kmedoids"),
            )

            # ── ILP solver engine seçimi (kullanıcıda kurulu olanlar) ──
            # CBC default + bundled. Gurobi/HiGHS gibi commercial / modern
            # alternatifler büyük problem (19k+ bina × capacity) için CBC'den
            # 10-100× hızlı. PuLP runtime'da hangileri kurulu görür.
            from src.optimizer.p_median import list_available_ilp_engines
            _avail_engines = list_available_ilp_engines()
            _engine_keys = [k for k, _ in _avail_engines]
            _engine_labels = dict(_avail_engines)
            ilp_engine = st.selectbox(
                "ILP solver engine",
                options=_engine_keys,
                format_func=lambda k: _engine_labels.get(k, k.upper()),
                index=0,
                key="opt_ilp_engine",
                help=(
                    "Which MIP solver to use under the hood.\n\n"
                    "• **CBC** (default) — open-source, bundled. Adequate for "
                    "small/medium problems. Slow at 10,000+ buildings with "
                    "capacity constraints.\n"
                    "• **HiGHS** — open-source, modern. Often 3-10× faster "
                    "than CBC. Install: `pip install highspy`.\n"
                    "• **Gurobi** — commercial, free **academic license** "
                    "at gurobi.com/academia. 10-100× faster than CBC for "
                    "MIPs; the right choice for 19k buildings + capacity. "
                    "Install: `pip install gurobipy` + license file.\n"
                    "• **CPLEX** / **SCIP** — also academic-free alternatives.\n\n"
                    "Only solvers detected on this machine appear in the "
                    "dropdown. If you install a new one and don't see it, "
                    "restart Streamlit."
                ),
                disabled=(solver_mode == "kmedoids"),
            )

        # Çözüm yöntem rozeti — gerçek seçimi yansıtır
        if solver_mode == "auto":
            method_txt = (
                "ILP (PuLP / CBC)"
                if n_building <= ILP_THRESHOLD and amac != "min_p95"
                else "K-Medoids (heuristic)"
            )
        elif solver_mode == "ilp":
            method_txt = "ILP (PuLP / CBC) — forced"
        else:
            method_txt = "K-Medoids (heuristic) — forced"

        st.markdown(
            f'<div style="background:#DBEAFE;border:1px solid #BFDBFE;'
            f'border-radius:8px;padding:10px 14px;color:#1E40AF;'
            f'font-size:0.875rem;margin-top:8px">'
            f'<b>Solver:</b> {method_txt} &nbsp;·&nbsp; '
            f'<b>Buildings:</b> {n_building:,} &nbsp;·&nbsp; '
            f'<b>Areas:</b> {n_area:,}'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Sensitivity analysis
        with st.expander("🔬 Sensitivity analysis (optional)"):
            st.markdown(
                "Compare solution quality across a range of `p` values to "
                "identify the sweet spot."
            )
            s1, s2, s3 = st.columns([1, 1, 2])
            with s1:
                p_min = st.number_input("p min", 1, n_area, 1, key="opt_p_min")
            with s2:
                p_max = st.number_input(
                    "p max", 1, n_area, min(10, n_area), key="opt_p_max"
                )
            with s3:
                run_sens = st.button("Run analysis", key="opt_btn_sens")

            if run_sens:
                if p_min > p_max:
                    st.warning("p_min cannot exceed p_max.")
                else:
                    # Spinner + adım-adım progress bar — büyük ilçede 10 p × dk
                    # uzunluğunda analiz tek bir spinner'la donmuş gibi
                    # görünüyordu (H-Opt-6). Şimdi her p başlangıcında bar +
                    # status text güncellenir.
                    _sens_progress = st.progress(0.0)
                    _sens_status = st.empty()

                    def _sens_iter_cb(i: int, total: int, p_val: int) -> None:
                        # i = 0..total-1, p_val = aktif p değeri
                        _sens_progress.progress((i + 0) / max(total, 1))
                        _sens_status.info(
                            f"Solving p = **{p_val}** "
                            f"({i + 1}/{total})…"
                        )

                    try:
                        df_sens = duyarlilik_analizi(
                            st.session_state.opt_od_matrix,
                            st.session_state.opt_buildings,
                            st.session_state.opt_assembly,
                            p_aralik=range(p_min, p_max + 1),
                            kapasite=capacity,
                            max_sure_dk=(float(max_walk_cap) if enforce_cap else None),
                            amac=amac,
                            solver=solver_mode,
                            time_limit_sn=effective_time_limit,
                            unlimited=ilp_unlimited,
                            allow_fallback=allow_fallback,
                            ilp_engine=ilp_engine,
                            iter_cb=_sens_iter_cb,
                        )
                        _sens_progress.progress(1.0)
                        _sens_status.success(
                            f"Sensitivity analysis complete "
                            f"({p_max - p_min + 1} runs)."
                        )
                        df_sens_en = to_english(df_sens)
                        st.dataframe(
                            df_sens_en,
                            width="stretch",
                            hide_index=True,
                        )

                        # plot_cols dışarıda hesaplanıyor ki except dalında da görünür olsun
                        plot_cols = [
                            c for c in ["Avg Time (min)", "Max Time (min)"]
                            if c in df_sens_en.columns
                        ]

                        # Plot
                        if plot_cols:
                            try:
                                import plotly.express as px
                                fig = px.line(
                                    df_sens_en,
                                    x="p",
                                    y=plot_cols,
                                    markers=True,
                                    title="Travel time vs. p",
                                    color_discrete_sequence=[
                                        TOKENS["accent"], TOKENS["danger"],
                                    ],
                                )
                                fig.update_layout(
                                    font=dict(family="Inter, sans-serif"),
                                    plot_bgcolor="white",
                                    paper_bgcolor="white",
                                    margin=dict(l=20, r=20, t=50, b=20),
                                    height=360,
                                    xaxis=dict(gridcolor="#F1F5F9"),
                                    yaxis=dict(gridcolor="#F1F5F9", title="Minutes"),
                                )
                                st.plotly_chart(fig, width="stretch")
                            except ImportError:
                                st.line_chart(df_sens_en.set_index("p")[plot_cols])

                    except Exception as e:
                        _sens_progress.empty()
                        _sens_status.empty()
                        st.error(f"Sensitivity analysis failed: {e}")

        st.markdown(
            '<div style="height:12px"></div>',
            unsafe_allow_html=True,
        )

        # Solver/amac çakışması varsa "Run" butonunu devre dışı bırak
        invalid_combo = (solver_mode == "ilp" and amac == "min_p95")
        # Sprint 2 #11: non-residential acknowledgement zorunlu ise
        # devam etmeyi engelle (warning Step 1'de gösterildi, ack
        # session_state'e yazılıyor).
        nr_ack_ok = st.session_state.get("opt_non_residential_acknowledged", True)
        run_disabled = invalid_combo or (not nr_ack_ok)

        if (not nr_ack_ok):
            st.caption(
                "⛔ Run is disabled — first acknowledge the non-residential "
                "warning at the top of **Step 1** (Data)."
            )

        if st.button(
            "🚀 Run optimization",
            key="opt_btn_opt",
            type="primary",
            width="stretch",
            disabled=run_disabled,
        ):
            st.session_state.opt_logs = []
            with st.spinner(f"Running optimization (p={p}) — this may take a moment…"):
                try:
                    # Kullanıcı seçtiği yoğunluğa göre kapasite kolonunu
                    # yeniden hesapla. Capacity OFF iken bu dokunulmaz; ama
                    # ON iken hard-coded 1.5 yerine slider değeri kullanılır.
                    assembly_for_solve = st.session_state.opt_assembly
                    if capacity and "area_m2" in assembly_for_solve.columns:
                        from src.optimizer.population_estimator import (
                            estimate_capacity_afad,
                        )
                        assembly_for_solve = assembly_for_solve.copy()
                        assembly_for_solve["kapasite"] = estimate_capacity_afad(
                            assembly_for_solve["area_m2"],
                            m2_per_person=float(m2_per_person),
                        )

                    result = coz(
                        st.session_state.opt_od_matrix,
                        st.session_state.opt_buildings,
                        assembly_for_solve,
                        p=int(p),
                        kapasite=capacity,
                        max_sure_dk=(float(max_walk_cap) if enforce_cap else None),
                        amac=amac,
                        progress_cb=log_cb,
                        solver=solver_mode,
                        time_limit_sn=effective_time_limit,
                        unlimited=ilp_unlimited,
                        allow_fallback=allow_fallback,
                        ilp_engine=ilp_engine,
                    )
                    st.session_state.opt_result = result
                    # Kullanılan yoğunluğu kaydet — Excel + report için
                    st.session_state["opt_m2_per_person_used"] = (
                        float(m2_per_person) if capacity else None
                    )
                    # Stale-banner: Step 3 sonucu için signature kaydet.
                    # Kullanıcı sonra p / amac / capacity / solver değişirse
                    # Step 4 sonuç ekranında uyarı görünür.
                    st.session_state["opt_result_signature"] = (
                        int(p), amac, bool(capacity), solver_mode,
                        float(m2_per_person) if capacity else None,
                    )

                    # Fizibilite uyarısı varsa kullanıcıya göster (kapasite/ulaşılabilirlik)
                    if result.fizibilite_uyarisi:
                        st.warning(result.fizibilite_uyarisi)
                    # ILP→K-Medoids fallback olduysa nedeni göster
                    if result.fallback_nedeni:
                        st.info(f"ℹ Fallback: {result.fallback_nedeni}")

                    unreach_txt = (
                        f" · ⚠ {result.ulasilamaz_sayisi} building(s) unreachable"
                        if result.ulasilamaz_sayisi else ""
                    )
                    st.success(
                        f"✅ Optimization complete — solved in "
                        f"{result.cozum_suresi_sn:.1f}s using {result.yontem}"
                        f"{unreach_txt}"
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Optimization error: {e}")
                    log.exception("Optimization error")

        # ── Compare: Capacity ON vs OFF ─────────────────────────────────
        # Akademik / danışman gereksinimi: aynı p ve hedef altında kapasite
        # kısıtının nasıl bir fark yarattığını yan-yana göster. Aynı problem
        # iki kez çözülür (capacity=False, capacity=True with current
        # density slider). KPI'lar, açılan alanlar, ulaşılamaz binalar
        # karşılaştırılır → tez raporunda "Sensitivity Analysis" figürü.
        with st.expander("📊 Compare capacity ON vs OFF (advanced)"):
            st.markdown(
                "Run the same problem twice — once **without** capacity "
                "constraints, once **with**. The diff shows how AFAD-style "
                "capacity reshapes assignments, walking times, and which "
                "areas get opened. Useful for thesis sensitivity analysis."
            )
            cmp_disabled = not area_available
            if cmp_disabled:
                st.info(
                    "Capacity compare is disabled because the loaded assembly "
                    "areas have no valid m² data — there is no capacity to "
                    "constrain against."
                )
            if st.button(
                "🔬 Run capacity comparison (2 solves)",
                key="opt_btn_cmp_cap",
                disabled=cmp_disabled or invalid_combo,
                width="stretch",
            ):
                st.session_state.opt_logs = []
                with st.spinner(
                    f"Comparing capacity scenarios (p={p}, density="
                    f"{m2_per_person:.2f} m²/person) — 2 solves…"
                ):
                    try:
                        from src.optimizer.population_estimator import (
                            estimate_capacity_afad,
                        )
                        # OFF: original GDF (kapasite kolonu ne olursa olsun
                        # kullanılmayacak — coz() kapasite=False ile çağrılır)
                        result_off = coz(
                            st.session_state.opt_od_matrix,
                            st.session_state.opt_buildings,
                            st.session_state.opt_assembly,
                            p=int(p),
                            kapasite=False,
                            max_sure_dk=None,
                            amac=amac,
                            progress_cb=log_cb,
                            solver=solver_mode,
                            time_limit_sn=effective_time_limit,
                            unlimited=ilp_unlimited,
                            allow_fallback=allow_fallback,
                            ilp_engine=ilp_engine,
                        )
                        # ON: capacity recompute with slider density
                        a_on = st.session_state.opt_assembly
                        if "area_m2" in a_on.columns:
                            a_on = a_on.copy()
                            a_on["kapasite"] = estimate_capacity_afad(
                                a_on["area_m2"],
                                m2_per_person=float(m2_per_person),
                            )
                        result_on = coz(
                            st.session_state.opt_od_matrix,
                            st.session_state.opt_buildings,
                            a_on,
                            p=int(p),
                            kapasite=True,
                            max_sure_dk=None,
                            amac=amac,
                            progress_cb=log_cb,
                            solver=solver_mode,
                            time_limit_sn=effective_time_limit,
                            unlimited=ilp_unlimited,
                            allow_fallback=allow_fallback,
                            ilp_engine=ilp_engine,
                        )
                        st.session_state["opt_compare_results"] = {
                            "off": result_off,
                            "on": result_on,
                            "density": float(m2_per_person),
                            "p": int(p),
                            "amac": amac,
                        }
                        st.success(
                            "✅ Comparison complete. See the **Capacity "
                            "comparison** section in Step 4 below."
                        )
                        # Mevcut tek-sonuç akışını da güncel tut: kullanıcı
                        # ON sonucunu birincil sayar (capacity-aware analiz).
                        st.session_state.opt_result = result_on
                        st.session_state["opt_m2_per_person_used"] = float(m2_per_person)
                        st.session_state["opt_result_signature"] = (
                            int(p), amac, True, solver_mode, float(m2_per_person),
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Comparison failed: {e}")
                        log.exception("Capacity comparison error")


# ════════════════════════════════════════════════════════════════════════════
# STEP 4 — RESULTS
# ════════════════════════════════════════════════════════════════════════════
if _have("opt_result"):
    result: PMedianResult = st.session_state.opt_result

    # Stale-result banner (Step 3 sonrası parametre değişti mi?). Result
    # üretildiğindeki (p, amac, capacity, solver) ile UI'daki güncel
    # değerleri karşılaştır. Fark varsa kullanıcı sonucu yorumlarken
    # yanlış parametre setini sandığını bilmesin.
    #
    # H-Opt-2 düzeltmesi: önceki sürüm `dir()` ile yerel scope'u sorgulayıp
    # `p`, `amac`, vs. tanımlı mı kontrol ediyordu. Streamlit script rerun'unda
    # Step 3 bloğu çalışmadıysa (örn. opt_buildings None iken eski result
    # session'da kalmışsa) bu kontroller False döner, sonuç solver_mode için
    # None ile karşılaştırma → false-positive uyarı. Şimdi Step 3 her render
    # olduğunda `opt_current_inputs` yazıyor; burada onu okuyoruz.
    _res_sig = st.session_state.get("opt_result_signature")
    _current_res_sig = st.session_state.get("opt_current_inputs")
    if (
        _res_sig is not None
        and _current_res_sig is not None
        and _res_sig != _current_res_sig
    ):
        _diff = []
        if _res_sig[0] != _current_res_sig[0]:
            _diff.append(f"p ({_res_sig[0]} → {_current_res_sig[0]})")
        if _res_sig[1] != _current_res_sig[1]:
            _diff.append(f"objective ({_res_sig[1]} → {_current_res_sig[1]})")
        if _res_sig[2] != _current_res_sig[2]:
            _diff.append(
                f"capacity ({'on' if _res_sig[2] else 'off'} → "
                f"{'on' if _current_res_sig[2] else 'off'})"
            )
        if _res_sig[3] != _current_res_sig[3]:
            _diff.append(f"solver ({_res_sig[3]} → {_current_res_sig[3]})")
        # 5. eleman density — sadece capacity ON iken karşılaştırılır
        if len(_res_sig) > 4 and len(_current_res_sig) > 4:
            if _res_sig[4] != _current_res_sig[4]:
                _old_d = "N/A" if _res_sig[4] is None else f"{_res_sig[4]:.2f}"
                _new_d = "N/A" if _current_res_sig[4] is None else f"{_current_res_sig[4]:.2f}"
                _diff.append(f"density m²/person ({_old_d} → {_new_d})")
        if _diff:
            st.warning(
                "⚠ **Result is stale.** Parameters changed: "
                + ", ".join(_diff)
                + ". The KPIs below reflect the **old solution** — "
                "do not produce reports without re-running **Run optimization**."
            )

    if result.amac == "min_max":
        objective_txt = "Min-Max (fairness)"
    elif result.amac == "min_p95":
        objective_txt = "Min-P95 (robust fairness)"
    else:
        objective_txt = "Min-Sum (efficiency)"
    cap_txt = "Capacity ON" if result.kapasite_aktif else "Capacity OFF"
    # Walking-time-cap kaldırıldı (akademik tercih); satıra koymuyoruz.
    # Transport mode bilgisi daha anlamlı.
    _res_mode = st.session_state.get("opt_transport_mode_used", "walk")
    _res_speed = st.session_state.get("opt_walk_speed_used", "?")
    _res_mode_txt = (
        f"🚗 Driving @ {_res_speed} km/h"
        if _res_mode == MODE_DRIVE
        else f"🚶 Walking @ {_res_speed} km/h"
    )
    cards.section_title(
        "4 · Results",
        f"Solved with {result.yontem} in {result.cozum_suresi_sn:.1f}s · "
        f"{objective_txt} · {cap_txt} · {_res_mode_txt}.",
    )

    # K-Medoids convergence banner — solver kalitesi şeffaflığı.
    # ILP path None döner (PuLP/CBC için convergence kavramı farklı —
    # `ilp_status` zaten taşınır). K-Medoids için True=converged (locally
    # optimal certified), False=MAX_ITER hit (best-found, NOT certified).
    if result.kmedoids_converged is True:
        _iter_n = result.kmedoids_iterations or 0
        st.success(
            f"✓ **Local search converged** in {_iter_n} iteration(s). "
            f"Solution is certified locally optimal (no improving 1-swap "
            f"found within the K-Medoids neighbourhood)."
        )
    elif result.kmedoids_converged is False:
        from src.optimizer.p_median import KMEDOIDS_MAX_ITER
        st.warning(
            f"⚠ **Local search hit MAX_ITER={KMEDOIDS_MAX_ITER} limit** — "
            f"the result is the best found so far but is **NOT certified** "
            f"locally optimal. The heuristic may have missed further "
            f"improving swaps. Interpret KPIs as an upper bound on the "
            f"objective; consider re-running with a different random seed "
            f"or smaller problem partition."
        )
    elif result.yontem == "ILP" and result.ilp_status:
        # Bilgi banner'ı — ILP path için convergence yerine PuLP status
        if result.ilp_status == "Optimal":
            st.success(
                f"✓ **ILP solved to optimality** (CBC status: "
                f"`{result.ilp_status}`). Solution is provably globally "
                f"optimal under the formulated constraints."
            )

    # ILP → K-Medoids fallback banner — sticky görünür uyarı.
    # `result.fallback_nedeni` populate edilmiş ise kullanıcı ILP'nin
    # başarısız olduğunu (infeasible / time limit / capacity-tight) net
    # görsün. Raporda "exact optimum" ile "heuristic fallback" ayrımı
    # akademik şeffaflık için kritik.
    if result.fallback_nedeni:
        st.info(
            f"ℹ **Solver fallback used:** the exact ILP attempt did not "
            f"yield a usable solution → switched to K-Medoids heuristic. "
            f"**Reason:** {result.fallback_nedeni} "
            f"Reported KPIs reflect the heuristic solution, NOT a provably "
            f"optimal ILP solution. Consider relaxing constraints (capacity, "
            f"p) if you need the exact optimum."
        )

    # ── Capacity ON vs OFF comparison ───────────────────────────────────────
    # `opt_compare_results` Step 3'teki "Compare capacity ON vs OFF" butonu
    # tıklandığında populate edilir. Sonuç yan-yana KPI tablosu + alan-seti
    # diff. Akademik / tez raporu için sensitivity analizi.
    _cmp = st.session_state.get("opt_compare_results")
    if _cmp is not None:
        st.markdown("---")
        st.markdown(
            f"### 🔬 Capacity sensitivity comparison\n"
            f"_Same problem (p={_cmp['p']}, objective={_cmp['amac']}) "
            f"solved with capacity OFF and capacity ON @ "
            f"**{_cmp['density']:.2f} m²/person**._"
        )
        r_off = _cmp["off"]
        r_on  = _cmp["on"]

        # Sayı diff helper
        def _fmt_diff(off_v: float, on_v: float, unit: str = "", precision: int = 1) -> str:
            d = on_v - off_v
            sign = "+" if d > 0 else ""
            if abs(d) < 0.05 and precision <= 1:
                return "≈ same"
            return f"{sign}{d:.{precision}f}{unit}"

        cmp_df = pd.DataFrame({
            "Metric": [
                "Avg travel time (min)",
                "Max travel time (min)",
                "P95 travel time (pop-w., min)",
                "Pop-weighted avg time (min)",
                "Coverage <10 min (%)",
                "Pop coverage <10 min (%)",
                "Unreachable buildings",
                "Solve time (s)",
                "Method",
            ],
            "Capacity OFF": [
                f"{r_off.ort_sure_dk:.1f}",
                f"{r_off.max_sure_dk:.1f}",
                f"{r_off.p95_sure_dk:.1f}",
                f"{r_off.agirlikli_ort_sure_dk:.1f}",
                f"{r_off.kapsama_10dk_pct:.1f}",
                f"{r_off.nufus_kapsama_10dk_pct:.1f}",
                f"{r_off.ulasilamaz_sayisi:,}",
                f"{r_off.cozum_suresi_sn:.1f}",
                r_off.yontem,
            ],
            "Capacity ON": [
                f"{r_on.ort_sure_dk:.1f}",
                f"{r_on.max_sure_dk:.1f}",
                f"{r_on.p95_sure_dk:.1f}",
                f"{r_on.agirlikli_ort_sure_dk:.1f}",
                f"{r_on.kapsama_10dk_pct:.1f}",
                f"{r_on.nufus_kapsama_10dk_pct:.1f}",
                f"{r_on.ulasilamaz_sayisi:,}",
                f"{r_on.cozum_suresi_sn:.1f}",
                r_on.yontem,
            ],
            "Δ (ON − OFF)": [
                _fmt_diff(r_off.ort_sure_dk, r_on.ort_sure_dk, " min"),
                _fmt_diff(r_off.max_sure_dk, r_on.max_sure_dk, " min"),
                _fmt_diff(r_off.p95_sure_dk, r_on.p95_sure_dk, " min"),
                _fmt_diff(r_off.agirlikli_ort_sure_dk, r_on.agirlikli_ort_sure_dk, " min"),
                _fmt_diff(r_off.kapsama_10dk_pct, r_on.kapsama_10dk_pct, " pp"),
                _fmt_diff(r_off.nufus_kapsama_10dk_pct, r_on.nufus_kapsama_10dk_pct, " pp"),
                _fmt_diff(r_off.ulasilamaz_sayisi, r_on.ulasilamaz_sayisi, "", 0),
                _fmt_diff(r_off.cozum_suresi_sn, r_on.cozum_suresi_sn, " s"),
                "same" if r_off.yontem == r_on.yontem else f"{r_off.yontem} → {r_on.yontem}",
            ],
        })
        st.dataframe(cmp_df, width="stretch", hide_index=True)

        # Açılan alan-seti diff: hangi alanlar paylaşılıyor, ON'a özgü olan
        # / OFF'a özgü olan? Karar destek raporu için kritik.
        off_set = set(r_off.acik_alan_adlari)
        on_set  = set(r_on.acik_alan_adlari)
        shared = sorted(off_set & on_set)
        only_off = sorted(off_set - on_set)
        only_on  = sorted(on_set - off_set)

        c_sh, c_off, c_on = st.columns(3, gap="small")
        with c_sh:
            cards.kpi_card("Shared areas (both)", len(shared))
        with c_off:
            cards.kpi_card("Only when OFF", len(only_off))
        with c_on:
            cards.kpi_card("Only when ON", len(only_on))

        with st.expander("📋 Area set details (which areas opened where)"):
            if shared:
                st.markdown("**Opened in both scenarios:** " + ", ".join(shared))
            if only_off:
                st.markdown(
                    f"**Only when capacity OFF** ({len(only_off)}): "
                    + ", ".join(only_off)
                )
            if only_on:
                st.markdown(
                    f"**Only when capacity ON** ({len(only_on)}): "
                    + ", ".join(only_on)
                )

        # Interpretation hint — jüri/okuyucu için yön çizgisi
        delta_unreach = r_on.ulasilamaz_sayisi - r_off.ulasilamaz_sayisi
        delta_avg = r_on.ort_sure_dk - r_off.ort_sure_dk
        hints = []
        if delta_unreach > 0:
            hints.append(
                f"Capacity tightness leaves **{delta_unreach:,} more "
                f"buildings unreachable** (no area has spare seats within "
                f"reach)."
            )
        if delta_avg > 0.5:
            hints.append(
                f"Average travel time rises by **{delta_avg:.1f} min** when "
                f"capacity is enforced — population is pushed to less-ideal "
                f"areas."
            )
        if only_on and not only_off:
            hints.append(
                "Capacity ON opens additional areas that OFF would skip "
                "(larger / better-positioned for spreading demand)."
            )
        if hints:
            st.info(" ".join(hints))
        st.markdown("---")

    # KPI row — building-count metrics (mode-aware label'lar).
    # "Travel time" terimi hem walking hem driving senaryosunda nötr.
    k1, k2, k3, k4, k5 = st.columns(5, gap="small")
    with k1:
        cards.kpi_card(
            f"{domain.facility_singular.capitalize()}s opened (p)",
            int(result.p),
        )
    with k2:
        cards.kpi_card("Avg travel time (min)", f"{result.ort_sure_dk:.1f}")
    with k3:
        cards.kpi_card("Max travel time (min)", f"{result.max_sure_dk:.1f}")
    with k4:
        # P95 düzeltmesi: rapor edilen p95 nüfus-ağırlıklı (hedef fonk.
        # ile tutarlı). Etiket bunu açıkça söylüyor — eski "P95 time"
        # bina-bazlı ile karıştırılabiliyordu.
        cards.kpi_card("P95 travel time (pop-w., min)", f"{result.p95_sure_dk:.1f}")
    with k5:
        cards.kpi_card("Method", result.yontem)

    # KPI row — population-weighted metrics
    k6, k7, k8, k9, k10 = st.columns(5, gap="small")
    with k6:
        cards.kpi_card("Pop-weighted avg (min)", f"{result.agirlikli_ort_sure_dk:.1f}")
    with k7:
        cards.kpi_card("Pop coverage <5 min", f"{result.nufus_kapsama_5dk_pct:.0f}%")
    with k8:
        cards.kpi_card("Pop coverage <10 min", f"{result.nufus_kapsama_10dk_pct:.0f}%")
    with k9:
        cards.kpi_card("Pop coverage <30 min", f"{result.nufus_kapsama_30dk_pct:.0f}%")
    with k10:
        cards.kpi_card("Unreachable bldgs", f"{result.ulasilamaz_sayisi:,}")

    # Unreachable warning — cutoff yok, ulaşılamazlık graf topolojisinden
    # (kopuk bileşen) veya kapasite yetersizliğinden gelir.
    if result.ulasilamaz_sayisi > 0:
        st.warning(
            f"⚠ **{result.ulasilamaz_sayisi:,} buildings** "
            f"(≈ {result.ulasilamaz_nufus:,.0f} people) could not be assigned "
            f"to any assembly area — either the transport network is "
            f"fragmented (no path exists) or capacity was exhausted. "
            f"See the dedicated section below for per-building reasons."
        )

    # ── Coverage chart (Plotly) ─────────────────────────────────────────────
    cards.section_title("Coverage by travel-time threshold")
    # H1: thresholds/values import'tan ÖNCE tanımlanmalı. Aksi halde plotly
    # ImportError düşerse except dalı tanımsız değişken erişip NameError
    # üretir — fallback'in tüm amacı bunu önlemekti.
    thresholds = ["< 5 min", "< 10 min", "< 30 min"]
    values = [
        float(result.kapsama_5dk_pct),
        float(result.kapsama_10dk_pct),
        float(result.kapsama_30dk_pct),
    ]
    try:
        import plotly.graph_objects as go

        colors = [TOKENS["danger"], TOKENS["warning"], TOKENS["success"]]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=thresholds,
            y=values,
            marker_color=colors,
            text=[f"{v:.1f}%" for v in values],
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>Coverage: %{y:.1f}%<extra></extra>",
        ))
        fig.update_layout(
            font=dict(family="Inter, sans-serif", color=TOKENS["text"]),
            plot_bgcolor="white",
            paper_bgcolor="white",
            height=340,
            margin=dict(l=20, r=20, t=20, b=20),
            yaxis=dict(title="Coverage (%)", range=[0, 105],
                       gridcolor="#F1F5F9", linecolor="#E2E8F0"),
            xaxis=dict(linecolor="#E2E8F0"),
            showlegend=False,
        )
        st.plotly_chart(fig, width="stretch")
    except ImportError:
        st.bar_chart(
            pd.DataFrame(
                {
                    "Threshold": thresholds,
                    "Coverage (%)": values,
                }
            ).set_index("Threshold")
        )

    # ── Area-level summary ──────────────────────────────────────────────────
    cards.section_title("Area-level summary")
    alan_en = to_english(result.alan_ozeti)
    st.dataframe(alan_en, width="stretch", hide_index=True, height=360)

    # ── Building assignment explorer ────────────────────────────────────────
    atamalar_en = to_english(result.atamalar)
    cards.section_title(
        "Building assignments",
        "Each row states exactly which assembly area a building is assigned to.",
    )

    assigned_total = len(atamalar_en)
    far_count = int((atamalar_en["Time (min)"] > 15).sum()) if "Time (min)" in atamalar_en.columns else 0
    excellent_count = (
        int((atamalar_en["Access Quality"] == "Excellent").sum())
        if "Access Quality" in atamalar_en.columns else 0
    )

    a1, a2, a3, a4 = st.columns(4, gap="small")
    with a1:
        cards.kpi_card("Assigned buildings", f"{assigned_total:,}")
    with a2:
        cards.kpi_card("Selected areas", len(result.acik_alanlar))
    with a3:
        cards.kpi_card("Excellent access", f"{excellent_count:,}")
    with a4:
        cards.kpi_card(">15 min buildings", f"{far_count:,}")

    with st.container(border=True):
        f1, f2, f3 = st.columns([1.2, 1.2, 1.6], gap="medium")
        with f1:
            area_options = ["All"] + sorted(
                atamalar_en["Assembly Area"].dropna().astype(str).unique().tolist()
            ) if "Assembly Area" in atamalar_en.columns else ["All"]
            selected_area = st.selectbox(
                "Assigned assembly area",
                area_options,
                key="opt_assign_area_filter",
            )
        with f2:
            quality_options = (
                atamalar_en["Access Quality"].dropna().astype(str).unique().tolist()
                if "Access Quality" in atamalar_en.columns else []
            )
            selected_qualities = st.multiselect(
                "Access quality",
                quality_options,
                default=quality_options,
                key="opt_assign_quality_filter",
            )
        with f3:
            assignment_query = st.text_input(
                "Search assignments",
                placeholder="Building label, neighborhood, assembly area…",
                key="opt_assign_search",
            )

        shown = atamalar_en.copy()
        if selected_area != "All" and "Assembly Area" in shown.columns:
            shown = shown[shown["Assembly Area"].astype(str) == selected_area]
        if selected_qualities and "Access Quality" in shown.columns:
            shown = shown[shown["Access Quality"].astype(str).isin(selected_qualities)]
        if assignment_query:
            patt = assignment_query.strip().lower()
            mask = shown.apply(
                lambda c: c.astype(str).str.lower().str.contains(patt, na=False, regex=False)
            ).any(axis=1)
            shown = shown[mask]

        readable_cols = [
            "Building Label", "Assignment", "Neighborhood", "Assembly Area",
            "Time (min)", "Time Band", "Access Quality", "Weight",
        ]
        readable_cols = [c for c in readable_cols if c in shown.columns]
        st.dataframe(
            shown[readable_cols] if readable_cols else shown,
            width="stretch",
            hide_index=True,
            height=420,
        )
        st.caption(f"{len(shown):,} of {assigned_total:,} assignments shown")

    with st.expander("📋 Full assignment table with coordinates"):
        st.dataframe(atamalar_en, width="stretch", hide_index=True, height=420)

    if "Time (min)" in atamalar_en.columns:
        with st.expander("⚠️ Buildings with longest travel times"):
            worst = atamalar_en.sort_values("Time (min)", ascending=False).head(20)
            worst_cols = [
                "Building Label", "Assignment", "Neighborhood", "Time (min)",
                "Time Band", "Access Quality",
            ]
            worst_cols = [c for c in worst_cols if c in worst.columns]
            st.dataframe(worst[worst_cols], width="stretch", hide_index=True)

    # ── Building detail card (search / select one building) ────────────────
    if "Building Label" in atamalar_en.columns:
        cards.section_title(
            "Building detail card",
            "Pick any building to see its assigned area, walking time, and "
            "the three next-best alternatives the solver considered.",
        )
        with st.container(border=True):
            label_options = atamalar_en["Building Label"].astype(str).tolist()
            selected_label = st.selectbox(
                "Search a building by label",
                options=[""] + sorted(set(label_options)),
                index=0,
                key="opt_detail_pick",
                help="Labels come from OSM name → falling back to 'Neighborhood Mh. #N'.",
            )
            if selected_label:
                row_df = atamalar_en[atamalar_en["Building Label"].astype(str) == selected_label]
                if not row_df.empty:
                    r = row_df.iloc[0]
                    dc1, dc2, dc3, dc4 = st.columns(4, gap="small")
                    with dc1:
                        cards.kpi_card("Assembly area", str(r.get("Assembly Area", "—")))
                    with dc2:
                        t_val = r.get("Time (min)", float("nan"))
                        cards.kpi_card(
                            "Walking time",
                            f"{float(t_val):.1f} min" if pd.notna(t_val) else "—",
                        )
                    with dc3:
                        cards.kpi_card("Access quality", str(r.get("Access Quality", "—")))
                    with dc4:
                        w_val = r.get("Weight", 0)
                        cards.kpi_card(
                            "Estimated population",
                            f"{float(w_val):.0f}" if pd.notna(w_val) else "—",
                        )

                    st.markdown("**Assignment statement**")
                    st.success(f"➡ {r.get('Assignment', selected_label)}")

                    # Alternatives block
                    alt_rows = []
                    for k in range(1, 4):
                        col_name = f"alternatif_{k}"
                        col_sure = f"alternatif_{k}_sure"
                        # to_english doesn't map these — use raw names from atamalar
                        raw = result.atamalar
                        raw_row = raw[raw["bina_etiketi"].astype(str) == selected_label]
                        if not raw_row.empty and col_name in raw_row.columns:
                            name = raw_row.iloc[0].get(col_name, "")
                            sure = raw_row.iloc[0].get(col_sure, float("nan"))
                            if name:
                                alt_rows.append({
                                    "Rank":           f"#{k}",
                                    "Alternative":    str(name),
                                    "Time (min)":     (
                                        round(float(sure), 2) if pd.notna(sure) else "—"
                                    ),
                                })
                    if alt_rows:
                        st.markdown("**Next-best alternatives (not chosen)**")
                        st.dataframe(
                            pd.DataFrame(alt_rows),
                            width="stretch",
                            hide_index=True,
                        )

                    # Mini-map for this building
                    try:

                        import folium
                        from streamlit_folium import st_folium

                        from components.map_builder import safe_field

                        # Coordinate read with explicit null check — using
                        # `if b_lat and a_lat` would silently suppress legit
                        # cases where the coordinate is exactly 0 (rare, but
                        # the equator/prime-meridian sentinel can sneak in
                        # from "missing" data normalisation upstream).
                        b_lat_raw = r.get("Building Latitude")
                        b_lon_raw = r.get("Building Longitude")
                        a_lat_raw = r.get("Area Latitude")
                        a_lon_raw = r.get("Area Longitude")
                        coords_ok = all(
                            pd.notna(v) for v in (b_lat_raw, b_lon_raw, a_lat_raw, a_lon_raw)
                        )
                        if coords_ok:
                            b_lat = float(b_lat_raw)
                            b_lon = float(b_lon_raw)
                            a_lat = float(a_lat_raw)
                            a_lon = float(a_lon_raw)
                            m_detail = folium.Map(
                                location=[(b_lat + a_lat) / 2, (b_lon + a_lon) / 2],
                                zoom_start=16,
                                tiles="CartoDB positron",
                            )
                            # Tooltip değerleri (selected_label, Assembly Area)
                            # kullanıcı upload'undan gelir; folium tooltip'i HTML olarak
                            # render eder → merkezi safe_field zorunlu.
                            _safe_label = safe_field(selected_label)
                            _safe_area  = safe_field(r.get("Assembly Area", ""))
                            folium.CircleMarker(
                                [b_lat, b_lon], radius=7, color="#e6194b",
                                fill=True, fill_color="#e6194b", fill_opacity=0.9,
                                tooltip=f"🏠 {_safe_label}",
                            ).add_to(m_detail)
                            folium.Marker(
                                [a_lat, a_lon],
                                tooltip=f"⭐ {_safe_area}",
                                icon=folium.Icon(color="blue", icon="star", prefix="fa"),
                            ).add_to(m_detail)
                            folium.PolyLine(
                                [[b_lat, b_lon], [a_lat, a_lon]],
                                color="#4363d8", weight=3, opacity=0.7,
                            ).add_to(m_detail)
                            st_folium(m_detail, width="100%", height=320, returned_objects=[])
                    except Exception as e:
                        st.caption(f"Mini-map unavailable: {e}")

    # ── Unreachable buildings panel ────────────────────────────────────────
    if not result.ulasilamaz_binalar.empty:
        cards.section_title(
            "Unreachable buildings",
            "These buildings could not be assigned to any assembly area — "
            "either no path exists in the transport network (fragmented "
            "graph) or capacity was exhausted. They are excluded from the "
            "objective function and KPI averages but listed separately so "
            "you can address them by adding new candidate areas, fixing the "
            "graph topology, or relaxing the capacity constraint.",
        )
        unreach_en = to_english(result.ulasilamaz_binalar)
        st.dataframe(unreach_en, width="stretch", hide_index=True, height=300)

    # ── Map ─────────────────────────────────────────────────────────────────
    cards.section_title("Assignment map")
    show_lines = st.checkbox(
        "Draw connection lines (slower)",
        value=False,
        key="opt_show_lines",
    )

    with st.spinner("Rendering map…"):
        try:
            from streamlit_folium import st_folium

            m = render_atama_haritasi(
                result,
                st.session_state.opt_buildings,
                st.session_state.opt_assembly,
                cizgiler=show_lines,
            )
            st_folium(m, width="100%", height=620, returned_objects=[])
        except Exception as e:
            st.warning(f"Map could not be rendered: {e}")

    # ── Downloads ───────────────────────────────────────────────────────────
    cards.section_title("Downloads", "Outputs are in English and decision-ready.")

    d1, d2 = st.columns(2, gap="medium")

    with d1:
        st.markdown("**Assignments (CSV)**")
        csv_bytes = atamalar_en.to_csv(
            index=False, encoding="utf-8-sig"
        ).encode("utf-8-sig")
        st.download_button(
            "⬇️ Download CSV",
            data=csv_bytes,
            file_name=f"assignments_p{result.p}.csv",
            mime="text/csv",
            key="opt_dl_csv",
            width="stretch",
        )

    with d2:
        st.markdown("**Full report (Excel)**")
        try:
            from src.services.excel_utils import build_styled_workbook

            def _write_optimization_sheets(writer: pd.ExcelWriter) -> None:
                # ── 1. Executive Summary ────────────────────────────────
                # P95 düzeltmesi: Building-count grubunda bina-bazlı
                # (ağırlıksız) p95; Population-weighted grubunda
                # nüfus-ağırlıklı p95. Etiketler hangi metriğin hangi
                # ağırlık mantığını kullandığını açıkça gösterir. Birincil
                # `p95_sure_dk` artık nüfus-ağırlıklı (hedef fonk. ile
                # tutarlı); informasyonel ağırlıksız `p95_bina_sure_dk`.
                _summ_mode = st.session_state.get("opt_transport_mode_used", "walk")
                _summ_speed = st.session_state.get("opt_walk_speed_used", "?")
                _summ_mode_label = (
                    f"Driving (comparative) @ {_summ_speed} km/h"
                    if _summ_mode == MODE_DRIVE
                    else f"Walking (AFAD default) @ {_summ_speed} km/h"
                )
                summary_df = pd.DataFrame({
                    "Metric": [
                        "Use case (domain)",
                        "District",
                        "Transport mode",
                        "Objective",
                        "Travel-time cap",
                        "Capacity constraint",
                        "Density assumption (m²/person)",
                        "p (areas opened)",
                        "Method",
                        "ILP engine used",
                        "Convergence status",
                        "Fallback reason",
                        "Solve time (s)",
                        "— Building-count metrics —",
                        "Avg travel time (min)",
                        "Max travel time (min)",
                        "P95 travel time (min, building-count, unweighted)",
                        "Coverage <5 min (%)",
                        "Coverage <10 min (%)",
                        "Coverage <30 min (%)",
                        "Buildings >15 min",
                        "Excellent-access buildings",
                        "— Population-weighted metrics —",
                        "Pop-weighted avg travel time (min)",
                        "P95 travel time (min, population-weighted)",
                        "Pop coverage <5 min (%)",
                        "Pop coverage <10 min (%)",
                        "Pop coverage <30 min (%)",
                        "— Unreachable —",
                        "Unreachable buildings",
                        "Unreachable population",
                        "— Objective value —",
                        "Total weighted travel time",
                    ],
                    "Value": [
                        domain.display_name,
                        st.session_state.get("opt_district", "—"),
                        _summ_mode_label,
                        objective_txt,
                        # Cutoff politikası: walking-time cap kaldırıldı —
                        # tüm bina-alan çiftleri optimizasyona admissible.
                        ("Not applied (all pairs admissible)"
                         if result.max_sure_dk_kisit is None
                         else f"{result.max_sure_dk_kisit} min (legacy)"),
                        "Yes" if result.kapasite_aktif else "No",
                        # Density: sadece capacity ON ise meaningful; OFF iken N/A
                        (f"{st.session_state.get('opt_m2_per_person_used', 1.5):.2f}"
                         if result.kapasite_aktif else "N/A (capacity off)"),
                        result.p,
                        result.yontem,
                        # ILP engine used — CBC / HiGHS / Gurobi / vs.
                        # K-Med yolundan dönen sonuçta None → "N/A".
                        (result.ilp_engine_used.upper()
                         if result.ilp_engine_used else "N/A (K-Medoids)"),
                        # Convergence status — solver tipine göre:
                        #   • K-Med converged → "Converged in N iter(s)"
                        #   • K-Med MAX_ITER → "NOT converged — hit MAX_ITER=N"
                        #   • ILP → "Provably optimal (CBC: <status>)" veya N/A
                        (
                            f"Converged in {result.kmedoids_iterations} iter(s)"
                            if result.kmedoids_converged is True else
                            (
                                f"NOT converged — hit MAX_ITER="
                                f"{result.kmedoids_iterations}"
                                if result.kmedoids_converged is False else
                                (
                                    f"Provably optimal (CBC: {result.ilp_status})"
                                    if result.ilp_status == "Optimal"
                                    else (f"ILP status: {result.ilp_status}"
                                          if result.ilp_status else "—")
                                )
                            )
                        ),
                        # Fallback reason — ILP→K-Med düşüşünün net sebebi
                        # (sadece fallback olduysa dolu). Akademik şeffaflık:
                        # rapor okuyan, "exact" vs "heuristic" ayrımını
                        # Convergence status + Fallback reason ikilisinden
                        # net çıkarır.
                        (result.fallback_nedeni or "—"),
                        round(result.cozum_suresi_sn, 2),
                        "",
                        round(result.ort_sure_dk, 2),
                        round(result.max_sure_dk, 2),
                        round(result.p95_bina_sure_dk, 2),
                        round(result.kapsama_5dk_pct, 1),
                        round(result.kapsama_10dk_pct, 1),
                        round(result.kapsama_30dk_pct, 1),
                        far_count,
                        excellent_count,
                        "",
                        round(result.agirlikli_ort_sure_dk, 2),
                        round(result.p95_sure_dk, 2),
                        round(result.nufus_kapsama_5dk_pct, 1),
                        round(result.nufus_kapsama_10dk_pct, 1),
                        round(result.nufus_kapsama_30dk_pct, 1),
                        "",
                        result.ulasilamaz_sayisi,
                        round(result.ulasilamaz_nufus, 0),
                        "",
                        round(result.toplam_agirlikli_sure, 1),
                    ],
                })
                summary_df.to_excel(writer, sheet_name="1. Summary", index=False)

                # ── 2. Methodology ─────────────────────────────────────
                _meth_mode = st.session_state.get("opt_transport_mode_used", "walk")
                _meth_speed = st.session_state.get("opt_walk_speed_used", "?")
                _meth_network_desc = (
                    f"OSMnx `network_type='drive'` over OpenStreetMap — cached "
                    f"per district. Travel speed: {_meth_speed} km/h (city avg). "
                    f"NOTE: AFAD emergency assembly planning assumes a walking "
                    f"scenario (vehicle use is impractical after an earthquake); "
                    f"driving mode is provided for COMPARATIVE ANALYSIS only."
                ) if _meth_mode == MODE_DRIVE else (
                    f"OSMnx `network_type='walk'` over OpenStreetMap — cached "
                    f"per district. Walking speed: {_meth_speed} km/h (adult "
                    f"pedestrian, AFAD/international decision-support practice)."
                )
                methodology_df = pd.DataFrame({
                    "Step": [
                        "Input data",
                        "Population weight",
                        "Transport network",
                        "OD matrix",
                        "Reachability",
                        "Objective",
                        "Capacity",
                        "Solver",
                        "Termination & convergence",
                        "Reporting",
                    ],
                    "Approach": [
                        "Buildings + assembly areas as point layers (Excel or GeoJSON).",
                        "Per-building population estimate from TÜİK household size × "
                        "dwelling area × net ratio (see Assumptions sheet). "
                        "Assumption: residential buildings only — non-residential "
                        "buildings (commercial / industrial / civic / etc.) are "
                        "over-estimated; UI surfaces a warning if any are detected.",
                        _meth_network_desc,
                        "Reverse-graph Dijkstra from each candidate area to all building "
                        "nodes — NO cutoff applied: all pairs are admissible. Walking "
                        "speed (default 4.8 km/h) is a runtime parameter; the graph "
                        "uses edge `length` and time is derived at compute time.",
                        "Buildings with no path in the pedestrian graph (network "
                        "fragmentation, isolated nodes) appear as +∞ in the OD matrix "
                        "and are reported separately as 'unreachable'. No time-based "
                        "cap is applied — long-walk assignments are reported and "
                        "left to decision-maker judgement.",
                        "Three modes: Min-Sum (Σ wᵢ dᵢⱼ xᵢⱼ) for efficiency, "
                        "Min-Max (min z, z ≥ dᵢⱼ xᵢⱼ) for worst-case fairness, "
                        "or Min-P95 — the population-weighted 95th-percentile "
                        "walking time, an outlier-resistant fairness measure "
                        "recommended for AFAD decision support. "
                        "Min-P95 is non-linear and is solved only by K-Medoids; "
                        "Min-Sum / Min-Max can be solved by either ILP or K-Medoids.",
                        domain.methodology_capacity + (
                            " The 'Compare capacity ON vs OFF' button (Step 3) "
                            "automates side-by-side sensitivity reporting."
                            if domain.show_afad_methodology else ""
                        ),
                        "Auto-selects PuLP + CBC ILP (provably optimal) for "
                        "≤5,000 buildings, otherwise greedy + 1-swap K-Medoids. "
                        "Advanced options let the user force ILP/K-Medoids, "
                        "tune the ILP time limit, and enable/disable the "
                        "ILP→K-Medoids fallback when ILP is infeasible or "
                        "times out.",
                        # Termination & convergence — solver-spesifik kalite
                        # garantileri açıkça belirtilir, akademik şeffaflık
                        # için kritik.
                        "ILP (PuLP/CBC): terminates with one of {Optimal, "
                        "Infeasible, Unbounded, NotSolved (time limit), "
                        "Undefined}. 'Optimal' status means provably "
                        "globally optimal under the formulated constraints. "
                        "K-Medoids: 1-swap local search; terminates when "
                        "no improving swap is found within the neighbourhood "
                        "(certified locally optimal) OR when the iteration "
                        "limit (KMEDOIDS_MAX_ITER, default 200) is reached "
                        "(NOT certified — result is best-found but the "
                        "heuristic may have stalled). Convergence status is "
                        "surfaced in the Summary sheet and the UI banner. "
                        "Multi-start restart is listed as future work.",
                        "Assignments, alternatives, area-level summary, sensitivity and "
                        "unreachable list — all in this workbook.",
                    ],
                })
                methodology_df.to_excel(writer, sheet_name="2. Methodology", index=False)

                # ── 3. Assumptions (population / capacity) ─────────────
                assumptions_table().to_excel(
                    writer, sheet_name="3. Assumptions", index=False
                )

                # ── 4. Assignment Guide ────────────────────────────────
                pd.DataFrame({
                    "Column": [
                        "Building Label", "Assignment", "Assembly Area",
                        "Time (min)", "Time Band", "Access Quality",
                        "Neighborhood", "Weight",
                        "alternatif_1 / _sure", "alternatif_2 / _sure",
                        "alternatif_3 / _sure",
                    ],
                    "Meaning": [
                        "Human-readable building label used in tables and map popups.",
                        "Direct building-to-assembly-area assignment statement.",
                        "Assembly area selected by the model for that building.",
                        "Travel time from the building to its assigned assembly area.",
                        "Travel-time interval used for quick review.",
                        "Interpretation of walking time: Excellent, Good, Acceptable, Far, Very far.",
                        "Neighborhood of the building.",
                        "Demand proxy (estimated population) used by the objective function.",
                        "Next-best alternative area and its walking time (runner-up).",
                        "Second-best alternative area and walking time.",
                        "Third-best alternative area and walking time.",
                    ],
                }).to_excel(writer, sheet_name="4. Assignment Guide", index=False)

                # ── 5. Area Summary ────────────────────────────────────
                to_english(result.alan_ozeti).to_excel(
                    writer, sheet_name="5. Area Summary", index=False
                )

                # ── 6. Readable Assignments (priority columns only) ────
                readable_cols = [
                    "Building Label", "Assignment", "Neighborhood", "Assembly Area",
                    "Time (min)", "Time Band", "Access Quality", "Weight",
                ]
                readable_cols = [c for c in readable_cols if c in atamalar_en.columns]
                atamalar_en[readable_cols].to_excel(
                    writer, sheet_name="6. Readable Assignments", index=False
                )

                # ── 7. Full Assignments (all columns + alternatives) ───
                atamalar_en.to_excel(
                    writer, sheet_name="7. Full Assignments", index=False
                )

                # ── 8. Unreachable Buildings ───────────────────────────
                if not result.ulasilamaz_binalar.empty:
                    to_english(result.ulasilamaz_binalar).to_excel(
                        writer, sheet_name="8. Unreachable", index=False
                    )
                else:
                    pd.DataFrame(
                        [{"Status": "All buildings successfully assigned (no unreachable)."}]
                    ).to_excel(writer, sheet_name="8. Unreachable", index=False)

                # ── 9. Open areas roster ───────────────────────────────
                open_df = pd.DataFrame({
                    "Area ID": result.acik_alanlar,
                    "Assembly Area": result.acik_alan_adlari,
                })
                open_df.to_excel(writer, sheet_name="9. Open Areas", index=False)

                # ── 10. Capacity comparison (only if compare ran) ─────
                # Akademik sensitivity figürü. `opt_compare_results` Step 3'te
                # "Compare capacity ON vs OFF" tıklandıysa populate edilir.
                _cmp_excel = st.session_state.get("opt_compare_results")
                if _cmp_excel is not None:
                    r_off_x = _cmp_excel["off"]
                    r_on_x  = _cmp_excel["on"]

                    def _diff(o, n, prec=1):
                        d = n - o
                        sgn = "+" if d > 0 else ""
                        return f"{sgn}{d:.{prec}f}"

                    cmp_excel_df = pd.DataFrame({
                        "Metric": [
                            "Density assumption (m²/person)",
                            "p (areas opened)",
                            "Objective",
                            "— Travel-time metrics —",
                            "Avg travel time (min)",
                            "Max travel time (min)",
                            "P95 travel time, pop-w. (min)",
                            "Pop-weighted avg time (min)",
                            "— Coverage —",
                            "Coverage <5 min (%)",
                            "Coverage <10 min (%)",
                            "Coverage <30 min (%)",
                            "Pop coverage <5 min (%)",
                            "Pop coverage <10 min (%)",
                            "Pop coverage <30 min (%)",
                            "— Accessibility —",
                            "Unreachable buildings",
                            "Unreachable population",
                            "— Solver —",
                            "Method",
                            "Solve time (s)",
                            "ILP status",
                            "Fallback reason",
                            "— Areas —",
                            "Areas opened (count)",
                            "Areas opened (shared with both)",
                            "Areas opened only in this scenario",
                        ],
                        "Capacity OFF": [
                            "N/A",
                            r_off_x.p,
                            r_off_x.amac,
                            "",
                            f"{r_off_x.ort_sure_dk:.2f}",
                            f"{r_off_x.max_sure_dk:.2f}",
                            f"{r_off_x.p95_sure_dk:.2f}",
                            f"{r_off_x.agirlikli_ort_sure_dk:.2f}",
                            "",
                            f"{r_off_x.kapsama_5dk_pct:.1f}",
                            f"{r_off_x.kapsama_10dk_pct:.1f}",
                            f"{r_off_x.kapsama_30dk_pct:.1f}",
                            f"{r_off_x.nufus_kapsama_5dk_pct:.1f}",
                            f"{r_off_x.nufus_kapsama_10dk_pct:.1f}",
                            f"{r_off_x.nufus_kapsama_30dk_pct:.1f}",
                            "",
                            r_off_x.ulasilamaz_sayisi,
                            f"{getattr(r_off_x, 'ulasilamaz_nufus', 0):,.0f}",
                            "",
                            r_off_x.yontem,
                            f"{r_off_x.cozum_suresi_sn:.1f}",
                            r_off_x.ilp_status or "—",
                            r_off_x.fallback_nedeni or "—",
                            "",
                            len(r_off_x.acik_alan_adlari),
                            len(set(r_off_x.acik_alan_adlari) & set(r_on_x.acik_alan_adlari)),
                            "; ".join(
                                sorted(set(r_off_x.acik_alan_adlari) - set(r_on_x.acik_alan_adlari))
                            ) or "—",
                        ],
                        "Capacity ON": [
                            f"{_cmp_excel['density']:.2f}",
                            r_on_x.p,
                            r_on_x.amac,
                            "",
                            f"{r_on_x.ort_sure_dk:.2f}",
                            f"{r_on_x.max_sure_dk:.2f}",
                            f"{r_on_x.p95_sure_dk:.2f}",
                            f"{r_on_x.agirlikli_ort_sure_dk:.2f}",
                            "",
                            f"{r_on_x.kapsama_5dk_pct:.1f}",
                            f"{r_on_x.kapsama_10dk_pct:.1f}",
                            f"{r_on_x.kapsama_30dk_pct:.1f}",
                            f"{r_on_x.nufus_kapsama_5dk_pct:.1f}",
                            f"{r_on_x.nufus_kapsama_10dk_pct:.1f}",
                            f"{r_on_x.nufus_kapsama_30dk_pct:.1f}",
                            "",
                            r_on_x.ulasilamaz_sayisi,
                            f"{getattr(r_on_x, 'ulasilamaz_nufus', 0):,.0f}",
                            "",
                            r_on_x.yontem,
                            f"{r_on_x.cozum_suresi_sn:.1f}",
                            r_on_x.ilp_status or "—",
                            r_on_x.fallback_nedeni or "—",
                            "",
                            len(r_on_x.acik_alan_adlari),
                            len(set(r_off_x.acik_alan_adlari) & set(r_on_x.acik_alan_adlari)),
                            "; ".join(
                                sorted(set(r_on_x.acik_alan_adlari) - set(r_off_x.acik_alan_adlari))
                            ) or "—",
                        ],
                        "Δ (ON − OFF)": [
                            "—", "—", "—", "",
                            _diff(r_off_x.ort_sure_dk, r_on_x.ort_sure_dk, 2),
                            _diff(r_off_x.max_sure_dk, r_on_x.max_sure_dk, 2),
                            _diff(r_off_x.p95_sure_dk, r_on_x.p95_sure_dk, 2),
                            _diff(r_off_x.agirlikli_ort_sure_dk, r_on_x.agirlikli_ort_sure_dk, 2),
                            "",
                            _diff(r_off_x.kapsama_5dk_pct, r_on_x.kapsama_5dk_pct),
                            _diff(r_off_x.kapsama_10dk_pct, r_on_x.kapsama_10dk_pct),
                            _diff(r_off_x.kapsama_30dk_pct, r_on_x.kapsama_30dk_pct),
                            _diff(r_off_x.nufus_kapsama_5dk_pct, r_on_x.nufus_kapsama_5dk_pct),
                            _diff(r_off_x.nufus_kapsama_10dk_pct, r_on_x.nufus_kapsama_10dk_pct),
                            _diff(r_off_x.nufus_kapsama_30dk_pct, r_on_x.nufus_kapsama_30dk_pct),
                            "",
                            _diff(r_off_x.ulasilamaz_sayisi, r_on_x.ulasilamaz_sayisi, 0),
                            "—", "", "—",
                            _diff(r_off_x.cozum_suresi_sn, r_on_x.cozum_suresi_sn),
                            "—", "—", "",
                            _diff(
                                len(r_off_x.acik_alan_adlari),
                                len(r_on_x.acik_alan_adlari),
                                0,
                            ),
                            "—", "—",
                        ],
                    })
                    cmp_excel_df.to_excel(
                        writer, sheet_name="10. Capacity Comparison", index=False
                    )

            xlsx_bytes = build_styled_workbook(_write_optimization_sheets)
            st.download_button(
                "⬇️ Download Excel",
                data=xlsx_bytes,
                file_name=f"optimization_p{result.p}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="opt_dl_xlsx",
                width="stretch",
            )
            _has_cmp_sheet = st.session_state.get("opt_compare_results") is not None
            _sheet_count = "10 sheets" if _has_cmp_sheet else "9 sheets"
            _cmp_suffix = " · Capacity Comparison" if _has_cmp_sheet else ""
            st.caption(
                f"{_sheet_count}: Summary · Methodology · Assumptions · "
                f"Assignment Guide · Area Summary · Readable Assignments · "
                f"Full Assignments · Unreachable · Open Areas{_cmp_suffix}"
            )
        except Exception as e:
            st.warning(f"Excel export failed: {e}")

    # ── Process log ─────────────────────────────────────────────────────────
    with st.expander("🔍 Process log"):
        if st.session_state.opt_logs:
            # P2-01 escape: log mesajları pipeline'dan (OSM service, exception
            # text, fizibilite uyarısı) gelir → HTML render'da escape zorunlu.
            # Bir OSM hata mesajı `<RouteResponseError>` içerebilir; escape
            # olmazsa hem layout bozulur hem teorik XSS vektörü.
            import html as _html
            _safe_lines = "<br>".join(
                f"• {_html.escape(str(m))}"
                for m in st.session_state.opt_logs
            )
            st.markdown(
                '<div style="background:#0F172A;color:#E2E8F0;padding:1rem;'
                'border-radius:10px;font-family:ui-monospace,monospace;'
                'font-size:0.8125rem;line-height:1.6;max-height:300px;overflow:auto">'
                + _safe_lines +
                "</div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("No log entries yet.")


# ════════════════════════════════════════════════════════════════════════════
# EMPTY STATE (no data loaded)
# ════════════════════════════════════════════════════════════════════════════
if not _have("opt_buildings"):
    cards.divider()
    cards.empty_state(
        title="Waiting for input data",
        text="Upload a buildings layer and an assembly-areas layer above to "
             "begin. You can feed the Excel output of the Data Extraction tool "
             "directly into this optimizer.",
        icon="📥",
    )


cards.footer()
