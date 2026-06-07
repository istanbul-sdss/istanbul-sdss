"""
generate_report_flowcharts.py — Chapter 4 flowcharts in the shared visual
style of the progress-report diagrams (rounded pastel boxes, vertical flow,
left-side phase brackets).

Produces three vector SVGs (Word: Insert > Picture, scales without quality loss):

    figures/fig_4_1_system_architecture.svg   → §4.2.1  (5-layer architecture)
    figures/fig_4_2_data_collection_flow.svg  → §4.3    (9-step data pipeline)
    figures/fig_4_3_optimization_flow.svg     → §4.4    (OD → ILP → results)

Run:  python tools/generate_report_flowcharts.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

FIG_DIR = Path(__file__).resolve().parent.parent / "figures"

# ── Palette (matches the shared diagram style) ───────────────────────────────
PURPLE_F, PURPLE_E = "#E8E6FB", "#6C63C7"   # input / output
GREEN_F,  GREEN_E  = "#DDF3E4", "#2E8B57"   # data-acquisition phase
ORANGE_F, ORANGE_E = "#FBE6D4", "#C77D2E"   # spatial-processing phase
BLUE_F,   BLUE_E   = "#DDE8FB", "#3A6EA5"   # service boxes (architecture)
RED_F,    RED_E    = "#FBE0E0", "#C0504D"   # accent box (architecture)
INK   = "#1F2D3D"
MUTED = "#5A6B7B"
BRACKET = "#9AA7B4"

plt.rcParams["font.family"] = "DejaVu Sans"


def box(ax, cx, cy, w, h, title, sub, fill, edge, title_size=12, sub_size=9.5):
    """Rounded box centred at (cx, cy) with bold title + muted subtitle."""
    p = FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.14",
        linewidth=1.6, edgecolor=edge, facecolor=fill, mutation_aspect=1,
    )
    ax.add_patch(p)
    if sub:
        ax.text(cx, cy + h * 0.16, title, ha="center", va="center",
                fontsize=title_size, weight="bold", color=edge)
        ax.text(cx, cy - h * 0.22, sub, ha="center", va="center",
                fontsize=sub_size, color=MUTED)
    else:
        ax.text(cx, cy, title, ha="center", va="center",
                fontsize=title_size, weight="bold", color=edge)


def varrow(ax, cx, y_top, y_bot, color=MUTED):
    ax.add_patch(FancyArrowPatch(
        (cx, y_top), (cx, y_bot),
        arrowstyle="-|>", mutation_scale=16, color=color, linewidth=1.6))


def split_arrow(ax, cx, y_top, targets, y_bot, color=MUTED):
    """One source fanning out to multiple x targets (for export split)."""
    for tx in targets:
        ax.add_patch(FancyArrowPatch(
            (cx, y_top), (tx, y_bot),
            arrowstyle="-|>", mutation_scale=14, color=color, linewidth=1.4,
            connectionstyle="arc3,rad=0"))


def phase_bracket(ax, x, y_top, y_bot, label, color=BRACKET):
    """Vertical bracket with a rotated label on the left."""
    ax.plot([x, x], [y_bot, y_top], color=color, lw=1.4)
    ax.plot([x, x + 0.12], [y_top, y_top], color=color, lw=1.4)
    ax.plot([x, x + 0.12], [y_bot, y_bot], color=color, lw=1.4)
    ax.text(x - 0.18, (y_top + y_bot) / 2, label, rotation=90,
            ha="center", va="center", fontsize=10, color=MUTED, weight="bold")


def title(ax, x, y, text):
    ax.text(x, y, text, ha="center", va="center",
            fontsize=13, weight="bold", color=INK)


def save(fig, name):
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = FIG_DIR / name
    fig.savefig(out, format="svg", bbox_inches="tight", pad_inches=0.15)
    # also PNG for quick preview / non-vector contexts
    fig.savefig(out.with_suffix(".png"), dpi=150, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print(f"WROTE {out}  (+ .png)")


# ════════════════════════════════════════════════════════════════════════════
# FIGURE 4.1 — Five-layer system architecture (§4.2.1)
# ════════════════════════════════════════════════════════════════════════════
def fig_4_1():
    fig, ax = plt.subplots(figsize=(7.4, 9.2))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 13)
    ax.axis("off")
    title(ax, 5, 12.5, "Figure 4.1  System architecture (five layers)")

    cx, w, h = 5.6, 6.4, 1.35
    ys = [11.0, 9.2, 7.4, 5.6, 3.8]
    layers = [
        ("1  ·  Presentation layer", "Streamlit interface — district & parameter selection", PURPLE_F, PURPLE_E),
        ("2  ·  Pipeline layer", "End-to-end workflow coordinator", GREEN_F, GREEN_E),
        ("3  ·  Service layer", "OSM · spatial · classification · neighbourhood · export", BLUE_F, BLUE_E),
        ("4  ·  Optimizer layer", "Population est. · OD matrix · p-median solver", ORANGE_F, ORANGE_E),
        ("5  ·  Configuration layer", "Constants · rules · assumptions (single source of truth)", RED_F, RED_E),
    ]
    for y, (t, s, f, e) in zip(ys, layers):
        box(ax, cx, y, w, h, t, s, f, e)
    for i in range(len(ys) - 1):
        varrow(ax, cx, ys[i] - h / 2, ys[i + 1] + h / 2)

    # left bracket grouping the operational core (layers 2-4)
    phase_bracket(ax, 1.9, ys[1] + h / 2, ys[3] - h / 2, "Processing core")

    # caption note
    ax.text(5, 2.5,
            "Arrows show control/data flow; the configuration layer feeds every layer.",
            ha="center", va="center", fontsize=8.5, color=MUTED, style="italic")
    save(fig, "fig_4_1_system_architecture.svg")


# ════════════════════════════════════════════════════════════════════════════
# FIGURE 4.2 — Data-collection flow, 9 steps (§4.3)
# ════════════════════════════════════════════════════════════════════════════
def fig_4_2():
    fig, ax = plt.subplots(figsize=(7.6, 11.4))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 16)
    ax.axis("off")
    title(ax, 5.2, 15.5, "Figure 4.2  Data-collection and preparation workflow")

    cx, w, h = 5.8, 6.6, 1.15
    steps = [
        ("1. Select district", "Define the area of interest", PURPLE_F, PURPLE_E),
        ("2. Retrieve district boundary", "Local mahalle union (OSM fallback)", GREEN_F, GREEN_E),
        ("3. Load neighbourhood GeoJSON", "Import local geometry file", GREEN_F, GREEN_E),
        ("4. Retrieve features by category", "Overpass API — POIs, land use, roads", GREEN_F, GREEN_E),
        ("5. Clean & standardize geometries", "Fix invalid shapes, reproject CRS", ORANGE_F, ORANGE_E),
        ("6. Apply rule-based classification", "Tag features using defined rules", ORANGE_F, ORANGE_E),
        ("7. Assign neighbourhood", "Spatial join to neighbourhood layer", ORANGE_F, ORANGE_E),
        ("8. Calculate spatial attributes", "Area, distance, density metrics", ORANGE_F, ORANGE_E),
        ("9. Export final dataset", "Save as Excel / CSV / GeoJSON", PURPLE_F, PURPLE_E),
    ]
    gap = 1.55
    ys = [14.2 - i * gap for i in range(len(steps))]
    for y, (t, s, f, e) in zip(ys, steps):
        box(ax, cx, y, w, h, t, s, f, e, title_size=11, sub_size=9)
    for i in range(len(ys) - 1):
        varrow(ax, cx, ys[i] - h / 2, ys[i + 1] + h / 2)

    # phase brackets
    phase_bracket(ax, 2.1, ys[1] + h / 2, ys[3] - h / 2, "Data acquisition")
    phase_bracket(ax, 2.1, ys[4] + h / 2, ys[7] - h / 2, "Spatial processing")
    save(fig, "fig_4_2_data_collection_flow.svg")


# ════════════════════════════════════════════════════════════════════════════
# FIGURE 4.3 — Optimization flow (§4.4)
# ════════════════════════════════════════════════════════════════════════════
def fig_4_3():
    fig, ax = plt.subplots(figsize=(7.6, 11.8))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 16)
    ax.axis("off")
    title(ax, 5.2, 15.5, "Figure 4.3  Optimization workflow (assignment model)")

    cx, w, h = 5.8, 6.8, 1.2
    steps = [
        ("1. Load prepared data", "Buildings + assembly areas (Excel / GeoJSON)", PURPLE_F, PURPLE_E),
        ("2. Estimate building population", "Footprint-based or TÜİK-uniform → demand wᵢ", GREEN_F, GREEN_E),
        ("3. Derive assembly capacity", "Cⱼ = areaⱼ / density (AFAD 1.5 m²/person)", GREEN_F, GREEN_E),
        ("4. Build pedestrian OD matrix", "OSMnx walk graph, shortest paths (dᵢⱼ)", GREEN_F, GREEN_E),
        ("5. Set optimization parameters", "p (areas to open) · objective · capacity on/off", ORANGE_F, ORANGE_E),
        ("6. Solve capacity-aware p-median", "Exact ILP (PuLP / CBC) — provably optimal", ORANGE_F, ORANGE_E),
        ("7. Evaluate solution", "Coverage, avg/p95/max time, utilization, status", ORANGE_F, ORANGE_E),
        ("8. Visualize, compare & export", "Map · KPIs · capacity ON/OFF · Excel report", PURPLE_F, PURPLE_E),
    ]
    gap = 1.62
    ys = [14.0 - i * gap for i in range(len(steps))]
    for y, (t, s, f, e) in zip(ys, steps):
        box(ax, cx, y, w, h, t, s, f, e, title_size=11, sub_size=9)
    for i in range(len(ys) - 1):
        varrow(ax, cx, ys[i] - h / 2, ys[i + 1] + h / 2)

    phase_bracket(ax, 2.0, ys[1] + h / 2, ys[3] - h / 2, "Model inputs")
    phase_bracket(ax, 2.0, ys[5] + h / 2, ys[6] - h / 2, "Solve & assess")
    save(fig, "fig_4_3_optimization_flow.svg")


if __name__ == "__main__":
    fig_4_1()
    fig_4_2()
    fig_4_3()
    print("Done. 3 figures written to figures/.")
