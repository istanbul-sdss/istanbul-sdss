"""
optimizer_steps/step2_od.py — Step 2: OD matrix computation.

Sprint 2 #8 (phase 4): 378-line Step 2 block (district picker, transport
mode + speed controls, walking-graph download / cache, Dijkstra OD matrix
computation, Haversine fallback, post-compute stale signature) extracted
from Optimization_Tool.py into a standalone `render_step2_od()` function.

Behaviour byte-for-byte identical to the inline version. Reads
opt_buildings / opt_assembly / opt_district from session_state; writes
opt_od_matrix / opt_od_mode / opt_transport_mode_used / opt_walk_speed_used
/ opt_od_signature.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from components import cards
from components.domain_config import DomainConfig
from components.signatures import ODSignature, coerce_signature, signature_diff
from optimizer_steps._common import _have, log_cb  # noqa: E402,F401
from src.config.settings import ISTANBUL_ILCELER
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

log = get_logger(__name__)


def _cached_graph(ilce: str, mode: str = MODE_WALK, force_download: bool = False):
    """get_graph wrapper'ı — Streamlit cache'i bu seviyede tutar."""
    return get_graph(ilce, mode=mode, force_download=force_download)


def render_step2_od(domain: DomainConfig) -> None:
    """
    Step 2 — OD matrix: district picker + transport mode + speed +
    "Compute OD matrix" button + post-compute stale signature.
    Reads opt_buildings; writes opt_od_matrix + supporting metadata.
    """
    if not _have("opt_buildings"):
        return

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


