# Input templates

These are the blank Excel templates that the **Optimization Tool** offers for
download in *Step 1 · Load data* ("📥 Need a template? Download blank Excel").
They are provided here so you can grab them straight from the repository without
running the app. Both files are also generated programmatically by
[`src/optimizer/templates.py`](../src/optimizer/templates.py), so the copies in
this folder are byte-for-byte identical to what the tool produces. Fill in your
own rows (the single example row in each sheet shows the expected format) and
upload the file back into the tool — the loader is bilingual, so these English
headers are recognised without any renaming.

## Files

| File | Sheets | Use it when |
|---|---|---|
| **`Buildings_Assembly_template.xlsx`** | `Buildings`, `Assembly`, `README` | You want to provide your own demand points (buildings) and candidate assembly areas instead of using the data-collection tool's output. |
| **`TUIK_Population_template.xlsx`** | `TUIK_Population`, `README` | You use the *Uniform per-building* population method, which distributes each neighbourhood's official TÜİK population across its buildings. |

## Columns

**Buildings** — `Latitude`, `Longitude`, `Neighbourhood`, `Name`, `Area (m²)`,
`Floors`, `OSM ID`
**Assembly** — `Latitude`, `Longitude`, `Name`, `Area (m²)`, `Neighbourhood`
**TUIK_Population** — `neighbourhood_name`, `population`

`Latitude`/`Longitude` are WGS84 (EPSG:4326) decimal degrees and must fall
inside Istanbul. `Area (m²)` drives the footprint-based population estimate
(buildings) and the AFAD capacity at 1.5 m²/person (assembly areas); if `Floors`
is blank a default of 4 is assumed. Each workbook's own `README` sheet documents
every field and whether it is required or optional.
