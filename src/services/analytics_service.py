from __future__ import annotations

import pandas as pd

EMPTY_LIKE_VALUES = {"", "nan", "none", "null"}


def is_meaningfully_filled(series: pd.Series) -> pd.Series:
    normalized = series.astype(str).str.strip().str.lower()
    return series.notna() & normalized.ne("") & ~normalized.isin(EMPTY_LIKE_VALUES)


def summarize_classification(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "rule_code" not in df.columns:
        return pd.DataFrame(columns=["rule_code", "count"])

    return (
        df.groupby("rule_code", dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
        .reset_index(drop=True)
    )


def extract_tag_frequency(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["tag", "non_null_count", "coverage_ratio"])

    rows = []
    total = len(df)

    for col in df.columns:
        if col == "geometry":
            continue

        filled = is_meaningfully_filled(df[col])
        count = int(filled.sum())

        if count > 0:
            rows.append(
                {
                    "tag": col,
                    "non_null_count": count,
                    "coverage_ratio": round(count / total, 4) if total > 0 else 0.0,
                }
            )

    if not rows:
        return pd.DataFrame(columns=["tag", "non_null_count", "coverage_ratio"])

    return (
        pd.DataFrame(rows)
        .sort_values(["non_null_count", "tag"], ascending=[False, True])
        .reset_index(drop=True)
    )


def summarize_unresolved_yes(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["building", "name", "count"])

    temp = df.copy()

    if "building" not in temp.columns:
        temp["building"] = None
    if "name" not in temp.columns:
        temp["name"] = None

    return (
        temp.groupby(["building", "name"], dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
        .reset_index(drop=True)
    )
