"""
optimizer_steps/step4_results.py — Step 4: Results render.

Sprint 2 #8 (phase 2): 642-line Step 4 block extracted from Optimization_Tool.py
into a standalone `render_step4_results()` function. Reads everything from
`st.session_state` (opt_result, opt_compare_results, opt_transport_mode_used,
etc.); writes nothing to session except via download buttons.

Behaviour is byte-for-byte identical to the inline version. Function takes
the active `domain` config as parameter so the same Streamlit context can
reuse it.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from components import cards
from components.domain_config import DomainConfig
from components.signatures import ResultSignature, coerce_signature, signature_diff
from components.styles import TOKENS
from components.translations import to_english
from src.logger import get_logger
from src.optimizer.od_matrix import MODE_DRIVE
from src.optimizer.p_median import PMedianResult

log = get_logger(__name__)


def render_step4_results(domain: DomainConfig) -> None:
    """
    Step 4 — Results: stale-banner, KPI cards, charts, building detail,
    capacity-compare display, downloads (CSV + Excel). Caller must have
    `st.session_state.opt_result` populated; this function early-returns
    if not (callers protect with `if _have("opt_result"):`).
    """
    if not st.session_state.get("opt_result"):
        return

    result: PMedianResult = st.session_state.opt_result

    # Stale-result banner (Step 3 sonrası parametre değişti mi?).
    # Typed ResultSignature kullanıyoruz; eski tuple session'lar
    # coerce_signature ile geriye uyumlu parse edilir.
    # signature_diff insancıl format string'leri döner — alan başına
    # eski/yeni değerleri okunabilir biçimde gösterir.
    _res_sig = coerce_signature(
        st.session_state.get("opt_result_signature"), ResultSignature
    )
    _current_res_sig = coerce_signature(
        st.session_state.get("opt_current_inputs"), ResultSignature
    )
    _diff = signature_diff(_res_sig, _current_res_sig)
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

    # atamalar_en'i erken hazırlıyoruz — hem histogram/CDF chart'ları hem de
    # aşağıdaki Building assignments bölümü kullanacak. EN translation cache'li
    # olduğu için iki kez çağırmak masraflı değil ama kod okunabilirliği için
    # tek noktada üretmek daha temiz.
    atamalar_en = to_english(result.atamalar)

    # ── F3 + F4: Walking-time distribution + Population coverage CDF ──────
    # Sprint 3 (academic visualization push): tek bir KPI üçlüsü yerine
    # erişim kalitesinin TÜM dağılımını gösteren histogram + kümülatif
    # eğri. Tez raporu Figure 5.2 + 5.3 olarak kullanılır.
    if "Time (min)" in atamalar_en.columns and len(atamalar_en) > 0:
        try:
            import numpy as _np
            import plotly.graph_objects as go

            _times = atamalar_en["Time (min)"].dropna().astype(float).values
            _weights = (
                atamalar_en["Weight"].dropna().astype(float).values
                if "Weight" in atamalar_en.columns
                else _np.ones_like(_times)
            )

            if len(_times) > 0:
                cards.section_title(
                    "Travel-time distribution",
                    "Histogram of building travel times (left) and the "
                    "cumulative population coverage curve (right). The shaded "
                    "thresholds at 5 / 10 / 30 min mark AFAD reference bands.",
                )
                cc1, cc2 = st.columns(2, gap="medium")

                # F3 — Walking time histogram (buildings + population overlay)
                with cc1:
                    fig_hist = go.Figure()
                    # Bina sayısı (count) histogramı
                    fig_hist.add_trace(go.Histogram(
                        x=_times,
                        xbins=dict(start=0, end=max(60, float(_np.max(_times)) + 5), size=2.5),
                        marker_color=TOKENS["accent"],
                        opacity=0.75,
                        name="Buildings",
                        hovertemplate="Bin: %{x} min<br>%{y} buildings<extra></extra>",
                    ))
                    # AFAD eşik çizgileri (5/10/30 dk)
                    for thr, label, color in [
                        (5,  "5 min",  TOKENS["success"]),
                        (10, "10 min", TOKENS["warning"]),
                        (30, "30 min", TOKENS["danger"]),
                    ]:
                        fig_hist.add_vline(
                            x=thr, line_dash="dot", line_color=color,
                            annotation_text=label,
                            annotation_position="top",
                        )
                    fig_hist.update_layout(
                        title="Building count by travel-time bin",
                        font=dict(family="Inter, sans-serif", color=TOKENS["text"]),
                        plot_bgcolor="white",
                        paper_bgcolor="white",
                        height=380,
                        margin=dict(l=20, r=20, t=50, b=40),
                        xaxis=dict(title="Travel time (min)",
                                   gridcolor="#F1F5F9", linecolor="#E2E8F0"),
                        yaxis=dict(title="Number of buildings",
                                   gridcolor="#F1F5F9", linecolor="#E2E8F0"),
                        showlegend=False,
                    )
                    st.plotly_chart(fig_hist, width="stretch")

                # F4 — Population coverage CDF
                with cc2:
                    # Ağırlıklı CDF: sürelere göre sırala, ağırlıkları kümülatif
                    # topla, toplam ağırlıkla normalize et → 0-100%
                    order = _np.argsort(_times)
                    t_sorted = _times[order]
                    w_sorted = _weights[order]
                    tot_w = float(w_sorted.sum())
                    cum_pct = (
                        _np.cumsum(w_sorted) / tot_w * 100.0
                        if tot_w > 0 else _np.zeros_like(w_sorted)
                    )

                    fig_cdf = go.Figure()
                    fig_cdf.add_trace(go.Scatter(
                        x=t_sorted, y=cum_pct,
                        mode="lines",
                        line=dict(color=TOKENS["accent"], width=2.5),
                        fill="tozeroy",
                        fillcolor="rgba(37, 99, 235, 0.10)",
                        name="Cumulative pop. coverage",
                        hovertemplate="≤ %{x:.1f} min<br>%{y:.1f}% population<extra></extra>",
                    ))
                    for thr, label, color in [
                        (5,  "5 min",  TOKENS["success"]),
                        (10, "10 min", TOKENS["warning"]),
                        (30, "30 min", TOKENS["danger"]),
                    ]:
                        fig_cdf.add_vline(
                            x=thr, line_dash="dot", line_color=color,
                            annotation_text=label,
                            annotation_position="top",
                        )
                    fig_cdf.update_layout(
                        title="Cumulative population coverage (%)",
                        font=dict(family="Inter, sans-serif", color=TOKENS["text"]),
                        plot_bgcolor="white",
                        paper_bgcolor="white",
                        height=380,
                        margin=dict(l=20, r=20, t=50, b=40),
                        xaxis=dict(title="Travel time (min)",
                                   gridcolor="#F1F5F9", linecolor="#E2E8F0"),
                        yaxis=dict(title="Population covered (%)",
                                   range=[0, 105],
                                   gridcolor="#F1F5F9", linecolor="#E2E8F0"),
                        showlegend=False,
                    )
                    st.plotly_chart(fig_cdf, width="stretch")

                st.caption(
                    "💡 Tip: Use the camera icon in the chart toolbar to export "
                    "each plot as PNG for inclusion in your report."
                )
        except ImportError:
            # Plotly yoksa sessiz geç — coverage bar chart zaten yukarıda gösterilmişti
            pass

    # ── Area-level summary ──────────────────────────────────────────────────
    cards.section_title("Area-level summary")
    alan_en = to_english(result.alan_ozeti)
    st.dataframe(alan_en, width="stretch", hide_index=True, height=360)

    # ── Building assignment explorer ────────────────────────────────────────
    # atamalar_en yukarıda zaten oluşturuldu (yeniden çağırmaya gerek yok).
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

            from src.optimizer.map_renderer import render_atama_haritasi

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
            from optimizer_steps.excel_report import write_optimization_sheets
            from src.services.excel_utils import build_styled_workbook

            # Eski 415-satırlık inner function optimizer_steps/excel_report.py'a
            # taşındı. Burada kalan kabuk: locals'u kwarg olarak forward eder.
            def _write_optimization_sheets(writer: pd.ExcelWriter) -> None:
                write_optimization_sheets(
                    writer,
                    result=result,
                    domain=domain,
                    objective_txt=objective_txt,
                    far_count=far_count,
                    excellent_count=excellent_count,
                    atamalar_en=atamalar_en,
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

