"""
tools/generate_chapter4_figures.py

Bölüm 4 — System Design and Methodology için iki SVG figür üretir:
    figures/figure_4_1_sdss_architecture.svg
    figures/figure_4_2_optimization_workflow.svg

Kullanım:
    python tools/generate_chapter4_figures.py

SVG dosyaları Word'e "Insert > Picture" ile çekilir; vektörel oldukları için
ölçeklendirmede kalite kaybı yok.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

# ── Renkler (UI design token'larıyla uyumlu) ─────────────────────────────────
LAYER1_FILL = "#DBEAFE"     # açık mavi
LAYER1_EDGE = "#2563EB"
LAYER2_FILL = "#DCFCE7"     # açık yeşil
LAYER2_EDGE = "#16A34A"
INPUT_FILL  = "#FEF3C7"     # açık sarı
INPUT_EDGE  = "#D97706"
OUTPUT_FILL = "#FCE7F3"     # açık pembe
OUTPUT_EDGE = "#DB2777"
TEXT_DARK   = "#0F172A"
TEXT_MUTED  = "#475569"


def _box(ax, x, y, w, h, label, fill, edge, fontsize=9, weight="normal"):
    """Yuvarlatılmış köşeli kutu + ortalanmış etiket."""
    patch = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.15",
        linewidth=1.5, edgecolor=edge, facecolor=fill,
    )
    ax.add_patch(patch)
    ax.text(
        x + w / 2, y + h / 2, label,
        ha="center", va="center",
        fontsize=fontsize, color=TEXT_DARK, weight=weight,
        wrap=True,
    )


def _arrow(ax, x1, y1, x2, y2, color="#475569", style="->", lw=1.5):
    """İki nokta arası ok."""
    arrow = FancyArrowPatch(
        (x1, y1), (x2, y2),
        arrowstyle=style, mutation_scale=15,
        color=color, linewidth=lw,
    )
    ax.add_patch(arrow)


def _label(ax, x, y, text, fontsize=10, weight="bold", color=None):
    ax.text(
        x, y, text,
        ha="center", va="center",
        fontsize=fontsize, weight=weight,
        color=color or TEXT_DARK,
    )


# ════════════════════════════════════════════════════════════════════════════
# FIGURE 4-1: Two-layer SDSS architecture
# ════════════════════════════════════════════════════════════════════════════
def figure_4_1(out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 7.5))
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 11)
    ax.axis("off")

    # Başlık
    _label(ax, 8, 10.5, "Figure 4-1 — Two-layer Spatial Decision Support System Architecture",
           fontsize=12, weight="bold")

    # ── INPUT ────────────────────────────────────────────────────────────
    _box(ax, 0.5, 5.5, 2.2, 1.4, "User\n(district +\nparameters)",
         INPUT_FILL, INPUT_EDGE, fontsize=9, weight="bold")

    # ── LAYER 1 BÜYÜK KUTU ───────────────────────────────────────────────
    layer1_x, layer1_y, layer1_w, layer1_h = 3.4, 4.2, 5.7, 4.7
    layer1_patch = FancyBboxPatch(
        (layer1_x, layer1_y), layer1_w, layer1_h,
        boxstyle="round,pad=0.05,rounding_size=0.25",
        linewidth=2, edgecolor=LAYER1_EDGE, facecolor=LAYER1_FILL,
        alpha=0.35,
    )
    ax.add_patch(layer1_patch)
    _label(ax, layer1_x + layer1_w / 2, layer1_y + layer1_h - 0.35,
           "LAYER 1 — Data Collection Tool", fontsize=10, weight="bold",
           color=LAYER1_EDGE)

    # Layer 1 alt-kutuları (servis modülleri)
    services_l1 = [
        ("OSM Service\n(Overpass API)",  3.7, 6.9),
        ("Spatial Service\n(geometry +\nspatial join)",  6.0, 6.9),
        ("Rule Engine\n(tag-based +\nname fallback)",     3.7, 5.0),
        ("Population\nEstimator\n(footprint /\nTÜİK uniform)",  6.0, 5.0),
    ]
    for label, x, y in services_l1:
        _box(ax, x, y, 2.8, 1.5, label, LAYER1_FILL, LAYER1_EDGE, fontsize=8)

    # ── INTERMEDIATE OUTPUT (Layer 1 → Layer 2 köprüsü) ─────────────────
    _box(ax, 9.5, 6.0, 2.4, 1.4,
         "Excel /\nGeoJSON\n(Layer 1 output)",
         OUTPUT_FILL, OUTPUT_EDGE, fontsize=9, weight="bold")

    # ── LAYER 2 BÜYÜK KUTU ───────────────────────────────────────────────
    layer2_x, layer2_y, layer2_w, layer2_h = 9.4, 0.5, 6.2, 5.0
    layer2_patch = FancyBboxPatch(
        (layer2_x, layer2_y), layer2_w, layer2_h,
        boxstyle="round,pad=0.05,rounding_size=0.25",
        linewidth=2, edgecolor=LAYER2_EDGE, facecolor=LAYER2_FILL,
        alpha=0.35,
    )
    ax.add_patch(layer2_patch)
    _label(ax, layer2_x + layer2_w / 2, layer2_y + layer2_h - 0.35,
           "LAYER 2 — Assignment Optimization Tool",
           fontsize=10, weight="bold", color=LAYER2_EDGE)

    # Layer 2 alt-kutuları
    services_l2 = [
        ("Data Loader\n+ population\nweight assignment", 9.7, 3.4),
        ("OD Matrix Builder\n(OSMnx Dijkstra,\nwalk / drive)",     12.7, 3.4),
        ("p-Median Solver Portfolio\n(CBC · HiGHS · Gurobi · CPLEX · SCIP\n+ Heuristic multi-start)", 9.7, 1.0),
    ]
    for label, x, y in services_l2:
        if "Solver" in label:
            _box(ax, x, y, 5.9, 1.7, label, LAYER2_FILL, LAYER2_EDGE, fontsize=8)
        else:
            _box(ax, x, y, 2.8, 1.7, label, LAYER2_FILL, LAYER2_EDGE, fontsize=8)

    # ── OUTPUTS (sağda dikey blok) ───────────────────────────────────────
    _box(ax, 13.6, 5.7, 2.2, 1.4,
         "Decision report\n(Excel 9-10 sheets)",
         OUTPUT_FILL, OUTPUT_EDGE, fontsize=8, weight="bold")
    _box(ax, 13.6, 7.4, 2.2, 1.4,
         "Visualisation suite\n(Plotly + Folium\nF1-F8 figures)",
         OUTPUT_FILL, OUTPUT_EDGE, fontsize=8, weight="bold")

    # ── Oklar ────────────────────────────────────────────────────────────
    # User → Layer 1
    _arrow(ax, 2.7, 6.2, 3.4, 6.2, color=INPUT_EDGE, lw=2)
    # Layer 1 → Excel/GeoJSON
    _arrow(ax, 9.1, 6.7, 9.5, 6.7, color=LAYER1_EDGE, lw=2)
    # Excel → Layer 2 (Data Loader)
    _arrow(ax, 10.7, 6.0, 11.1, 5.1, color=OUTPUT_EDGE, lw=2)
    # Layer 2 (Solver) → outputs (visualisation + report)
    _arrow(ax, 15.6, 1.85, 15.6, 5.7, color=LAYER2_EDGE, lw=2,
           style="->")
    _arrow(ax, 15.6, 5.7, 15.6, 7.4, color=LAYER2_EDGE, lw=2)

    # ── Caption ──────────────────────────────────────────────────────────
    ax.text(8, 0.15,
            "Layer 1 ingests raw OSM data and produces analysis-ready files; "
            "Layer 2 consumes those files to solve the p-Median assignment "
            "and emit decision artefacts.",
            ha="center", va="center", fontsize=9, color=TEXT_MUTED, style="italic")

    plt.tight_layout()
    fig.savefig(out_path, format="svg", bbox_inches="tight", dpi=200)
    fig.savefig(out_path.with_suffix(".png"), format="png", bbox_inches="tight", dpi=200)
    plt.close(fig)
    print(f"Wrote {out_path}")
    print(f"Wrote {out_path.with_suffix('.png')}")


# ════════════════════════════════════════════════════════════════════════════
# FIGURE 4-2: Optimization workflow (Step 1 → 4)
# ════════════════════════════════════════════════════════════════════════════
def figure_4_2(out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(13, 6))
    ax.set_xlim(0, 18)
    ax.set_ylim(0, 9)
    ax.axis("off")

    # Başlık
    _label(ax, 9, 8.5,
           "Figure 4-2 — Optimization workflow (Step 1 to Step 4)",
           fontsize=12, weight="bold")

    # ── 4 Step kutuları (sol → sağ) ──────────────────────────────────────
    step_w, step_h = 3.4, 4.5
    step_y = 1.5
    steps = [
        # (x, başlık, alt-içerik, fill, edge)
        (0.5,  "Step 1\nLoad Data",
                "• Excel / GeoJSON upload\n"
                "• Population method\n"
                "   (Auto / Footprint /\n"
                "   Uniform per-building)\n"
                "• TÜİK calibration file\n"
                "• Non-residential\n"
                "   acknowledgement (>5%)\n"
                "• KPI summary +\n"
                "   neighbourhood audit",
                "#FEF3C7", "#D97706"),
        (4.5,  "Step 2\nOD Matrix",
                "• District selection\n"
                "• Transport mode\n"
                "   (walk / drive)\n"
                "• Speed parameter\n"
                "• OSMnx graph cache\n"
                "• Multi-source Dijkstra\n"
                "• Haversine fallback\n"
                "   (if network fails)",
                "#DBEAFE", "#2563EB"),
        (8.5,  "Step 3\nOptimize",
                "• p (areas to open)\n"
                "• Objective\n"
                "   (min-sum / max / p95)\n"
                "• Capacity ON/OFF\n"
                "• Density slider\n"
                "• ILP engine selector\n"
                "• K-Med multi-start\n"
                "   + reproducible seed\n"
                "• Sensitivity / Compare /\n"
                "   Density sweep /\n"
                "   Engine benchmark",
                "#DCFCE7", "#16A34A"),
        (12.5, "Step 4\nReview Results",
                "• KPI cards (5+5)\n"
                "• Coverage chart +\n"
                "   travel-time histogram\n"
                "• Population CDF\n"
                "• Density sweep table\n"
                "• Convergence trajectory\n"
                "• Engine benchmark\n"
                "• Folium map +\n"
                "   service catchments\n"
                "• CSV + Excel download",
                "#FCE7F3", "#DB2777"),
    ]
    for x, title, body, fill, edge in steps:
        # Ana kutu
        patch = FancyBboxPatch(
            (x, step_y), step_w, step_h,
            boxstyle="round,pad=0.05,rounding_size=0.2",
            linewidth=1.8, edgecolor=edge, facecolor=fill,
        )
        ax.add_patch(patch)
        # Başlık (üstte, bold)
        ax.text(x + step_w / 2, step_y + step_h - 0.4, title,
                ha="center", va="top", fontsize=11, weight="bold", color=edge)
        # Gövde (madde liste)
        ax.text(x + 0.25, step_y + step_h - 1.3, body,
                ha="left", va="top", fontsize=8, color=TEXT_DARK,
                family="sans-serif")

    # ── Step → Step okları ───────────────────────────────────────────────
    for i in range(3):
        x1 = 0.5 + (i + 1) * 4 - 0.6
        x2 = 0.5 + (i + 1) * 4 + 0.05
        y_mid = step_y + step_h / 2
        _arrow(ax, x1, y_mid, x2, y_mid, color=TEXT_MUTED, lw=2.5)

    # ── Session_state akışı (altta yatay band) ──────────────────────────
    band_y = 0.5
    band_w = 17
    band_patch = mpatches.Rectangle(
        (0.5, band_y), band_w, 0.55,
        linewidth=1, edgecolor="#94A3B8",
        facecolor="#F1F5F9",
    )
    ax.add_patch(band_patch)
    ax.text(0.7, band_y + 0.275,
            "Persistent state:",
            ha="left", va="center", fontsize=8, weight="bold", color=TEXT_MUTED)
    ax.text(9, band_y + 0.275,
            "opt_buildings · opt_assembly · opt_od_matrix · opt_result · "
            "opt_compare_results · opt_density_sweep · opt_engine_benchmark · "
            "ODSignature · ResultSignature",
            ha="center", va="center", fontsize=7.5, color=TEXT_MUTED,
            family="monospace")

    # ── Top hint: stale-banner döngüsü ──────────────────────────────────
    _arrow(ax, 16, 6.5, 0.7, 6.5,
           color="#F59E0B", lw=1.2, style="->")
    ax.text(9, 6.85,
            "Stale-result banner: if user changes parameters after a step, the "
            "next step auto-detects via typed signature diff and warns the user.",
            ha="center", va="center", fontsize=8, color="#B45309", style="italic")

    plt.tight_layout()
    fig.savefig(out_path, format="svg", bbox_inches="tight", dpi=200)
    fig.savefig(out_path.with_suffix(".png"), format="png", bbox_inches="tight", dpi=200)
    plt.close(fig)
    print(f"Wrote {out_path}")
    print(f"Wrote {out_path.with_suffix('.png')}")


# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent
    figures_dir = repo_root / "figures"
    figures_dir.mkdir(exist_ok=True)
    figure_4_1(figures_dir / "figure_4_1_sdss_architecture.svg")
    figure_4_2(figures_dir / "figure_4_2_optimization_workflow.svg")
    print(f"\nAll figures written to {figures_dir}")
    # Print in plain ASCII so Windows cp1254 console doesn't garble the
    # message — Turkish "Word'e ekleme:" became "Word'e ekleme: yukar?daki..."
    print("To use in Word: Insert > Picture > pick the files above.")
