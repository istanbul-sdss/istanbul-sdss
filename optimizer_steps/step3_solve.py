"""
optimizer_steps/step3_solve.py — Step 3: Optimization.

Sprint 2 #8 (phase 5, final): 656-line Step 3 block (solver inputs,
solver mode, advanced ILP options, advanced K-Medoids options, run
button, sensitivity analysis, capacity ON/OFF compare) extracted
from Optimization_Tool.py.

This was the largest and most-shared-state phase: ~15 local variables
(p, amac, capacity, solver_mode, m2_per_person, kmed_n_restarts,
kmed_random_state, ilp_engine, time_limit_sn, ilp_unlimited,
allow_fallback, effective_time_limit, max_walk_cap, enforce_cap,
n_building, n_area) lived in this scope. None of them are read by
Step 4; cross-step communication is purely via session_state.

Behaviour byte-for-byte identical to the inline version.
"""
from __future__ import annotations

import streamlit as st

from components import cards
from components.domain_config import DomainConfig
from components.signatures import ResultSignature
from components.styles import TOKENS
from components.translations import to_english
from src.logger import get_logger
from src.optimizer.p_median import (
    ILP_THRESHOLD,
    ILP_TIME_LIMIT_SN,
    coz,
    duyarlilik_analizi,
)

log = get_logger(__name__)


def _have(key: str) -> bool:
    return st.session_state.get(key) is not None


def log_cb(msg: str) -> None:
    """Progress callback: log + UI session log paneli."""
    log.info(msg)
    if "opt_logs" not in st.session_state:
        st.session_state["opt_logs"] = []
    st.session_state.opt_logs.append(msg)


def render_step3_solve(domain: DomainConfig) -> None:
    """
    Step 3 — Optimization: solver inputs + advanced ILP/K-Med options +
    Run + Sensitivity + Capacity ON/OFF compare. Reads opt_od_matrix +
    opt_buildings + opt_assembly from session; writes opt_result +
    opt_compare_results + signatures.
    """
    if not _have("opt_od_matrix"):
        return

    cards.section_title(
        "3 · P-Median optimization",
        "Select the number of assembly areas to open and (optionally) enforce "
        "capacity. The solver auto-picks ILP or K-Medoids by problem size.",
    )

    n_area     = len(st.session_state.opt_assembly)
    n_building = len(st.session_state.opt_buildings)

    # ── Solver sabitlerini erkenden import et (UI'da ihtiyaç var) ────────

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
            # Aralık 0.1 - 1000 m²/kişi. AFAD pratiği 1.5 ama hocaların
            # tartıştığı 2.5, fairness-yoğun emergency 1.0, lüks (m²/villa)
            # 100+ gibi senaryolar için tek üst sınır koymuyoruz. Step=0.1
            # küçük ayar için yeterli; büyük değerleri kullanıcı doğrudan
            # input'a yazabilir.
            m2_per_person = st.number_input(
                domain.capacity_method_label,
                min_value=0.1,
                max_value=1000.0,
                value=float(_AFAD_DEFAULT),
                step=0.1,
                key="opt_m2_per_person",
                help=(
                    f"{domain.capacity_method_help_short}\n\n"
                    + (
                        "**Common reference values (AFAD context):**\n"
                        "• **1.0** — high-density emergency (short-term, max coverage)\n"
                        "• **1.5** — AFAD assembly standard (default)\n"
                        "• **2.5** — AFAD long-term shelter standard (more comfort)\n"
                        "• **5–10** — open-park spacing with tents / mid-term shelter\n"
                        "• **>10** — research / sensitivity / hypothetical scenarios\n\n"
                        if domain.show_afad_methodology
                        else "Default 1.5 is the AFAD value; tune to your domain "
                             "(students/classroom, beds/m², etc.).\n\n"
                    )
                    + "Any positive value is accepted (0.1 ≤ density ≤ 1000). "
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

        # ── Compare: Density sensitivity sweep (F5) ─────────────────────────
        # Visualization sprint: AFAD reference yoğunluklarını yan yana
        # karşılaştır. ρ = 1.0 (acil), 1.5 (default), 2.5 (uzun süreli
        # barınma), 5.0 (geniş park). Aynı p ve hedef altında 4 çözüm.
        # Sonuç: KPI tablosu + bar chart. Tez raporu Figure 5.5.
        with st.expander("📐 Compare densities (ρ sweep — advanced)"):
            st.markdown(
                "Run the same problem with **four AFAD reference density "
                "values** (1.0, 1.5, 2.5, 5.0 m²/person) — all with capacity "
                "ON. The result is a KPI table + bar chart showing how the "
                "density assumption shifts unreachable count and travel-time "
                "metrics. Useful for the thesis density-sensitivity figure."
            )
            sweep_disabled = not area_available
            if sweep_disabled:
                st.info(
                    "Density sweep requires assembly-area m² data — "
                    "currently unavailable."
                )
            if st.button(
                "🔬 Run density sweep (4 solves)",
                key="opt_btn_density_sweep",
                disabled=sweep_disabled or invalid_combo,
                width="stretch",
            ):
                st.session_state.opt_logs = []
                sweep_densities = [1.0, 1.5, 2.5, 5.0]
                sweep_progress = st.progress(0.0)
                sweep_status = st.empty()
                sweep_results: list = []
                try:
                    from src.optimizer.population_estimator import (
                        estimate_capacity_afad,
                    )
                    for i_d, rho in enumerate(sweep_densities):
                        sweep_status.info(
                            f"Solving for **ρ = {rho:.1f} m²/person** "
                            f"({i_d + 1}/{len(sweep_densities)})…"
                        )
                        a_rho = st.session_state.opt_assembly
                        if "area_m2" in a_rho.columns:
                            a_rho = a_rho.copy()
                            a_rho["kapasite"] = estimate_capacity_afad(
                                a_rho["area_m2"],
                                m2_per_person=float(rho),
                            )
                        r_rho = coz(
                            st.session_state.opt_od_matrix,
                            st.session_state.opt_buildings,
                            a_rho,
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
                        sweep_results.append({"density": float(rho), "result": r_rho})
                        sweep_progress.progress((i_d + 1) / len(sweep_densities))
                    sweep_status.success(
                        f"✅ Density sweep complete ({len(sweep_densities)} runs). "
                        f"Scroll to **Step 4 → Density sensitivity** for the table + chart."
                    )
                    st.session_state["opt_density_sweep"] = {
                        "p": int(p),
                        "amac": amac,
                        "runs": sweep_results,
                    }
                    st.rerun()
                except Exception as e:
                    sweep_progress.empty()
                    sweep_status.empty()
                    st.error(f"Density sweep failed: {e}")
                    log.exception("Density sweep error")

        # ── Benchmark: ILP engine runtime comparison (F8) ───────────────────
        # Visualization sprint: kurulu tüm ILP solver'ları aynı problemde
        # çalıştır, runtime karşılaştırması yap. Sonuç: tez raporu
        # Methodology / Computational Results bölümünde tablo olarak
        # kullanılabilir ("CBC X ms, HiGHS Y ms, CPLEX Z ms").
        with st.expander("⏱ Benchmark ILP engines (advanced)"):
            _avail = list_available_ilp_engines()
            _avail_keys = [k for k, _ in _avail]
            if len(_avail_keys) <= 1:
                st.info(
                    "Only one ILP engine detected on this machine "
                    f"({_avail_keys[0].upper() if _avail_keys else 'none'}). "
                    "Install HiGHS (`pip install highspy`), Gurobi, CPLEX, or "
                    "SCIP to enable side-by-side benchmarking."
                )
            else:
                st.markdown(
                    f"Run the same problem (p={p}, objective={amac}, "
                    f"{'capacity ON' if capacity else 'capacity OFF'}) with "
                    f"**all {len(_avail_keys)} installed ILP engines** and "
                    f"compare runtime + objective value. Useful for the "
                    f"thesis Solution Method section."
                )
                if st.button(
                    f"🏁 Benchmark {len(_avail_keys)} engines",
                    key="opt_btn_engine_bench",
                    disabled=invalid_combo,
                    width="stretch",
                ):
                    st.session_state.opt_logs = []
                    bench_progress = st.progress(0.0)
                    bench_status = st.empty()
                    bench_results: list = []
                    try:
                        # Capacity reuse: aynı density ile kapasite ON ise GDF
                        # bir kez hazırlanır.
                        a_bench = st.session_state.opt_assembly
                        if capacity and "area_m2" in a_bench.columns:
                            from src.optimizer.population_estimator import (
                                estimate_capacity_afad,
                            )
                            a_bench = a_bench.copy()
                            a_bench["kapasite"] = estimate_capacity_afad(
                                a_bench["area_m2"],
                                m2_per_person=float(m2_per_person),
                            )
                        for i_e, eng_key in enumerate(_avail_keys):
                            bench_status.info(
                                f"Solving with **{eng_key.upper()}** "
                                f"({i_e + 1}/{len(_avail_keys)})…"
                            )
                            r_eng = coz(
                                st.session_state.opt_od_matrix,
                                st.session_state.opt_buildings,
                                a_bench,
                                p=int(p),
                                kapasite=capacity,
                                max_sure_dk=None,
                                amac=amac,
                                progress_cb=log_cb,
                                solver="ilp",   # ZORLA ILP — benchmark ILP'ler için
                                time_limit_sn=effective_time_limit,
                                unlimited=ilp_unlimited,
                                allow_fallback=False,   # düşmesin, gerçek timing alalım
                                n_restarts=1,           # ILP için multi-start anlamsız
                                random_state=None,
                                ilp_engine=eng_key,
                            )
                            bench_results.append({
                                "engine": eng_key,
                                "result": r_eng,
                            })
                            bench_progress.progress((i_e + 1) / len(_avail_keys))
                        bench_status.success(
                            f"✅ Engine benchmark complete ({len(_avail_keys)} runs). "
                            f"See **Step 4 → Engine benchmark** for the table."
                        )
                        st.session_state["opt_engine_benchmark"] = {
                            "p": int(p),
                            "amac": amac,
                            "capacity": bool(capacity),
                            "runs": bench_results,
                        }
                        st.rerun()
                    except Exception as e:
                        bench_progress.empty()
                        bench_status.empty()
                        st.error(
                            f"Benchmark failed (check that all engines accept "
                            f"this problem; fallback was disabled): {e}"
                        )
                        log.exception("Engine benchmark error")


