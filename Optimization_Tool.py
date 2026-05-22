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
from components.signatures import (
    ODSignature,
    ResultSignature,
    coerce_signature,
    signature_diff,
)
from components.styles import TOKENS, configure_page
from components.translations import to_english
from optimizer_steps.step1_data import render_step1_data
from optimizer_steps.step4_results import render_step4_results
from src.config.settings import CACHE_DIR, ISTANBUL_ILCELER
from src.logger import get_logger
from src.optimizer.od_matrix import (
    DEFAULT_SPEED_KPH,
    MODE_DRIVE,
    MODE_WALK,
    compute_od_matrix,
    compute_od_matrix_haversine,
    get_graph,
    validate_graph,
)
from src.optimizer.p_median import coz, duyarlilik_analizi

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
render_step1_data(domain)

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
                    # üretildiğini bir signature'da tut. Tipli dataclass
                    # (eskiden tuple'du; alan eklendikçe len()-bazlı
                    # backward-compat patches yığılıyordu — audit 3.3).
                    st.session_state["opt_od_signature"] = ODSignature(
                        district=st.session_state.opt_district,
                        mode=mode,
                        speed_kph=float(travel_speed),
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
        # Stale-result banner: OD hesaplandığı andaki signature ile UI'daki
        # güncel değerleri karşılaştır (typed ODSignature, eski tuple'lar
        # coerce_signature ile parse edilir).
        _od_sig = coerce_signature(
            st.session_state.get("opt_od_signature"), ODSignature
        )
        _current_sig = ODSignature(
            district=st.session_state.opt_district,
            mode=mode,
            speed_kph=float(travel_speed),
        )
        _changes = signature_diff(_od_sig, _current_sig)
        if _changes:
            st.warning(
                "⚠ **OD matrix is stale.** Parameters changed: "
                + ", ".join(_changes)
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
        # Typed ResultSignature kullanıyoruz (eski tuple'lar coerce edilir).
        # K-Med fields'leri session_state.get ile okuyoruz çünkü Advanced
        # expander bu satırdan sonra render oluyor.
        _live_density = float(m2_per_person) if capacity else None
        _live_n_restarts = int(st.session_state.get("opt_kmed_n_restarts", 1))
        _live_seed: int | None = None
        if st.session_state.get("opt_kmed_seed_enabled", False):
            _live_seed = int(st.session_state.get("opt_kmed_seed_value", 42))
        st.session_state["opt_current_inputs"] = ResultSignature(
            p=int(p),
            amac=amac,
            capacity=bool(capacity),
            solver_mode=solver_mode,
            m2_per_person=_live_density,
            n_restarts=_live_n_restarts,
            random_state=_live_seed,
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

        # ── Gelişmiş: K-Medoids detayları (multi-start + stable seed) ──
        # Sprint 2 #14 + #20: heuristic kalitesini artırmak ve tez figürlerini
        # reprodüklenebilir kılmak için iki yeni kontrol.
        with st.expander("⚙️ Advanced K-Medoids options"):
            kmed_n_restarts = st.number_input(
                "Multi-start restarts (n_restarts)",
                min_value=1,
                max_value=20,
                value=1,
                step=1,
                key="opt_kmed_n_restarts",
                help=(
                    "How many independent K-Medoids runs to perform. The "
                    "first restart uses the deterministic greedy initialization "
                    "(backward-compatible); the remaining N−1 restarts seed "
                    "from a random first medoid. The best (lowest cost) "
                    "result is returned.\n\n"
                    "• **1** (default) — single-shot, fastest, may stick in "
                    "local optima.\n"
                    "• **3–5** — recommended for academic-quality results; "
                    "tradeoff is 3–5× slower runtime.\n"
                    "• **10+** — extensive search, useful for tough plateau "
                    "instances."
                ),
                disabled=(solver_mode == "ilp"),
            )
            _kmed_seed_enabled = st.checkbox(
                "Pin random seed (reproducible results)",
                value=False,
                key="opt_kmed_seed_enabled",
                help=(
                    "When enabled, the multi-start restarts use a fixed seed "
                    "so the same problem produces the same result run after "
                    "run. Useful for thesis figures and academic comparison. "
                    "Default is OFF (system random)."
                ),
                disabled=(solver_mode == "ilp") or (int(kmed_n_restarts) <= 1),
            )
            kmed_random_state: int | None = None
            if _kmed_seed_enabled and int(kmed_n_restarts) > 1:
                kmed_random_state = int(st.number_input(
                    "Seed value",
                    min_value=0,
                    max_value=2**31 - 1,
                    value=42,
                    step=1,
                    key="opt_kmed_seed_value",
                    help="Any non-negative integer; default 42.",
                ))

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
                            n_restarts=int(kmed_n_restarts),
                            random_state=kmed_random_state,
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
                        n_restarts=int(kmed_n_restarts),
                        random_state=kmed_random_state,
                        ilp_engine=ilp_engine,
                    )
                    st.session_state.opt_result = result
                    # Kullanılan yoğunluğu kaydet — Excel + report için
                    st.session_state["opt_m2_per_person_used"] = (
                        float(m2_per_person) if capacity else None
                    )
                    # Stale-banner: Step 3 sonucu için typed signature kaydet.
                    # Kullanıcı sonra p / amac / capacity / solver / density /
                    # K-Med restarts/seed değiştirirse Step 4'te uyarı.
                    st.session_state["opt_result_signature"] = ResultSignature(
                        p=int(p),
                        amac=amac,
                        capacity=bool(capacity),
                        solver_mode=solver_mode,
                        m2_per_person=(float(m2_per_person) if capacity else None),
                        n_restarts=int(kmed_n_restarts),
                        random_state=kmed_random_state,
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
                            n_restarts=int(kmed_n_restarts),
                            random_state=kmed_random_state,
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
                            n_restarts=int(kmed_n_restarts),
                            random_state=kmed_random_state,
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
                        st.session_state["opt_result_signature"] = ResultSignature(
                            p=int(p),
                            amac=amac,
                            capacity=True,
                            solver_mode=solver_mode,
                            m2_per_person=float(m2_per_person),
                            n_restarts=int(kmed_n_restarts),
                            random_state=kmed_random_state,
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Comparison failed: {e}")
                        log.exception("Capacity comparison error")


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
