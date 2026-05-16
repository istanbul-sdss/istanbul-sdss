"""
pages/5_Neighborhood_Sync.py — Refresh neighbourhood boundaries from OSM.

The local `data/mahalleleri/<district>.geojson` files can drift from
OpenStreetMap over time. This page lets the user pick a Turkish district
name; in the background, the Overpass query is built, sent, converted to
GeoJSON, and written under the correct (lowercase, ASCII-folded) filename
in one click. The previous file is preserved as `.bak.<timestamp>` so a
bad download can be rolled back.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from components import cards
from components.state import init_state
from components.styles import configure_page
from src.config.settings import ISTANBUL_ILCELER, MAH_DIR_STR
from src.logger import get_logger
from src.services.overpass_downloader import (
    OverpassError,
    build_query,
    file_status,
    update_district,
)

log = get_logger("page.neighborhood_sync")

configure_page(title="Neighborhood Sync", icon="🔄")
init_state()


# ════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════════════════════
cards.sidebar_brand()

st.sidebar.markdown("### Mode")
mode = st.sidebar.radio(
    "Mode",
    options=["Single district", "Bulk update"],
    index=0,
    label_visibility="collapsed",
    help=(
        "Single district — refresh one district's neighbourhood file.\n"
        "Bulk update — process several districts in sequence "
        "(a short pause between calls keeps Overpass happy)."
    ),
)

st.sidebar.markdown("---")
st.sidebar.markdown("### Settings")
backup = st.sidebar.checkbox(
    "Back up existing file as `.bak.<ts>`",
    value=True,
    help="If disabled, the existing file is overwritten and cannot be recovered.",
)
# Confirmation guard (UI review P3): backup KAPALI iken üzerine yazma
# geri alınamayan bir aksiyon. İkinci bir onay checkbox'ı ile yanlış
# tıklama kazasını önlüyoruz.
backup_off_confirmed = True
if not backup:
    st.sidebar.warning(
        "⚠ Backup kapalı — mevcut dosya **kalıcı olarak** üzerine yazılacak. "
        "Geri alınamaz."
    )
    backup_off_confirmed = st.sidebar.checkbox(
        "Yedeksiz üzerine yazma riskini kabul ediyorum",
        value=False,
        key="nbsync_backup_off_confirm",
    )
timeout = st.sidebar.slider(
    "Query timeout (seconds)",
    min_value=30, max_value=180, value=90, step=10,
    help="Maximum time Overpass is allowed to spend on each query.",
)


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════
cards.page_header(
    title="Neighborhood Sync",
    subtitle=(
        "Pull the latest neighbourhood boundaries from OpenStreetMap "
        "and write them to the data/mahalleleri/ folder."
    ),
    eyebrow="Data Maintenance",
)

# A2 düzeltmesi: mutlak yol göstermek (örn. `C:\Users\yusuf\...`) hem
# kullanıcı adını ifşa ediyor hem de portable değil. Proje köküne göre
# relative path daha temiz; tooltip'te tam yol gerekirse expander'da
# görünür.
from pathlib import Path as _Path

try:
    _rel_target = _Path(MAH_DIR_STR).resolve().relative_to(_Path.cwd().resolve())
    _rel_display = f"./{_rel_target.as_posix()}"
except (ValueError, OSError):
    # cwd dışında ise relative çıkmaz — sadece son iki dizini göster
    _parts = _Path(MAH_DIR_STR).parts
    _rel_display = ".../" + "/".join(_parts[-2:]) if len(_parts) >= 2 else MAH_DIR_STR
st.caption(
    f"Target folder: `{_rel_display}` · "
    f"Query target: `relation/way[admin_level=8]` (neighbourhood boundaries)"
)


# ── Status table for existing files ─────────────────────────────────────────
def _status_table() -> pd.DataFrame:
    rows = []
    for ilce in ISTANBUL_ILCELER:
        st_ = file_status(ilce)
        rows.append({
            "District": ilce,
            "Status": "✅ Present" if st_["exists"] else "⚠️ Missing",
            "Last updated": (
                st_["mtime"].strftime("%Y-%m-%d %H:%M") if st_.get("mtime") else "—"
            ),
            "Size (KB)": st_.get("size_kb", "—"),
        })
    return pd.DataFrame(rows)


with st.expander("📋 Current file status", expanded=False):
    df_status = _status_table()
    st.dataframe(df_status, hide_index=True, width="stretch")
    missing = (df_status["Status"] == "⚠️ Missing").sum()
    if missing:
        st.info(f"{missing} district(s) have no neighbourhood file yet.")


st.markdown("---")


# ── District selection ──────────────────────────────────────────────────────
if mode == "Single district":
    st.markdown("### 1 · Select district")
    # Default: Beşiktaş varsa onu seç, yoksa listenin başı.
    # (Listenin sabit kalacağına güvenmemek için defansif: ad değişirse veya
    #  silinirse sayfa yine açılır.)
    _default_idx = (
        ISTANBUL_ILCELER.index("Beşiktaş")
        if "Beşiktaş" in ISTANBUL_ILCELER else 0
    )
    ilce = st.selectbox(
        "District",
        ISTANBUL_ILCELER,
        index=_default_idx,
        label_visibility="collapsed",
    )
    selected = [ilce]
else:
    st.markdown("### 1 · Select districts")
    pick_mode = st.radio(
        "Selection",
        options=["All districts (39)", "Missing only", "Manual select"],
        horizontal=True,
        label_visibility="collapsed",
    )
    if pick_mode == "All districts (39)":
        selected = list(ISTANBUL_ILCELER)
    elif pick_mode == "Missing only":
        selected = [
            ilce for ilce in ISTANBUL_ILCELER
            if not file_status(ilce)["exists"]
        ]
        st.caption(f"{len(selected)} missing district(s) selected.")
    else:
        selected = st.multiselect(
            "Districts",
            ISTANBUL_ILCELER,
            default=[],
            label_visibility="collapsed",
        )


# ── Single-district status card + query preview ────────────────────────────
if mode == "Single district" and selected:
    cur = file_status(selected[0])
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            "Existing file",
            "✅ Yes" if cur["exists"] else "⚠️ No",
        )
    with col2:
        st.metric(
            "Last updated",
            cur["mtime"].strftime("%Y-%m-%d") if cur.get("mtime") else "—",
        )
    with col3:
        st.metric(
            "Size",
            f"{cur['size_kb']} KB" if cur.get("size_kb") is not None else "—",
        )

    with st.expander("🔍 Overpass query to be sent", expanded=False):
        st.code(build_query(selected[0], timeout=timeout), language="text")


st.markdown("---")
st.markdown("### 2 · Run")

_sync_disabled_reason = None
if not selected:
    _sync_disabled_reason = "Select at least one district to sync."
elif not backup and not backup_off_confirmed:
    _sync_disabled_reason = (
        "⚠ Backup kapalı — mevcut dosyaların kalıcı olarak üzerine yazılması "
        "için sidebar'daki onay checkbox'ını işaretleyin."
    )
# Bulk update için ek uyarı: tek tıkla 39 ilçe Overpass'tan yeniden
# çekiliyor — 20+ dakika sürebilir.
if mode == "Bulk update" and len(selected) >= 5:
    st.info(
        f"ℹ Bulk plan: **{len(selected)} ilçe** sırayla işlenecek. "
        f"Tahmini süre: **~{max(1, len(selected) // 2)}-{max(2, len(selected))} dk** "
        f"(Overpass cevap süresine bağlı). İptal etmek için tarayıcı sekmesi "
        f"kapatılmalı; başarılı/başarısız ayrımı sonuçta gösterilir."
    )

if _sync_disabled_reason:
    st.info(_sync_disabled_reason)
elif st.button(
    f"🔄 Sync ({len(selected)} district{'s' if len(selected) != 1 else ''})",
    type="primary",
    width="stretch",
):
    progress = st.progress(0.0, text="Starting…")
    log_box = st.container()
    successes: list[dict] = []
    failures: list[dict] = []

    for i, ilce in enumerate(selected, start=1):
        progress.progress(
            (i - 1) / len(selected),
            text=f"({i}/{len(selected)}) {ilce} — querying Overpass…",
        )
        try:
            res = update_district(
                ilce,
                backup=backup,
                timeout=timeout,
            )
            successes.append(res)
            with log_box:
                st.success(
                    f"✅ **{ilce}** — {res['feature_count']} feature(s), "
                    f"{res['polygon_count']} polygon(s) → "
                    f"`{Path(res['path']).name}`"
                )
        except OverpassError as e:
            failures.append({"ilce": ilce, "error": str(e)})
            with log_box:
                st.error(f"❌ **{ilce}** — {e}")

        # Be polite to Overpass: short pause between consecutive districts
        if len(selected) > 1 and i < len(selected):
            time.sleep(1.5)

    progress.progress(1.0, text="Done.")

    st.markdown("---")
    col_ok, col_err = st.columns(2)
    col_ok.metric("✅ Succeeded", len(successes))
    col_err.metric("❌ Failed", len(failures))

    if successes:
        st.markdown("#### Files written")
        st.dataframe(
            pd.DataFrame(successes)[
                ["ilce", "feature_count", "polygon_count", "path"]
            ].rename(
                columns={
                    "ilce": "District",
                    "feature_count": "Features",
                    "polygon_count": "Polygons",
                    "path": "File",
                }
            ),
            hide_index=True,
            width="stretch",
        )

    if failures:
        st.markdown("#### Failures")
        st.dataframe(
            pd.DataFrame(failures).rename(
                columns={"ilce": "District", "error": "Error"}
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "If a backup was enabled, the previous file was preserved as "
            "`.bak.<ts>` before the new one was written. If Overpass is the "
            "issue, wait a few minutes and try again."
        )

    if successes:
        # Disk cache'i (neighbourhood_loader.list_available) update_district
        # içinde otomatik temizleniyor. Ancak Name Lookup gibi sayfalardaki
        # @st.cache_data ile sarılı pool'lar (PreparedPools, UniversalPool)
        # ESKİ mahalle verisini hâlâ tutuyor olabilir — bu cache process-local
        # ve TTL=3600s; kullanıcı bu butona basarak hemen invalidate edebilir.
        st.info(
            "New neighbourhood data is now on disk. Other pages "
            "(e.g. Name Lookup) may still hold the old version in their "
            "Streamlit cache; click below to clear it."
        )
        if st.button("🧹 Clear Streamlit caches", key="nbsync_clear_cache"):
            st.cache_data.clear()
            st.success("Streamlit caches cleared. Other pages will refetch on next visit.")


cards.footer()
