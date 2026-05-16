"""
src/pipelines/pipeline.py — Production Pipeline

Akış:
  ilçe + kategori seçimi
    → boundary çek
    → mahalle GeoJSON yükle
    → her kategori: OSM çek → post-filter → spatial enrich → classify → Türkçe çeviri
"""

from __future__ import annotations

from collections.abc import Callable

import geopandas as gpd
import pandas as pd

from src.config.category_registry import get_subcategory_code
from src.config.output_columns import get_export_columns
from src.config.settings import MAH_DIR_STR
from src.config.tag_rules import get_rule
from src.logger import get_logger
from src.models.results import PipelineSummary
from src.services.classification_service import run_classification_pipeline
from src.services.neighbourhood_loader import load_mahalleleri
from src.services.osm_service import (
    fetch_boundary,
    fetch_rule_based_features_with_boundary,
)
from src.services.post_filter import apply_religion_filter, apply_strict_post_filter
from src.services.spatial_service import enrich_with_spatial_features

log = get_logger(__name__)

WGS84 = "EPSG:4326"

# ── Din eşleşmesi gereken kurallar ───────────────────────────────────────────
RELIGION_FILTER_MAP = {
    "building_mosque":    "muslim",
    "building_church":    "christian",
    "building_synagogue": "jewish",
}

# ── Değer çeviri tabloları ────────────────────────────────────────────────────
BUILDING_TR = {
    "mosque":"Cami","church":"Kilise","synagogue":"Sinagog",
    "residential":"Konut","apartments":"Apartman","house":"Müstakil Ev",
    "detached":"Villa","terrace":"Sıra Ev","commercial":"Ticari Bina",
    "office":"Ofis Binası","retail":"AVM / Mağaza",
    "industrial":"Endüstriyel","warehouse":"Depo",
    "hospital":"Hastane Binası","school":"Okul Binası",
    "university":"Üniversite Binası","public":"Kamu Binası",
    "civic":"Belediye Binası","police":"Karakol",
    "fire_station":"İtfaiye","garage":"Garaj","garages":"Garaj",
    "parking":"Otopark","sports_hall":"Spor Salonu",
    "hotel":"Otel","dormitory":"Yurt / KYK","historic":"Tarihi Yapı",
    "supermarket":"Süpermarket","stadium":"Stadyum",
    "yes":"Belirsiz","":"-",
}
AMENITY_TR = {
    "hospital":"Hastane","clinic":"Klinik","doctors":"Aile Hekimi",
    "dentist":"Diş Hekimi","pharmacy":"Eczane","veterinary":"Veteriner",
    "school":"Okul","university":"Üniversite","kindergarten":"Anaokul",
    "library":"Kütüphane","place_of_worship":"İbadet Yeri",
    "townhall":"Belediye","police":"Karakol","fire_station":"İtfaiye",
    "parking":"Otopark","ferry_terminal":"Vapur İskelesi",
    "fuel":"Benzin İstasyonu","bank":"Banka","atm":"ATM",
    "post_office":"Postane","restaurant":"Restoran","cafe":"Kafe",
    "park":"Park","playground":"Oyun Alanı","grave_yard":"Mezarlık",
    "recycling":"Geri Dönüşüm","theatre":"Tiyatro","cinema":"Sinema",
    "arts_centre":"Kültür Merkezi","museum":"Müze",
    "assembly_point":"Toplanma Alanı",
    "emergency_assembly_point":"Toplanma Alanı","":"-",
}
RELIGION_TR   = {"muslim":"İslam","christian":"Hristiyanlık","jewish":"Yahudilik","":"-"}
CONFIDENCE_TR = {"high":"Yüksek","medium":"Orta","low":"Düşük","none":"Belirsiz"}
REASON_TR = {
    "strict_match":"Kesin eşleşme",
    "support_match":"Destekleyici eşleşme",
    "name_fallback":"Ad eşleşmesi",
    "no_match":"Eşleşme yok",
    "building_yes_mapped:strict_match":"yes → kesin kategori",
    "building_yes_mapped:support_match":"yes → destekleyici kategori",
    "building_yes_mapped:name_fallback":"yes → ad ile kategori",
}
OSM_ELEMENT_TR = {"node":"Nokta","way":"Yol/Alan","relation":"İlişki"}


def translate_values(df: pd.DataFrame) -> pd.DataFrame:
    """Ham OSM değerlerini Türkçeye çevirir."""
    result = df.copy()
    maps = {
        "Bina Tipi":      BUILDING_TR,
        "Tesis":          AMENITY_TR,
        "Din":            RELIGION_TR,
        "Güven":          CONFIDENCE_TR,
        "Eşleşme Nedeni": REASON_TR,
        "OSM Tipi":       OSM_ELEMENT_TR,
    }
    for col, mapping in maps.items():
        if col in result.columns:
            result[col] = (
                result[col].astype(str).str.strip().str.lower()
                .map(lambda x, m=mapping: m.get(x, x))
            )
    return result


def run_rule(
    boundary_gdf: gpd.GeoDataFrame,
    rule_code: str,
    mahalleleri: gpd.GeoDataFrame | None,
    progress_cb: Callable | None = None,
) -> dict:
    """
    Tek kural için tam pipeline:
    1. OSM feature çek
    2. Post-fetch filtre (din karışıklığı önle)
    3. Spatial enrich
    4. Classification
    5. Türkçe değer çevirisi
    """
    def cb(msg):
        log.info(msg)
        if progress_cb: progress_cb(msg)

    rule   = get_rule(rule_code)
    label  = rule.get("label_tr", rule_code)
    family = rule.get("export_family", "generic")

    cb(f"'{label}' çekiliyor...")

    gdf_raw = fetch_rule_based_features_with_boundary(
        boundary_gdf=boundary_gdf,
        rule_code=rule_code,
    )

    # P2.3: OSM kısmi başarısızlık bayrağını yakalayıp result dict'ine taşı.
    # Önceden gdf_raw.empty branch'inde attrs siliniyor, kullanıcı outage'i
    # "veri yok" sanıyordu. Artık partial_failure ve failed_tags her durumda
    # taşınır; UI bu bilgiyi log'a/uyarıya yansıtabilir.
    partial_failure_meta: dict = {}
    if hasattr(gdf_raw, "attrs") and gdf_raw.attrs.get("partial_failure"):
        partial_failure_meta = {
            "partial_failure":      True,
            "failed_tags":          list(gdf_raw.attrs.get("failed_tags", [])),
            "network_failed_count": int(gdf_raw.attrs.get("network_failed_count", 0)),
        }
        cb(
            f"⚠️ '{label}': bazı OSM sorguları başarısız "
            f"({len(partial_failure_meta['failed_tags'])} tag) — sonuç eksik olabilir"
        )

    if gdf_raw.empty:
        cb(f"'{label}': veri bulunamadı")
        return {
            "gdf": gpd.GeoDataFrame(),
            "df": pd.DataFrame(),
            "summary": {"total": 0},
            **partial_failure_meta,
        }

    cb(f"'{label}': {len(gdf_raw)} ham kayıt")

    # ── Post-fetch filtre ─────────────────────────────────────────────────────
    if rule_code in RELIGION_FILTER_MAP:
        gdf_raw = apply_religion_filter(gdf_raw, RELIGION_FILTER_MAP[rule_code])

    gdf_raw = apply_strict_post_filter(gdf_raw, rule_code)

    if gdf_raw.empty:
        cb(f"'{label}': filtre sonrası kayıt kalmadı")
        return {
            "gdf": gpd.GeoDataFrame(),
            "df": pd.DataFrame(),
            "summary": {"total": 0},
            **partial_failure_meta,
        }

    cb(f"'{label}': {len(gdf_raw)} kayıt (filtre sonrası)")

    # ── Spatial enrich ────────────────────────────────────────────────────────
    gdf_enriched, qc = enrich_with_spatial_features(
        gdf=gdf_raw,
        boundary_gdf=boundary_gdf,
        neighbourhoods_gdf=mahalleleri,
    )

    # ── Classification ────────────────────────────────────────────────────────
    # rule_codes=[rule_code] ile sınırla: tek kural için tüm TAG_RULES taranmasın
    # (kategori başına 5-10× hızlanma)
    clf     = run_classification_pipeline(gdf_enriched, rule_codes=[rule_code])
    # DÜZELTME: Sadece `resolved` (matched==True, güven≠"none") export/harita/KPI'ya
    # gitsin. `classified` unresolved satırları da içeriyordu → özet/sayım
    # tutarsızlığına yol açıyordu. Çözümlenemeyenler özette ayrı sayılır.
    gdf_cls   = clf["resolved"]
    gdf_unres = clf["unresolved"]
    summary   = clf["summary"]
    summary["qc"] = qc

    # ── Temiz DataFrame + çeviri ──────────────────────────────────────────────
    df_clean = _to_clean_dataframe(gdf_cls, family, rule_code, label)

    # Sınır dışı (komşu ilçeden sızmış) kayıt sayısını çıkar — analist için
    # özet bilgi. Asıl detay df_clean["Sınır Durumu"] kolonunda.
    n_outside = 0
    if "Sınır Durumu" in df_clean.columns:
        n_outside = int((df_clean["Sınır Durumu"] == "ilçe_dışı").sum())

    # Unresolved kayıtlar BİLEREK rapora dahil edilmez. Sebep: Overpass union
    # sorguları kategori sınırlarını sızdırabiliyor (ör. "Cami" sorgusu komşu
    # tag setleri yüzünden mezarlık node'larını da çekebiliyor); post_filter +
    # rule değerlendirmesi bunları matched=False olarak ayıklıyor. Onları
    # "Çözümsüz" etiketiyle aynı sayfaya koymak Cami sayfasını mezarlıkla
    # kirletirdi. Debug için gdf_unres yine return edilir; analist isterse
    # ayrı bir audit script'iyle inceleyebilir.
    msg = (
        f"'{label}': ✅ {len(df_clean)} çözümlü kayıt · "
        f"{len(gdf_unres)} kayıt rule eşleşmedi (kategori sınırı dışı, filtrelendi)"
    )
    if n_outside > 0:
        msg += (
            f" · ⚠️ {n_outside} kayıt İLÇE SINIRININ DIŞINDA "
            f"(muhtemelen komşu ilçeler — Excel'de 'Sınır Durumu' kolonundan "
            f"filtrelenebilir)"
        )
    cb(msg)

    return {
        "gdf":             gdf_cls,
        "df":              df_clean,
        "summary":         summary,
        "unresolved_gdf":  gdf_unres,   # debug / kalite analizi için
        "outside_count":   n_outside,   # boundary_status='ilçe_dışı' kayıt sayısı
        **partial_failure_meta,        # P2.3: kısmi OSM hata bilgisi
    }


def _to_clean_dataframe(
    gdf: gpd.GeoDataFrame,
    export_family: str,
    rule_code: str,
    label_tr: str,
) -> pd.DataFrame:
    if gdf.empty:
        return pd.DataFrame()

    g = gdf.copy()
    if "rule_code" not in g.columns: g["rule_code"] = rule_code
    if "label_tr"  not in g.columns: g["label_tr"]  = label_tr

    desired   = get_export_columns(export_family)
    available = [c for c in desired if c in g.columns]
    df = pd.DataFrame(g[available])

    TR_NAMES = {
        "element":"OSM Tipi","id":"OSM ID","name":"Ad",
        "category_group":"Kategori","subcategory":"Alt Kategori",
        "label_tr":"Kategori (TR)","rule_code":"Kural Kodu",
        "confidence":"Güven","reason":"Eşleşme Nedeni",
        "latitude":"Enlem","longitude":"Boylam","neighbourhood":"Mahalle",
        "boundary_status":"Sınır Durumu",
        "building":"Bina Tipi","amenity":"Tesis","shop":"Dükkan",
        "office":"Ofis","tourism":"Turizm","religion":"Din",
        "healthcare":"Sağlık Tipi","public_transport":"Toplu Taşıma",
        "railway":"Demiryolu","building:levels":"Kat Sayısı",
        "height":"Yükseklik (m)","footprint_m2":"Alan (m²)",
        # area_source: spatial_service.add_footprint_area provenance kolonu
        # ("measured" / "polygon_overlay" / "capacity_derived" / ""). Önceden
        # rename map'inde olmadığı için TR Excel'de ham `area_source` başlığıyla
        # gözüküyordu. components/translations.py round-trip'i de zaten
        # "Alan Kaynağı" → "Area Source" map'i bekliyor.
        "area_source":"Alan Kaynağı",
        "highway":"Yol Tipi","landuse":"Arazi","leisure":"Rekreasyon",
        "natural":"Doğal","bridge":"Köprü",
    }
    df = df.rename(columns={k: v for k, v in TR_NAMES.items() if k in df.columns})

    for col in ["Kat Sayısı","Kapasite"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "Yükseklik (m)" in df.columns:
        df["Yükseklik (m)"] = (
            df["Yükseklik (m)"].astype(str).str.extract(r"(\d+\.?\d*)")[0].astype(float)
        )
    if "Alan (m²)" in df.columns:
        df["Alan (m²)"] = pd.to_numeric(df["Alan (m²)"], errors="coerce").round(1)

    df = df.dropna(axis=1, how="all")
    df = translate_values(df)
    df = _ensure_core_columns(df)
    return df.reset_index(drop=True)


def _ensure_core_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Optimizasyon toolu ve genel kullanım için zorunlu sütunların
    her zaman mevcut olmasını garanti eder.
    Eksik sütunlar boş/NaN ile eklenir — veri kaybı olmaz.
    """
    # Türkçe sütun adlarına göre (rename sonrası)
    CORE = {
        "Enlem":      float,
        "Boylam":     float,
        "Mahalle":    str,
        "Alan (m²)":  float,
        "Kat Sayısı": float,
    }
    for col, dtype in CORE.items():
        if col not in df.columns:
            df[col] = pd.Series(dtype=dtype)
    return df


def run_pipeline(
    ilce: str,
    secimler: list[tuple[str, str]],
    data_dir: str = MAH_DIR_STR,
    progress_cb: Callable | None = None,
) -> dict:
    """Tam pipeline."""
    def cb(msg):
        log.info(msg)
        if progress_cb: progress_cb(msg)

    cb(f"Boundary çekiliyor: {ilce}")
    try:
        boundary = fetch_boundary(f"{ilce}, İstanbul, Türkiye")
    except Exception as e:
        raise RuntimeError(
            f"'{ilce}' için sınır çekilemedi. "
            f"İlçe adını kontrol edin veya internet bağlantısını deneyin. "
            f"Hata: {e}"
        ) from e

    cb(f"Mahalle yükleniyor: {ilce}")
    mahalleleri = load_mahalleleri(ilce, data_dir)
    if mahalleleri.empty:
        cb(f"⚠️ {ilce} mahalle verisi bulunamadı — mahalle ataması yapılamayacak")

    results = {}
    # P2.4: Kategori bazlı hataları yutup `results` boş dönmek karar destek
    # aracında "tam başarısızlık" durumunu "veri yok" gibi gösteriyordu.
    # Hata bilgisini `failed_categories` ile result contract'ına taşıyıp UI
    # tam-başarısızlık ile veri-yok durumlarını ayırt edebilsin.
    failed_categories: list[dict] = []
    requested_count = len(secimler)
    n               = requested_count

    for i, (cat_key, sub_key) in enumerate(secimler, 1):
        try:
            try:
                rule_code = get_subcategory_code(cat_key, sub_key)
            except ValueError as ve:
                # category_registry.get_subcategory_code geçersiz kategori/alt
                # kategori için ValueError fırlatır. Bunu generic Exception
                # bloğuna düşürmek yerine "rule_missing" olarak ayrı sınıflandır
                # — UI tarafında "kural kodu bulunamadı, atlanıyor" mesajı
                # bağlantı hatasından daha anlamlı.
                cb(f"⚠️ [{i}/{n}] {cat_key}/{sub_key}: kural kodu bulunamadı, atlanıyor ({ve})")
                failed_categories.append({
                    "cat_key": cat_key, "sub_key": sub_key,
                    "error_type": "rule_missing",
                    "message": str(ve),
                })
                continue

            rule           = get_rule(rule_code)
            label          = rule.get("label_tr", rule_code)
            category_group = rule.get("category_group", cat_key)
            cb(f"[{i}/{n}] {label}")

            result = run_rule(
                boundary_gdf=boundary,
                rule_code=rule_code,
                mahalleleri=mahalleleri if not mahalleleri.empty else None,
                progress_cb=progress_cb,
            )
            # DÜZELTME: Anahtar olarak `rule_code` kullan (benzersiz).
            # Önceki hali (`label`) birden fazla kuralın aynı label_tr'yi
            # paylaştığı durumlarda (ör. building_police + infrastructure_police
            # → "Karakol") sessizce sonuçları birbirinin üzerine yazıyordu.
            # Consumer'lar display için `res["label_tr"]`, renk/filtre için
            # `res["category_group"]` kullanır.
            result["label_tr"]       = label
            result["category_group"] = category_group
            result["rule_code"]      = rule_code
            results[rule_code]       = result

        except RuntimeError as e:
            # Overpass bağlantı hatası — kullanıcıya anlamlı mesaj
            log.error(f"OSM çekim hatası [{cat_key}/{sub_key}]: {e}")
            cb(f"❌ [{i}/{n}] {cat_key}/{sub_key}: bağlantı hatası — {e}")
            failed_categories.append({
                "cat_key": cat_key, "sub_key": sub_key,
                "error_type": "RuntimeError",
                "message": str(e),
            })
        except Exception as e:
            log.error(f"Beklenmedik hata [{cat_key}/{sub_key}]: {e}", exc_info=True)
            cb(f"❌ [{i}/{n}] {cat_key}/{sub_key}: {type(e).__name__} — {e}")
            failed_categories.append({
                "cat_key": cat_key, "sub_key": sub_key,
                "error_type": type(e).__name__,
                "message": str(e),
            })


    # Toplam özet istatistik
    total_records = sum(
        v.get("summary", {}).get("total", 0)
        for v in results.values()
    )
    resolved_count = sum(
        v.get("summary", {}).get("resolved_count", 0)
        for v in results.values()
    )
    pipeline_summary = PipelineSummary(
        total=total_records,
        resolved_count=resolved_count,
        unresolved_count=total_records - resolved_count,
        resolution_rate=resolved_count / total_records if total_records > 0 else 0.0,
    )

    # P2.4: tam başarısızlık durumunu UI'da yeşil "Completed" olarak göstermemek
    # için yapısal sinyaller ekliyoruz.
    error_count   = len(failed_categories)
    success_count = requested_count - error_count
    all_failed    = (requested_count > 0 and success_count == 0)

    return {
        # P1.1: ilce'yi result dict'ine taşı. Eskiden yoktu →
        # components.state.get_district() pipeline_result["ilce"]'yi
        # bulamayıp session'daki (potansiyel olarak DEĞİŞMİŞ) seçili ilçeye
        # düşüyordu. Sonuç: kullanıcı veriyi Kadıköy için çektikten sonra
        # sidebar'dan Beykoz seçip Map sayfasına geçince eski Kadıköy verisi
        # "Beykoz" etiketiyle görünüyordu.
        "ilce":               ilce,
        "boundary":           boundary,
        "mahalleleri":        mahalleleri,
        "results":            results,
        "summary":            pipeline_summary,
        # P2.4: failure semantics
        "requested_count":    requested_count,
        "success_count":      success_count,
        "error_count":        error_count,
        "failed_categories":  failed_categories,
        "all_failed":         all_failed,
    }
