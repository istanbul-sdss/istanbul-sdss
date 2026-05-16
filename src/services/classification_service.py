"""
src/services/classification_service.py

Düzeltmeler:
1. apply_building_yes_mapping: matched + score da overwrite ediliyor
2. run_classification_pipeline: map_rule_to_category_fields building=yes
   SONRASI çağrılıyor
3. split_resolved_unresolved: matched==False kriteri eklendi
4. rename bloğunda gereksiz self-mapping kaldırıldı
5. mask_yes artık result üzerinden hesaplanıyor
"""

from __future__ import annotations

import pandas as pd

from src.config.tag_rules import TAG_RULES
from src.services.rule_engine import (
    append_building_yes_mapping_columns,
    append_rule_match_columns,
    is_building_yes_record,
)


def map_rule_to_category_fields(df: pd.DataFrame) -> pd.DataFrame:
    """
    Güncel rule_code üzerinden category_group, subcategory, label_tr üretir.
    Her zaman FINAL rule_code kararından SONRA çağrılmalı.
    """
    result = df.copy()

    def get_field(rule_code, field):
        if rule_code and rule_code in TAG_RULES:
            return TAG_RULES[rule_code].get(field)
        return None

    result["category_group"] = result["rule_code"].apply(lambda x: get_field(x, "category_group"))
    result["subcategory"]    = result["rule_code"].apply(lambda x: get_field(x, "subcategory"))
    result["label_tr"]       = result["rule_code"].apply(lambda x: get_field(x, "label_tr"))
    return result


def classify_dataframe(df: pd.DataFrame, rule_codes: list[str] | None = None) -> pd.DataFrame:
    """
    DataFrame'e rule-based classification uygular.
    map_rule_to_category_fields burada çağrılmıyor — final karar
    building=yes sonrası run_classification_pipeline içinde merkezi yapılıyor.
    """
    if df.empty:
        return df.copy()

    result = append_rule_match_columns(df, rule_codes=rule_codes)

    # Gereksiz self-mapping ("rule_code": "rule_code") kaldırıldı
    result = result.rename(columns={
        "rule_matched":    "matched",
        "rule_score":      "score",
        "rule_confidence": "confidence",
        "rule_reason":     "reason",
    })
    return result


def apply_building_yes_mapping(df: pd.DataFrame) -> pd.DataFrame:
    """
    building=yes kayıtları için mapping uygular.

    DÜZELTME: Önceki versiyonda matched ve score overwrite edilmiyordu.
    Şimdi tüm ilgili kolonlar güncelleniyor.
    mask_yes artık result üzerinden hesaplanıyor (index güvenliği).
    """
    if df.empty:
        return df.copy()

    result  = append_building_yes_mapping_columns(df)
    mask_yes = result.apply(is_building_yes_record, axis=1)   # result'tan al

    if not mask_yes.any():
        return result

    result.loc[mask_yes, "rule_code"]  = result.loc[mask_yes, "yes_map_code"]
    result.loc[mask_yes, "matched"]    = result.loc[mask_yes, "yes_map_matched"]
    result.loc[mask_yes, "score"]      = result.loc[mask_yes, "yes_map_score"]
    result.loc[mask_yes, "confidence"] = result.loc[mask_yes, "yes_map_confidence"]
    result.loc[mask_yes, "reason"]     = result.loc[mask_yes, "yes_map_reason"]
    return result


def split_resolved_unresolved(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    DÜZELTME: matched==False kriteri eklendi.
    Önceden sadece rule_code ve confidence kontrolü vardı.
    """
    if df.empty:
        return df.copy(), df.copy()

    unresolved_mask = (
        df["rule_code"].isna()
        | (df["rule_code"] == "building_yes_unresolved")
        | (df["confidence"] == "none")
    )
    if "matched" in df.columns:
        unresolved_mask = unresolved_mask | (df["matched"] == False)  # noqa: E712

    return df[~unresolved_mask].copy(), df[unresolved_mask].copy()


def run_classification_pipeline(
    df: pd.DataFrame,
    rule_codes: list[str] | None = None,
    handle_building_yes: bool = True,
) -> dict:
    """
    DÜZELTME — Doğru sıra:
    1. Normal classification
    2. building=yes mapping   (rule_code değişebilir)
    3. map_rule_to_category_fields  ← FINAL rule_code'a göre
    4. resolved/unresolved split
    """
    if df.empty:
        return {
            "classified": df.copy(), "resolved": df.copy(),
            "unresolved": df.copy(), "summary": {"total": 0},
        }

    classified = classify_dataframe(df, rule_codes=rule_codes)

    if handle_building_yes:
        classified = apply_building_yes_mapping(classified)

    # Kategori alanları SONRA map ediliyor — building=yes mapping kararından sonra
    classified = map_rule_to_category_fields(classified)

    resolved, unresolved = split_resolved_unresolved(classified)

    n = len(classified)
    summary = {
        "total": n, "resolved_count": len(resolved),
        "unresolved_count": len(unresolved),
        "resolution_rate": len(resolved) / n if n > 0 else 0.0,
    }

    return {"classified": classified, "resolved": resolved,
            "unresolved": unresolved, "summary": summary}
