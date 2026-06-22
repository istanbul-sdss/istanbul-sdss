# Istanbul Spatial Decision Support System

*🇬🇧 English · [🇹🇷 Türkçe](README.tr.md)*

A decision-support system built on **Streamlit + GeoPandas + OSMnx** that
collects and classifies OpenStreetMap data for Istanbul districts and runs a
**capacity-aware p-median optimization** to plan AFAD earthquake assembly areas.
It ships as two complementary tools: a **Data Collection Tool** that turns a
district into clean, mapped, quality-checked spatial data, and an
**Optimization Tool** that places assembly areas optimally on top of that data.

## Live demos

Both tools are deployed on Streamlit Community Cloud, so you can try the full
system in your browser without installing anything:

- **Data Collection Tool** — <https://istanbul-sdss-data.streamlit.app/>
- **Optimization Tool** — <https://istanbul-sdss-optimization.streamlit.app/>

> The apps sleep after a period of inactivity; the first visit may take ~30
> seconds to wake up. For a quick tour, start with the Data Collection Tool
> (pick a district → extract → explore the map), then open the Optimization
> Tool and load one of the bundled samples or your own data.

## Components

| Streamlit page | Purpose |
|---|---|
| `Spatial_Data_Collection_Tool.py` | Home page of the data-collection app |
| `pages/1_Data_Extraction.py` | District + category selection → OSM extraction → Excel/CSV/GeoJSON export |
| `pages/2_Map_Visualization.py` | Interactive map of the extracted results |
| `pages/3_Analytics_Dashboard.py` | KPIs, neighbourhood distribution, confidence breakdown |
| `Optimization_Tool.py` | Earthquake assembly-area assignment + p-median |

| Backend module | Responsibility |
|---|---|
| `src/pipelines/pipeline.py` | OSM fetch + filter + spatial enrich + classification flow |
| `src/services/osm_service.py` | Overpass/Nominatim/OSMnx calls, error classes |
| `src/services/spatial_service.py` | CRS, geometry cleaning, area calculation, neighbourhood assignment |
| `src/services/rule_engine.py` | Rule-based classification (strict/support/name/query_tag) |
| `src/services/post_filter.py` | Strict-tag post-filter (cleans Overpass union leakage) |
| `src/services/excel_exporter.py` | Multi-sheet styled Excel report |
| `src/services/excel_utils.py` | Workbook styling layer (`build_styled_workbook`, `style_workbook`) |
| `src/optimizer/data_loader.py` | Excel/GeoJSON → buildings + assembly GeoDataFrames |
| `src/optimizer/od_matrix.py` | OSMnx walking graph + OD matrix |
| `src/optimizer/p_median.py` | ILP (PuLP) and heuristic solvers |
| `src/config/settings.py` | All constants in one place (WALK_SPEED_KPH, AFAD_M2_PER_PERSON, …) |

## Quick start (5 minutes)

**Requirements:** Python 3.10+ and an internet connection (for OSM data).

### Windows

```cmd
git clone https://github.com/istanbul-sdss/istanbul-sdss.git
cd istanbul-sdss
setup.bat
run_data_tool.bat
```

For the second app (assignment optimization), in a separate window:

```cmd
run_optimizer.bat
```

### macOS / Linux

```bash
git clone https://github.com/istanbul-sdss/istanbul-sdss.git
cd istanbul-sdss
./setup.sh
./run_data_tool.sh
```

For the second app (assignment optimization), in a separate terminal:

```bash
./run_optimizer.sh
```

> **Tip:** The first extraction pulls data from the Overpass API, so it takes
> 1–3 minutes. **Kadıköy** is a good district for a quick test; alternatively,
> ready-made samples live in `data/samples/` and can be loaded straight into the
> Optimization Tool (map + KPIs + Excel report without waiting for extraction).

## Manual install (without the scripts)

```bash
# Python 3.10+ required
python -m venv venv
venv\Scripts\activate         # Windows
# source venv/bin/activate    # Linux/macOS

pip install -r requirements.txt
pip install -r requirements-dev.txt   # for tests/lint (optional)

streamlit run Spatial_Data_Collection_Tool.py
# Separate entry point for the optimizer:
streamlit run Optimization_Tool.py --server.port 8502
```

### Reproducible installs (exact versions via lock files)

`requirements.txt` is kept with ranges (`>=lower,<upper`), so sub-packages may
resolve to different patch/minor versions between installs. For reproducing the
exact numbers in the thesis, letting reviewers see identical output, or
deterministic CI builds, use the **lock files**:

```bash
# Pinned install instead of ranges (every package at an exact version)
pip install -r requirements.lock              # runtime only
pip install -r requirements-dev.lock          # runtime + test/lint
```

The lock files are regenerated with `pip-tools` (`pip install pip-tools`, or it
comes via `requirements-dev.txt`):

```bash
python -m piptools compile --strip-extras \
    --output-file=requirements.lock requirements.txt
python -m piptools compile --strip-extras \
    --output-file=requirements-dev.lock requirements.txt requirements-dev.txt
```

To deliberately upgrade a dependency: bump the upper bound in `requirements.txt`
or `requirements-dev.txt`, re-run the two commands above, review the `.lock`
diffs, and commit.

## Verifying the install

A two-minute sanity check after installation:

1. **Does the test suite pass?** (`requirements-dev.txt` must be installed first
   — `pytest` is a dev dependency, not a runtime one.)
   ```bash
   venv\Scripts\activate                       # Windows
   # source venv/bin/activate                  # Linux/macOS
   pip install -r requirements-dev.txt         # pytest + ruff + pre-commit
   python -m pytest tests/ -q
   ```
   Expected: **all tests pass, 1 skipped.** (The test count grows over time, so
   the baseline is "no failures/errors" rather than a fixed number; for the
   current count: `python -m pytest tests/ --collect-only -q | tail -1`.)

2. **Does the UI open?** Run `run_data_tool.bat`/`.sh` → the browser should open
   `http://localhost:8501` with the "Istanbul Spatial Decision Support System"
   title.

3. **Does the sample data load?** In a separate window run `run_optimizer.bat`/
   `.sh` → choose "Excel" → `data/samples/Kadıköy_OSM_sample.xlsx` → pick the
   sheets (`Konut - Genel` + `Toplanma Alanı`) → ✅ Load. Expected: ~6,665
   buildings + 154 assembly areas, ~244,000 estimated people.

If all three pass, the install is sound. Otherwise see Troubleshooting below.

## Input templates

If you are not using the data-collection tool's output, you can provide your own
input. The Optimization Tool offers two blank Excel templates under *Step 1 ·
Load data* ("📥 Need a template? Download blank Excel"), and the same files are
committed in [`templates/`](templates/) so you can download them straight from
the repository:

- `templates/Buildings_Assembly_template.xlsx` — buildings (demand points) and
  candidate assembly areas.
- `templates/TUIK_Population_template.xlsx` — neighbourhood population for the
  *Uniform per-building* method.

Each workbook has a `README` sheet documenting every column. Headers are English
(`Latitude`, `Longitude`, `Neighbourhood`, `Area (m²)`, `Floors`, …) and the
loader is bilingual, so filled-in templates upload back without renaming.

## Troubleshooting

### Windows: "Microsoft Visual C++ 14.0 or greater is required"
GeoPandas/Shapely binaries usually ship as prebuilt wheels; this error typically
appears on Python 3.13+ or very old pip versions.
- **Fix 1:** `python -m pip install --upgrade pip wheel`, then re-run
  `pip install -r requirements.txt`.
- **Fix 2:** Use Python 3.11 or 3.12 (3.10/3.11/3.12 are verified in CI; 3.13 is
  not yet).

### "ImportError: GDAL not found" / Fiona error
Rare on Windows; the GeoPandas wheel carries its own dependencies.
- Try `pip install --force-reinstall geopandas shapely fiona`.
- If it still fails, use Anaconda: `conda install -c conda-forge geopandas shapely`.

### "OverpassNetworkError: all endpoints failed"
No internet, or the Overpass API is temporarily down. You can work offline with
the sample data (`data/samples/Kadıköy_OSM_sample.xlsx`); a live connection is
only required for Data Extraction. Retry in a few minutes or check
<https://overpass-api.de/api/status>.

### The Streamlit page does not open in the browser
- Open the URL printed on the command line (`http://localhost:8501`) manually.
- Antivirus/firewall may block the localhost port; add an exception.
- The port may already be in use (another Streamlit session); try a different
  one, e.g. `--server.port 8503`.

### Turkish characters in the Windows console
The logger uses a UTF-8 wrapper; emojis may show as `?` in a cp1254 console but
this is harmless. The UI is unaffected.

## Tests

```bash
python -m pytest tests/
# Quick: a specific test file
python -m pytest tests/test_category_leakage_audit.py -v
```

A comprehensive regression suite is in place (500+ tests; for the current count
`pytest --collect-only -q | tail -1`). On push/PR, `.github/workflows/ci.yml`
runs it automatically on a Python 3.10, 3.11 and 3.12 matrix.

## Developer tools

Extra tools included in the repo (not part of the production flow):

- `analyze_outputs.py` — walks the Excel outputs in `output/` and audits row
  counts / empty-column ratios for the latest file per district. A quick way to
  spot regressions (e.g. whether new `TAG_RULES` changes keep the expected
  record counts across districts). Run: `python analyze_outputs.py`

## Third-party distribution (for developers)

To produce a clean ZIP 

```bash
python build_release.py --verify
# → dist/istanbul_sdss_<YYYYMMDD>.zip
```

This ZIP **excludes** local/generated folders such as `venv/`, `cache/`,
`output/`, `logs/`, `__pycache__/`. The recipient unzips it and runs
`setup.bat`/`setup.sh` to install into a clean environment.

## Data sources

- **OpenStreetMap (Overpass API)** — building/POI data (licence: ODbL). Three
  mirrors are tried: `overpass-api.de` → `lz4.overpass-api.de` →
  `overpass.kumi.systems`.
- **Nominatim** — district boundary geocoding.
- **TÜİK** — per-person area assumption for population estimation (6.25 m²/person).
- **AFAD** — assembly-area capacity standard (1.5 m²/person).

## Key assumptions

| Assumption | Value | Location |
|---|---|---|
| Adult walking speed | 4.8 km/h | `src/optimizer/od_matrix.py::WALK_SPEED_KPH` |
| AFAD m²/person | 1.5 m² | `src/services/spatial_service.py::AFAD_M2_PER_PERSON` |
| Per-person building area (TÜİK) | 6.25 m² | `src/optimizer/population_estimator.py` |
| ILP/heuristic threshold | 5000 buildings | `src/optimizer/p_median.py::ILP_THRESHOLD` |
| Assembly-area default | 1000 m² (no column, Point geometry) | `data_loader.py::DEFAULT_AREA_FALLBACK_M2` |
| Walk-graph cache version | v2 | `od_matrix.py::GRAPH_CACHE_VERSION` |

## Known limitations

- OSM data is volunteer-contributed — some buildings may lack `building:levels`,
  `name`, or a footprint polygon. The `Data Quality` page shows completeness
  percentages.
- Overpass mirrors occasionally return 504; if all endpoints fail an
  `OverpassNetworkError` is raised (it does not silently become "no data").
- The heuristic solver is used instead of ILP on large datasets (>5000
  buildings); it has no optimality guarantee but stays close to a local optimum.
- Walking-time estimates are horizontal; slope/stairs are not considered.
- Neighbourhood assignment: Points just outside the district boundary get the
  nearest neighbourhood via a `nearest` fallback, with a log warning.

## Engineering notes

The codebase has been hardened over several phases: a large regression test
suite (500+ tests, CI on Python 3.10–3.12 plus a Streamlit smoke test),
centralized constants in `src/config/settings.py`, a bilingual data loader,
content-based caching, deterministic spatial joins, hardened error handling (no
stack-trace leakage to the UI), a consolidated Excel-styling layer, and a `ruff`
lint baseline enforced via pre-commit and CI. See the git history for the
detailed change log.

## License

**Code: Apache License 2.0.** The source code of this project is licensed under
Apache-2.0 (see `LICENSE`). It may be freely used, modified and distributed; the
only conditions are preserving the copyright/licence notices and marking changed
files. Apache-2.0 also includes an explicit patent grant from contributors.

**Data: governed by its own licences (outside the Apache-2.0 scope).**
`data/mahalleleri/*.geojson` and all OpenStreetMap data the app fetches via
Overpass are **© OpenStreetMap contributors, ODbL v1.0**. Distribution of
databases derived from this data must comply with ODbL independently of the
code. See `NOTICE` for details and third-party library attributions.
