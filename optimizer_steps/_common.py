"""
optimizer_steps/_common.py — Paylaşılan helper'lar.

Sprint 1.5 audit 4.1: `_have()` ve `log_cb()` her step modülünde tek tek
tanımlanmıştı (DRY ihlali). Bu küçük modül her ikisini tek noktada tutar;
tüm step modülleri ve Optimization_Tool.py buradan import eder.

İçerik:
  • _have(key) → session_state'te key tanımlı ve None değil mi?
  • log_cb(msg) → log + UI session log paneline ekle (idempotent)
"""
from __future__ import annotations

import streamlit as st

from src.logger import get_logger

log = get_logger(__name__)


def _have(key: str) -> bool:
    """st.session_state'te `key` tanımlı VE None değilse True."""
    return st.session_state.get(key) is not None


def log_cb(msg: str) -> None:
    """Progress callback: logger'a yaz + Streamlit session log paneline ekle.
    'opt_logs' anahtarı yoksa otomatik başlatır (idempotent)."""
    log.info(msg)
    if "opt_logs" not in st.session_state:
        st.session_state["opt_logs"] = []
    st.session_state.opt_logs.append(msg)
