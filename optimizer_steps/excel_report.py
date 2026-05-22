"""
optimizer_steps/excel_report.py — Optimization result Excel raporu.

Sprint 2 #8 ilk extraction: önceden Optimization_Tool.py içinde 415 satırlık
inner function (`_write_optimization_sheets`) olarak duruyordu. Stand-alone
modüle çekildi:

  • Test edilebilir (Streamlit context dışında pure-function)
  • Sheet eklemek için inner-function navigasyonu gerekmiyor
  • Optimization_Tool.py ~415 satır küçüldü

Streamlit ile entegrasyon: `st.session_state`'e doğrudan erişiyor (transport
mode/speed, m²/person used, K-Med restarts/seed, compare results). Bu
session-state bağımlılıkları çağrı yerinde dataclass'a çekilebilir ama şu
an basit bırakıldı — Streamlit içinde her zaman çalışacak.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from components.domain_config import DomainConfig
from components.translations import to_english
from src.optimizer.od_matrix import MODE_DRIVE
from src.optimizer.p_median import PMedianResult
from src.optimizer.population_estimator import assumptions_table


def write_optimization_sheets(
    writer: pd.ExcelWriter,
    *,
    result: PMedianResult,
    domain: DomainConfig,
    objective_txt: str,
    far_count: int,
    excellent_count: int,
    atamalar_en: pd.DataFrame,
) -> None:
    """
    9 veya 10 sayfalık Excel raporu yazar (capacity-compare çalıştıysa
    10. sayfa Capacity Comparison).

    Parameters
    ----------
    writer : pd.ExcelWriter
        Çağıran tarafından açılmış writer (genelde build_styled_workbook
        callback'i içinde).
    result : PMedianResult
        Birincil optimization sonucu (capacity ON varyantı ise compare
        çalıştırılmışsa).
    domain : DomainConfig
        Sidebar use-case seçimi (Earthquake / Custom). Hero subtitle ve
        methodology paragrafları için kullanılır.
    objective_txt : str
        Hedef fonksiyonun insanca adı (örn. "Min-Sum (efficiency)").
    far_count, excellent_count : int
        Step 4'te hesaplanan bina-sayısı metrikleri.
    atamalar_en : pd.DataFrame
        EN translasyonu yapılmış atamalar tablosu (Step 4'te hazırlanmış).
    """

    # ── 1. Executive Summary ────────────────────────────────────────────
    # P95 düzeltmesi: Building-count grubunda bina-bazlı (ağırlıksız) p95;
    # Population-weighted grubunda nüfus-ağırlıklı p95. Etiketler hangi
    # metriğin hangi ağırlık mantığını kullandığını açıkça gösterir.
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
            "K-Medoids restarts",
            "K-Medoids random seed",
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
            ("Not applied (all pairs admissible)"
             if result.max_sure_dk_kisit is None
             else f"{result.max_sure_dk_kisit} min (legacy)"),
            "Yes" if result.kapasite_aktif else "No",
            (f"{st.session_state.get('opt_m2_per_person_used', 1.5):.2f}"
             if result.kapasite_aktif else "N/A (capacity off)"),
            result.p,
            result.yontem,
            (result.ilp_engine_used.upper()
             if result.ilp_engine_used else "N/A (K-Medoids)"),
            int(st.session_state.get("opt_kmed_n_restarts", 1)),
            (
                str(st.session_state.get("opt_kmed_seed_value", ""))
                if st.session_state.get("opt_kmed_seed_enabled", False)
                else "(unseeded)"
            ),
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

    # ── 2. Methodology ─────────────────────────────────────────────────
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
            "Multi-start restart is now exposed as an option "
            "(Advanced K-Medoids options).",
            "Assignments, alternatives, area-level summary, sensitivity and "
            "unreachable list — all in this workbook.",
        ],
    })
    methodology_df.to_excel(writer, sheet_name="2. Methodology", index=False)

    # ── 3. Assumptions (population / capacity) ─────────────────────────
    assumptions_table().to_excel(
        writer, sheet_name="3. Assumptions", index=False
    )

    # ── 4. Assignment Guide ────────────────────────────────────────────
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

    # ── 5. Area Summary ────────────────────────────────────────────────
    to_english(result.alan_ozeti).to_excel(
        writer, sheet_name="5. Area Summary", index=False
    )

    # ── 6. Readable Assignments (priority columns only) ────────────────
    readable_cols = [
        "Building Label", "Assignment", "Neighborhood", "Assembly Area",
        "Time (min)", "Time Band", "Access Quality", "Weight",
    ]
    readable_cols = [c for c in readable_cols if c in atamalar_en.columns]
    atamalar_en[readable_cols].to_excel(
        writer, sheet_name="6. Readable Assignments", index=False
    )

    # ── 7. Full Assignments (all columns + alternatives) ───────────────
    atamalar_en.to_excel(
        writer, sheet_name="7. Full Assignments", index=False
    )

    # ── 8. Unreachable Buildings ───────────────────────────────────────
    if not result.ulasilamaz_binalar.empty:
        to_english(result.ulasilamaz_binalar).to_excel(
            writer, sheet_name="8. Unreachable", index=False
        )
    else:
        pd.DataFrame(
            [{"Status": "All buildings successfully assigned (no unreachable)."}]
        ).to_excel(writer, sheet_name="8. Unreachable", index=False)

    # ── 9. Open areas roster ───────────────────────────────────────────
    open_df = pd.DataFrame({
        "Area ID": result.acik_alanlar,
        "Assembly Area": result.acik_alan_adlari,
    })
    open_df.to_excel(writer, sheet_name="9. Open Areas", index=False)

    # ── 10. Capacity comparison (only if compare ran) ─────────────────
    _cmp_excel = st.session_state.get("opt_compare_results")
    if _cmp_excel is not None:
        _write_capacity_compare_sheet(writer, _cmp_excel)


def _write_capacity_compare_sheet(
    writer: pd.ExcelWriter,
    cmp_results: dict,
) -> None:
    """10. Capacity Comparison sheet — capacity ON vs OFF yan yana KPI."""
    r_off_x = cmp_results["off"]
    r_on_x = cmp_results["on"]

    def _diff(o, n, prec: int = 1) -> str:
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
            f"{cmp_results['density']:.2f}",
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
