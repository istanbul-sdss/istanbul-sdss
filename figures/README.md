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
| `figure_4_1_sdss_architecture.svg` / `.png` | **Figure 4-1.** Two-layer Spatial Decision Support System architecture. Layer 1 (Data Collection Tool) ingests raw OSM data through the OSM Service / Spatial Service / Rule Engine / Population Estimator pipeline and writes analysis-ready Excel / GeoJSON files. Layer 2 (Assignment Optimization Tool) consumes those files via its Data Loader, builds the OD matrix over the OSMnx street graph, and dispatches the p-Median problem to one of five ILP engines (CBC, HiGHS, Gurobi, CPLEX, SCIP) or to the K-Medoids heuristic with multi-start. Decision artefacts are produced as a 9–10 sheet Excel report and an interactive Plotly / Folium visualisation suite (F1–F8). |
| `figure_4_2_optimization_workflow.svg` / `.png` | **Figure 4-2.** Step-by-step optimisation workflow inside the Assignment Optimization Tool. Each step writes to shared `st.session_state` keys (bottom band); typed `ODSignature` / `ResultSignature` dataclasses drive the stale-banner that warns the user when a parameter changes after a step (top arrow). Step 4's "Review Results" panel produces the 8 academic figures used in Chapter 5. |

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
