"""
src/optimizer/map_renderer.py

P-Median atama sonuçlarını Folium haritasında görselleştirir.

Katmanlar:
  1. Binalar — atandıkları alana göre renklendirilen noktalar
  2. Toplanma alanları — yıldız / büyük marker
  3. Atama çizgileri (isteğe bağlı) — bina → alan bağlantısı
  4. Mahalle sınırları (isteğe bağlı)

Renk paleti: Her toplanma alanı için farklı renk, ≤20 alan desteklenir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import folium
import geopandas as gpd

# Merkezi popup escape helper'ları — tüm folium kullanan modüller buradan
# import etmeli (DRY + injection defense single source of truth).
from components.map_builder import safe_field as _esc
from components.map_builder import safe_hex_color


def _safe_color(color: str) -> str:
    """Geriye uyumlu sarmalayıcı; map_renderer'ın gri fallback'ı korur."""
    return safe_hex_color(color, fallback="#888888")

if TYPE_CHECKING:
    from src.optimizer.p_median import PMedianResult

# 20 renk paleti (Brewer + Material Design)
RENKLER = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
    "#dcbeff", "#9A6324", "#fffac8", "#800000", "#aaffc3",
    "#808000", "#ffd8b1", "#000075", "#a9a9a9", "#000000",
]

WGS84 = "EPSG:4326"


def render_atama_haritasi(
    sonuc: PMedianResult,
    binalar_gdf: gpd.GeoDataFrame,
    toplanma_gdf: gpd.GeoDataFrame,
    cizgiler: bool = False,
    mahalle_gdf: gpd.GeoDataFrame | None = None,
    max_cizgi: int = 500,
) -> folium.Map:
    """
    P-Median atama sonucunu Folium haritasına çizer.

    Parametreler:
        sonuc        : PMedianResult (p_median.coz() çıktısı)
        binalar_gdf  : bina GeoDataFrame (geometry=Point)
        toplanma_gdf : toplanma alanı GeoDataFrame (geometry=Point)
        cizgiler     : bina→alan bağlantı çizgisi göster (yavaşlatır)
        mahalle_gdf  : mahalle sınır GDF (opsiyonel)
        max_cizgi    : gösterilecek maksimum çizgi sayısı
    """
    b_gdf = binalar_gdf.to_crs(WGS84)
    t_gdf = toplanma_gdf.to_crs(WGS84)

    # Harita merkezi
    merkez_lat = b_gdf.geometry.y.mean()
    merkez_lon = b_gdf.geometry.x.mean()

    m = folium.Map(
        location=[merkez_lat, merkez_lon],
        zoom_start=13,
        tiles="CartoDB positron",
    )

    # ── Alan→Renk eşlemesi ────────────────────────────────────────────────────
    acik = sonuc.acik_alanlar
    renk_map: dict[int, str] = {
        j: RENKLER[k % len(RENKLER)] for k, j in enumerate(acik)
    }

    # ── Mahalle sınırları ─────────────────────────────────────────────────────
    if mahalle_gdf is not None and not mahalle_gdf.empty:
        mah = mahalle_gdf.to_crs(WGS84)
        folium.GeoJson(
            mah.__geo_interface__,
            name="Mahalleler",
            style_function=lambda _: {
                "fillColor":   "transparent",
                "color":       "#666",
                "weight":      1,
                "dashArray":   "4 4",
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["mahalle_adi"] if "mahalle_adi" in mah.columns else [],
                aliases=["Mahalle:"],
            ),
        ).add_to(m)

    # ── Catchment polygons (Voronoi-style) ──────────────────────────────
    # Her açık alan için ona atanan binaların CONVEX HULL'unu çiz; alan
    # rengiyle hafif transparent doldur. Voronoi'ye benzer "service region"
    # görselleştirmesi — tez Figure 5.6 için kullanılır.
    try:
        from shapely.geometry import MultiPoint
        catchment_grubu = folium.FeatureGroup(
            name="🎯 Service catchments (convex hull)", show=False,
        )
        for j_acik in acik:
            mask = sonuc.atamalar["alan_idx"] == j_acik
            assigned_idx = sonuc.atamalar.loc[mask, "bina_idx"].astype(int).tolist()
            # ≥3 bina lazım convex hull için (aksi halde line/point döner)
            valid_pts = [
                b_gdf.geometry.iloc[bi]
                for bi in assigned_idx
                if 0 <= bi < len(b_gdf)
            ]
            if len(valid_pts) < 3:
                continue
            hull = MultiPoint(valid_pts).convex_hull
            if hull.geom_type != "Polygon":
                continue
            renk = renk_map.get(j_acik, "#888")
            folium.GeoJson(
                hull.__geo_interface__,
                style_function=lambda _x, _c=renk: {
                    "fillColor":   _safe_color(_c),
                    "color":       _safe_color(_c),
                    "weight":      1.5,
                    "fillOpacity": 0.12,
                    "dashArray":   "5 3",
                },
                tooltip=f"Catchment area for {j_acik}",
            ).add_to(catchment_grubu)
        catchment_grubu.add_to(m)
    except Exception:
        # shapely yoksa veya hull hesabı patlarsa sessiz geç — kritik değil
        pass

    # ── Atama çizgileri ───────────────────────────────────────────────────────
    if cizgiler:
        cizgi_grubu = folium.FeatureGroup(name="Atama Çizgileri", show=False)
        atamalar = sonuc.atamalar

        # Çok fazla çizgi render'ı yavaşlatır
        orneklem = atamalar.sample(min(max_cizgi, len(atamalar)), random_state=42)

        for _, row in orneklem.iterrows():
            bi = int(row["bina_idx"])
            ji = int(row["alan_idx"])
            if bi >= len(b_gdf) or ji >= len(t_gdf):
                continue
            b_pt = b_gdf.geometry.iloc[bi]
            t_pt = t_gdf.geometry.iloc[ji]
            renk = renk_map.get(ji, "#888")
            folium.PolyLine(
                locations=[[b_pt.y, b_pt.x], [t_pt.y, t_pt.x]],
                color=renk,
                weight=0.8,
                opacity=0.4,
            ).add_to(cizgi_grubu)

        cizgi_grubu.add_to(m)

    # ── Bina katmanları (alan bazlı gruplar) ──────────────────────────────────
    bina_gruplari: dict[int, folium.FeatureGroup] = {}
    for k, j in enumerate(acik):
        ad = sonuc.acik_alan_adlari[k] if k < len(sonuc.acik_alan_adlari) else f"Alan {j}"
        fg = folium.FeatureGroup(name=f"🏠 {ad}", show=True)
        bina_gruplari[j] = fg
        fg.add_to(m)

    # Bina noktaları
    for _, row in sonuc.atamalar.iterrows():
        bi = int(row["bina_idx"])
        ji = int(row["alan_idx"])
        if bi >= len(b_gdf):
            continue
        pt = b_gdf.geometry.iloc[bi]
        renk = renk_map.get(ji, "#888")
        sure = float(row["sure_dk"])

        agirlik = row["agirlik"] if "agirlik" in row.index else 0
        bina_etiketi = row.get("bina_etiketi", f"Bina {bi + 1}")
        alan_adi = row.get("alan_adi", "")
        kalite = row.get("erisim_kalitesi", "")
        sure_araligi = row.get("sure_araligi", "")
        atama_ozeti = row.get("atama_ozeti", f"{bina_etiketi} → {alan_adi}")

        # P2.1: tüm dış kaynaklı string'ler html.escape ile kaçırılır.
        popup_html = (
            f"<div style='font-family:Arial,sans-serif;min-width:190px'>"
            f"<div style='font-weight:700;font-size:14px;margin-bottom:6px'>{_esc(bina_etiketi)}</div>"
            f"<div><b>Atama:</b> {_esc(atama_ozeti)}</div>"
            f"<div><b>Toplanma alanı:</b> {_esc(alan_adi)}</div>"
            f"<div><b>Yürüme süresi:</b> {sure:.1f} dk</div>"
            f"<div><b>Süre aralığı:</b> {_esc(sure_araligi)}</div>"
            f"<div><b>Erişim kalitesi:</b> {_esc(kalite)}</div>"
            f"<div><b>Mahalle:</b> {_esc(row.get('mahalle', ''))}</div>"
            f"<div><b>Ağırlık:</b> {float(agirlik):.0f}</div>"
            f"</div>"
        )

        folium.CircleMarker(
            location=[pt.y, pt.x],
            radius=4,
            color=_safe_color(renk),
            fill=True,
            fill_color=_safe_color(renk),
            fill_opacity=0.65,
            weight=0.5,
            popup=folium.Popup(popup_html, max_width=280),
            tooltip=f"{_esc(bina_etiketi)} → {_esc(alan_adi)} ({sure:.1f} dk)",
        ).add_to(bina_gruplari.get(ji, m))

    # ── Toplanma alanı markerları ─────────────────────────────────────────────
    toplanma_grubu = folium.FeatureGroup(name="⭐ Toplanma Alanları", show=True)

    for k, j in enumerate(acik):
        if j >= len(t_gdf):
            continue
        pt = t_gdf.geometry.iloc[j]
        ad = sonuc.acik_alan_adlari[k] if k < len(sonuc.acik_alan_adlari) else f"Alan {j}"
        renk = renk_map.get(j, "#888")

        # Bu alana atanan binaların istatistikleri
        mask = sonuc.atamalar["alan_idx"] == j
        alan_satir = sonuc.atamalar[mask]
        n_bina = len(alan_satir)
        ort_sure = alan_satir["sure_dk"].mean() if n_bina > 0 else 0
        max_sure = alan_satir["sure_dk"].max() if n_bina > 0 else 0
        toplam_agirlik = alan_satir["agirlik"].sum() if "agirlik" in alan_satir.columns else 0
        uzak_bina = int((alan_satir["sure_dk"] > 15).sum()) if n_bina > 0 else 0

        # P2.1: alan adı dış kaynaklı (kullanıcı upload / OSM) → escape.
        popup_html = (
            f"<div style='font-family:Arial,sans-serif;min-width:190px'>"
            f"<div style='font-weight:700;font-size:14px;margin-bottom:6px'>⭐ {_esc(ad)}</div>"
            f"<div><b>Atanan bina:</b> {n_bina:,}</div>"
            f"<div><b>Toplam ağırlık:</b> {float(toplam_agirlik):,.0f}</div>"
            f"<div><b>Ort. süre:</b> {ort_sure:.1f} dk</div>"
            f"<div><b>Max süre:</b> {max_sure:.1f} dk</div>"
            f"<div><b>15 dk üstü bina:</b> {uzak_bina:,}</div>"
            f"</div>"
        )

        folium.Marker(
            location=[pt.y, pt.x],
            popup=folium.Popup(popup_html, max_width=220),
            tooltip=f"⭐ {_esc(ad)}",
            icon=folium.Icon(
                color="white",
                icon_color=_safe_color(renk),
                icon="star",
                prefix="fa",
            ),
        ).add_to(toplanma_grubu)

    toplanma_grubu.add_to(m)

    # Tüm toplanma alanları (açık olmayan dahil) — gri
    kapali_grubu = folium.FeatureGroup(name="○ Kapalı Alanlar", show=False)
    kapali_idxler = [j for j in range(len(t_gdf)) if j not in acik]
    for j in kapali_idxler:
        pt = t_gdf.geometry.iloc[j]
        row_t = t_gdf.iloc[j]
        ad = str(row_t["ad"]) if "ad" in t_gdf.columns else f"Alan {j}"
        folium.CircleMarker(
            location=[pt.y, pt.x],
            radius=6,
            color="#aaa",
            fill=True,
            fill_color="#ccc",
            fill_opacity=0.5,
            weight=1,
            tooltip=f"○ {_esc(ad)}",
        ).add_to(kapali_grubu)
    kapali_grubu.add_to(m)

    # ── Legend ────────────────────────────────────────────────────────────────
    legend_html = _legend_html(acik, sonuc.acik_alan_adlari, renk_map)
    m.get_root().html.add_child(folium.Element(legend_html))

    # Katman kontrolü
    folium.LayerControl(collapsed=False).add_to(m)

    return m


def _legend_html(
    acik: list[int],
    adlar: list[str],
    renk_map: dict[int, str],
) -> str:
    satirlar = ""
    for k, j in enumerate(acik):
        ad   = adlar[k] if k < len(adlar) else f"Alan {j}"
        renk = _safe_color(renk_map.get(j, "#888"))
        satirlar += (
            f'<li style="margin:3px 0">'
            f'<span style="display:inline-block;width:12px;height:12px;'
            f'border-radius:50%;background:{renk};margin-right:6px"></span>'
            f'{_esc(ad)}</li>\n'
        )

    return f"""
    <div style="
        position: fixed;
        bottom: 30px; right: 10px;
        z-index: 9999;
        background: rgba(255,255,255,0.92);
        padding: 10px 14px;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
        font-size: 12px;
        max-height: 320px;
        overflow-y: auto;
        min-width: 160px;
    ">
    <b style="font-size:13px">⭐ Açık Alanlar ({len(acik)})</b>
    <ul style="list-style:none;padding:0;margin:6px 0 0 0">
    {satirlar}
    </ul>
    </div>
    """
