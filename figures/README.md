# Figures — Chapter 4

## Generation

```bash
./venv/Scripts/python tools/generate_chapter4_figures.py
```

Re-running the script regenerates both SVG and PNG files deterministically;
useful when the system design changes and the diagrams need to be refreshed.

## Files

| File | Caption (use in Word) |
|---|---|
| `figure_4_1_sdss_architecture.svg` / `.png` | **Figure 4-1.** Two-layer Spatial Decision Support System architecture. Layer 1 (Data Collection Tool) ingests raw OSM data through the OSM Service / Spatial Service / Rule Engine / Population Estimator pipeline and writes analysis-ready Excel / GeoJSON files. Layer 2 (Assignment Optimization Tool) consumes those files via its Data Loader, builds the OD matrix over the OSMnx street graph, and dispatches the p-Median problem to one of five ILP engines (CBC, HiGHS, Gurobi, CPLEX, SCIP) or to the greedy heuristic with multi-start. Decision artefacts are produced as a 9–10 sheet Excel report and an interactive Plotly / Folium visualisation suite (see F1–F8 mapping below). |
| `figure_4_2_optimization_workflow.svg` / `.png` | **Figure 4-2.** Step-by-step optimisation workflow inside the Assignment Optimization Tool. Each step writes to shared `st.session_state` keys (bottom band); typed `ODSignature` / `ResultSignature` dataclasses drive the stale-banner that warns the user when a parameter changes after a step (top arrow). Step 4's "Review Results" panel produces the eight academic visualisations used in Chapter 5 (see F1–F8 mapping below). |

## F1–F8 visualisation mapping

The "visualisation suite (F1–F8)" referenced in the figure captions
maps to the following Step 4 panels (each pasted into Chapter 5 as
one or two figures):

| ID | Step 4 panel | Chapter 5 figure |
|---|---|---|
| **F1** | "Coverage by travel-time threshold" — bar chart at 5 / 10 / 30 min | 5.1 Coverage bands |
| **F2** | "Capacity sensitivity comparison" — capacity ON vs OFF KPI tables + hints | 5.4 Capacity ON vs OFF |
| **F3** | "Travel-time distribution" — building-count histogram with AFAD threshold lines | 5.2 Walking-time histogram |
| **F4** | "Population coverage CDF" — weighted cumulative curve | 5.3 Population coverage CDF |
| **F5** | "Density sensitivity (ρ sweep)" — KPI table + dual-axis bar chart | 5.5 Density sensitivity |
| **F6** | "🎯 Service catchments" — Folium polygon overlay (convex hulls) on assignment map | 5.6 Assignment map + catchments |
| **F7** | "📉 Heuristic convergence trajectory" — per-restart cost descent | 5.7 Heuristic convergence |
| **F8** | "⏱ ILP engine benchmark" — table + bar chart (CBC / HiGHS / Gurobi / CPLEX) | 5.8 Engine runtime benchmark |

Two additional artefacts are produced by Step 4 but are not part of
the F1–F8 numbering (they are decision artefacts rather than
sensitivity figures): the full assignment Folium map (without the
catchment overlay) and the Excel report (9–10 sheets).

## Embedding into Word

1. In Word: **Insert → Picture → This Device** → select the SVG file.
2. Right-click → **Wrap Text → Top and Bottom** (typical thesis layout).
3. Below the figure, add the caption (numbered automatically via Word's
   **References → Insert Caption** if you've defined a "Figure" label).
4. SVGs are vector, so resizing in Word never blurs them. Keep PNG copies
   only as a backup for editors that do not support SVG.

## Style notes

Colours match the optimizer UI design tokens for visual consistency:

- **Layer 1** — blue (`#2563EB` on `#DBEAFE`)
- **Layer 2** — green (`#16A34A` on `#DCFCE7`)
- **Input/User** — amber (`#D97706` on `#FEF3C7`)
- **Outputs** — pink (`#DB2777` on `#FCE7F3`)

If reviewers prefer black-and-white printing, regenerate after editing
`tools/generate_chapter4_figures.py` to use grayscale palettes.
