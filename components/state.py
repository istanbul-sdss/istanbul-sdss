"""
components/state.py — Centralized session state helpers.

Keeps the keys used by st.session_state in one place so pages stay
consistent and don't drift.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

# Canonical session-state keys
KEY_PIPELINE_RESULT = "pipeline_result"   # dict returned by run_pipeline
KEY_EXCEL_PATH      = "excel_path"        # path to exported Excel file
KEY_SELECTED_DISTRICT = "selected_district"
KEY_SELECTED_CATEGORIES = "selected_categories"   # list[tuple[str, str]]


_DEFAULTS: dict[str, Any] = {
    KEY_PIPELINE_RESULT:    None,
    KEY_EXCEL_PATH:         None,
    KEY_SELECTED_DISTRICT:  "Kadıköy",
    KEY_SELECTED_CATEGORIES: [],
}


def init_state() -> None:
    """Initialize session_state defaults. Safe to call on every page."""
    for k, v in _DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v


def has_data() -> bool:
    """Return True if pipeline has been run and produced results."""
    pr = st.session_state.get(KEY_PIPELINE_RESULT)
    if not pr:
        return False
    results = pr.get("results", {}) or {}
    return any(not v["df"].empty for v in results.values())


def get_nonempty_results() -> dict:
    """Return only categories that produced non-empty DataFrames."""
    pr = st.session_state.get(KEY_PIPELINE_RESULT) or {}
    results = pr.get("results", {}) or {}
    return {k: v for k, v in results.items() if not v["df"].empty}


def get_district() -> str | None:
    """Return the district of the last pipeline run (if any)."""
    pr = st.session_state.get(KEY_PIPELINE_RESULT)
    if pr:
        return pr.get("ilce") or st.session_state.get(KEY_SELECTED_DISTRICT)
    return st.session_state.get(KEY_SELECTED_DISTRICT)


def get_boundary():
    """Return the district boundary GeoDataFrame (if present)."""
    pr = st.session_state.get(KEY_PIPELINE_RESULT) or {}
    return pr.get("boundary")


def clear_results() -> None:
    """Reset pipeline output state."""
    st.session_state[KEY_PIPELINE_RESULT] = None
    st.session_state[KEY_EXCEL_PATH] = None
