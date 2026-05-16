"""
Regresyon: optimizasyon UI metni çözücü davranışıyla hizalı olmalı
(bulgu #5, bulgu A).

Eski metinler:
  • "Connections exceeding this threshold receive a 2× penalty."
    → Gerçekte OD hücresi +inf, pair hard-exclude ediliyor; 2× penalty diye bir şey yok.
  • "Avg weight (m²)"
    → weight = tahmini nüfus (kişi), m² değil.

Bu test Optimization_Tool.py'nin o eski stringleri içermediğini
kontrol eder.
"""
from __future__ import annotations

from pathlib import Path


def _read_opt_tool() -> str:
    return Path("Optimization_Tool.py").read_text(encoding="utf-8")


def test_no_2x_penalty_copy():
    src = _read_opt_tool()
    assert "2× penalty" not in src, (
        "REGRESYON: 'Connections exceeding this threshold receive a 2× penalty.' "
        "ifadesi yanlış — OD cut-off gerçekte +inf/hard-exclude davranıyor."
    )
    assert "2x penalty" not in src.lower()


def test_avg_weight_label_is_not_m2():
    """`weight` tahmini nüfustur (kişi); KPI label'ı m² demez."""
    src = _read_opt_tool()
    assert "Avg weight (m²)" not in src, (
        "REGRESYON: KPI 'Avg weight (m²)' yanlış. weight = tahmini nüfus."
    )
    # Yeni label (en azından biri) olmalı
    assert (
        "Avg est. population" in src
        or "Avg building weight" in src
        or "Avg estimated population" in src
    )


def test_enforce_hard_limit_help_mentions_inf_not_penalty():
    """'Enforce hard walking-time limit' toggle'ının help text'i hard-exclude
    semantiğini yansıtmalı — eski penalty yaklaşımı YOK; aşan çiftler
    yasaklanır (hem EN 'forbidden' hem TR 'yasaklan' kabul)."""
    src = _read_opt_tool().lower()
    assert ("forbidden" in src) or ("yasaklan" in src), (
        "Toggle help text'inde hard-exclude semantiği (forbidden / yasaklan) geçmeli"
    )
