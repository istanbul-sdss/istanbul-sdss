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

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from components import cards
from components.domain_config import DEFAULT_DOMAIN_KEY, DOMAINS, get_domain
from components.styles import configure_page
from optimizer_steps.step1_data import render_step1_data
from optimizer_steps.step2_od import render_step2_od
from optimizer_steps.step3_solve import render_step3_solve
from optimizer_steps.step4_results import render_step4_results
from src.config.settings import CACHE_DIR
from src.logger import get_logger
from src.optimizer.od_matrix import (
    MODE_WALK,
    get_graph,
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
    # Sprint 1.5 audit #4.9: önceki sürüm Reset session'da bu 3 key'i
    # temizlemiyordu → yeni run'da hayalet karşılaştırma/sweep/benchmark
    # gözüküyordu. Şimdi reset bunları da temizler.
    "opt_compare_results":  None,   # capacity ON vs OFF compare results
    "opt_density_sweep":    None,   # F5 density sensitivity sweep results
    "opt_engine_benchmark": None,   # F8 ILP engine benchmark results
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


# Audit 4.1: shared helpers; eskiden bu modülde + 3 step modülünde tekrar
# tekrar tanımlanmıştı (DRY ihlali).
from optimizer_steps._common import _have, log_cb  # noqa: E402,F401

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
        # Audit 4.5: Büyük cache (~10 GB) silmek dakikalar sürebilir.
        # Spinner olmadan UI dondu görünüyordu → kullanıcıya görünür ilerleme.
        with st.spinner(f"Clearing {_target}…"):
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
render_step1_data(domain)

# ════════════════════════════════════════════════════════════════════════════
# STEP 2 — OD MATRIX
# ════════════════════════════════════════════════════════════════════════════
render_step2_od(domain)

# ════════════════════════════════════════════════════════════════════════════
# STEP 3 — OPTIMIZATION
# ════════════════════════════════════════════════════════════════════════════
render_step3_solve(domain)

# ════════════════════════════════════════════════════════════════════════════
# STEP 4 — RESULTS
# ════════════════════════════════════════════════════════════════════════════
# Tüm Step 4 mantığı optimizer_steps/step4_results.py'a taşındı
# (Sprint 2 #8 phase 2): KPI cards, charts, building detail, capacity-
# compare display, downloads. Bu modül session_state'ten okuyor; domain
# config'i sidebar selection'dan parametre olarak alıyor.
if _have("opt_result"):
    render_step4_results(domain)


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
