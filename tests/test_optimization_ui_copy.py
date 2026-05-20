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
    # Domain config eklendiğinden bu testin scope'u genişledi: yanlış label
    # ana modülde bulunmadığı gibi, domain_config.py'da da bulunmamalı.
    domain_cfg = Path("components/domain_config.py").read_text(encoding="utf-8")
    assert "Avg weight (m²)" not in src, (
        "REGRESYON: KPI 'Avg weight (m²)' yanlış. weight = tahmini nüfus."
    )
    assert "Avg weight (m²)" not in domain_cfg, (
        "REGRESYON: domain_config.py'da 'Avg weight (m²)' yanlış."
    )
    # Earthquake domain weight_label "Avg est. population" — domain_config'de tanımlı
    assert "Avg est. population" in domain_cfg, (
        "Earthquake DomainConfig.weight_label 'Avg est. population' olmalı"
    )
    # Optimization_Tool.py artık `domain.weight_label` kullanmalı (string'i
    # hardcoded yazmak yerine).
    assert "domain.weight_label" in src, (
        "Optimization_Tool.py KPI label için domain.weight_label kullanmalı"
    )


def test_enforce_hard_limit_help_mentions_inf_not_penalty():
    """'Enforce hard walking-time limit' toggle'ının help text'i hard-exclude
    semantiğini yansıtmalı — eski penalty yaklaşımı YOK; aşan çiftler
    yasaklanır (hem EN 'forbidden' hem TR 'yasaklan' kabul)."""
    src = _read_opt_tool().lower()
    assert ("forbidden" in src) or ("yasaklan" in src), (
        "Toggle help text'inde hard-exclude semantiği (forbidden / yasaklan) geçmeli"
    )
