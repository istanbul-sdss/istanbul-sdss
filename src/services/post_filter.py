"""
src/services/post_filter.py

Pipeline çekme sonrası uygulanan katı filtre.

Problem: osmnx her query_tags sorgusunu ayrı çekip union yapıyor.
Örnek: {"amenity":"place_of_worship"} → kiliseler de geliyor.
Bu modül, sonuçları strict_tags + support_tags kurallarına göre filtreler.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

from src.config.tag_rules import TAG_RULES
from src.logger import get_logger

log = get_logger(__name__)


def _normalize(val) -> str:
    if pd.isna(val) or val is None:
        return ""
    return str(val).strip().lower()


def _row_matches_single_strict_dict(row: pd.Series, strict_tags: dict) -> bool:
    """Tek bir strict_tags dict'i için AND kontrolü."""
    if not strict_tags:
        return True
    for key, expected in strict_tags.items():
        actual = _normalize(row.get(key, ""))
        if expected is True:
            if not actual:
                return False
        else:
            if actual != _normalize(expected):
                return False
    return True


def _row_matches_strict(row: pd.Series, strict_tags) -> bool:
    """
    Satır strict_tags koşullarını sağlıyor mu?

    strict_tags artık iki biçimi destekler:
      • dict             → AND (tüm anahtarlar eşleşmeli)
      • list[dict]       → OR-of-AND (herhangi bir dict tam eşleşirse yeter)

    Bu senkronizasyon rule_engine.match_strict_tags() ile paralel; aksi halde
    list biçimi kullanan rule'larda (assembly_point gibi) post_filter adımı
    AttributeError: 'list' object has no attribute 'items' ile çakılır.
    """
    if not strict_tags:
        return True  # strict_tags boşsa filtre yok
    if isinstance(strict_tags, dict):
        return _row_matches_single_strict_dict(row, strict_tags)
    if isinstance(strict_tags, (list, tuple)):
        return any(
            isinstance(opt, dict) and _row_matches_single_strict_dict(row, opt)
            for opt in strict_tags
        )
    # Bilinmeyen tür: dokunma, tutmayı tercih et (geriye dönük güvenlik).
    return True


def _row_matches_support(row: pd.Series, support_tags: dict) -> bool:
    """En az bir support_tag eşleşiyor mu?"""
    if not support_tags:
        return False
    for key, expected in support_tags.items():
        actual = _normalize(row.get(key, ""))
        if (expected is True and actual) or (actual == _normalize(expected)):
            return True
    return False


def apply_strict_post_filter(
    gdf: gpd.GeoDataFrame,
    rule_code: str,
) -> gpd.GeoDataFrame:
    """
    Query sonrası strict filtre uygular.

    Bir kayıt şu koşullardan EN AZ BİRİNİ sağlamalı:
    1. strict_tags TÜMÜ eşleşiyor (AND)
    2. Herhangi bir query_tag'den gelen birincil anahtar eşleşiyor

    Hiçbiri eşleşmiyorsa kayıt çıkarılır.
    """
    if gdf.empty:
        return gdf

    rule = TAG_RULES.get(rule_code, {})
    strict_tags  = rule.get("strict_tags", {})
    support_tags = rule.get("support_tags", {})
    query_tags   = rule.get("query_tags", [])

    # Tüm query_tag'lerden birincil anahtar-değer çiftleri
    primary_checks = []
    for qt in query_tags:
        if isinstance(qt, dict):
            for k, v in qt.items():
                primary_checks.append((k, v))

    def keep_row(row: pd.Series) -> bool:
        # 1. strict_tags tam eşleşme
        if strict_tags and _row_matches_strict(row, strict_tags):
            return True
        # 2. Herhangi bir query_tag birincil koşulu
        for key, expected in primary_checks:
            actual = _normalize(row.get(key, ""))
            if (expected is True and actual) or (
                isinstance(expected, str) and actual == _normalize(expected)
            ):
                return True
        # 3. Support tag desteği var ve strict sağlanamıyorsa bile tut
        return bool(support_tags and _row_matches_support(row, support_tags))

    # Önce mevcut sütunları belirle (tag sütunları)
    tag_cols = [c for c in gdf.columns
                if c not in ["geometry", "kategori", "ilce", "mahalle",
                              "latitude", "longitude", "footprint_m2",
                              "rep_point", "osm_element", "osm_id"]]

    # GeoDataFrame üzerinde filtre uygula
    df_tags = gdf[tag_cols] if tag_cols else gdf.select_dtypes(exclude="geometry")

    mask = df_tags.apply(keep_row, axis=1)
    filtered = gdf[mask.values].copy().reset_index(drop=True)

    removed = len(gdf) - len(filtered)
    if removed > 0:
        rule_label = rule.get("label_tr", rule_code)
        log.info(
            f"post_filter '{rule_label}': "
            f"{len(gdf)} → {len(filtered)} kayıt "
            f"({removed} yanlış eşleşme temizlendi)"
        )

    return filtered


def apply_religion_filter(
    gdf: gpd.GeoDataFrame,
    expected_religion: str,
) -> gpd.GeoDataFrame:
    """
    Dini yapılar için özel filtre.
    expected_religion: "muslim", "christian", "jewish" vb.

    'religion' sütunu yanlış olan veya building tipi uyumsuz
    olanları atar.

    Sadece dini yapı kuralları için çağrılır.
    """
    if gdf.empty or "religion" not in gdf.columns:
        return gdf

    def keep(row):
        rel = _normalize(row.get("religion", ""))
        # Dini bilgi yoksa (boş) → keep (building=mosque varsa zaten geldi)
        if not rel:
            return True
        # Dini bilgi var ve beklenenle eşleşiyor → keep; farklı din → at.
        return rel == expected_religion

    mask = gdf.apply(keep, axis=1)
    filtered = gdf[mask.values].copy().reset_index(drop=True)

    removed = len(gdf) - len(filtered)
    if removed > 0:
        log.info(
            f"post_filter din filtresi ({expected_religion}): "
            f"{removed} yanlış din kaydı temizlendi"
        )
    return filtered
