"""
tests/test_golden_kadikoy.py

İki katmanlı test:
  1. Offline core: golden_runner CSV parsing + metrik hesabı
     (her zaman koşar, network'siz, fixture pool ile mock).
  2. Live integration: gerçek Overpass çağrısıyla Kadıköy üzerinde ölç.
     Default'ta SKIP — env var NAME_LOOKUP_GOLDEN=1 ile aktive olur.

Eşik:
  Top-1 ≥ 70% (Kadıköy template <TODO>'larla başladığı için ilk
  koşumda ölçülmez; satırlar doldurulduğunda gerçek baseline çıkar.)
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from src.config.name_lookup_rules import tokenize_lite
from src.services.name_lookup_service import (
    UniversalPool,
    _UniversalCandidate,
    match_mixed_list,
)
from tests.golden_runner import (
    GOLDEN_DIR,
    compute_metrics,
    format_report,
    load_golden,
)

KADIKOY_CSV = GOLDEN_DIR / "name_lookup_kadikoy.csv"


# ─────────────────────────────────────────────────────────────────────────────
# Offline core — schema + parsing + metric calculation
# ─────────────────────────────────────────────────────────────────────────────
def test_kadikoy_csv_exists():
    assert KADIKOY_CSV.exists(), "Kadıköy golden CSV mevcut olmalı"


def test_kadikoy_csv_parses_with_required_columns():
    rows = load_golden(KADIKOY_CSV)
    assert len(rows) > 0
    assert all(r.input_name for r in rows if r.input_name not in ("", "nan"))
    # En az birkaç farklı status temsil edilmeli (kalite için çeşitlilik)
    statuses = {r.expected_status for r in rows}
    assert "Matched" in statuses
    assert "Not found" in statuses


def test_todo_placeholder_marks_row_as_incomplete():
    rows = load_golden(KADIKOY_CSV)
    todo_rows = [r for r in rows if not r.is_complete and r.expected_status == "Matched"]
    # Template <TODO>'larla başladığı için en az bir tane bulunmalı
    assert len(todo_rows) > 0, "<TODO> placeholder'ları işaretlenmeli"


def test_metrics_computation_against_synthetic_pool():
    """
    compute_metrics + match_mixed_list pipeline sözleşmesi: synthetic pool
    + golden satırı ile pipeline'ın doğru sayıları ürettiğini doğrula.
    Network gerektirmez.
    """
    # Tek bilinen senaryo: "Şifa Eczanesi" Caferağa'da, OSM ID 999.
    cands = [
        _UniversalCandidate(
            lite_variants=[(set(tokenize_lite("Şifa Eczanesi")),
                            " ".join(sorted(tokenize_lite("Şifa Eczanesi"))))],
            raw_name_variants=["Şifa Eczanesi"],
            payload={
                "Ad": "Şifa Eczanesi",
                "OSM ID": 999,
                "OSM Tipi": "Nokta",
                "Mahalle": "Caferağa Mahallesi",
                "Sınır Durumu": "ilçe_içi",
                "amenity": "pharmacy",
            },
        ),
    ]
    pool = UniversalPool(
        ilce="Kadıköy", candidates=cands,
        rule_token_cache={}, place_stopwords=set(),
    )
    # Tek satırlık synthetic golden
    from tests.golden_runner import GoldenRow
    golden = [
        GoldenRow(
            input_name="Şifa Eczanesi",
            input_neighborhood="Caferağa",
            expected_status="Matched",
            expected_osm_ids=["999"],
            expected_category="amenity=pharmacy",
            notes="synthetic",
            is_complete=True,
        ),
    ]
    result = match_mixed_list(pool, names=["Şifa Eczanesi"], neighborhoods=["Caferağa"])
    metrics = compute_metrics(golden, result)
    assert metrics.matched_total == 1
    assert metrics.top1_correct == 1
    assert metrics.top1_pct == 100.0


def test_format_report_returns_human_readable_string():
    """Rapor formatı insan-okunur ve boş set'te bile çökmemeli."""
    from tests.golden_runner import GoldenMetrics
    m = GoldenMetrics(
        total_rows=10, skipped_todo=10, measured=0,
        top1_correct=0, top3_correct=0, matched_total=0,
        not_found_correct=0, not_found_total=0,
    )
    txt = format_report(m, "Kadıköy")
    assert "Kadıköy" in txt
    assert "Top-1" in txt
    assert "Top-3" in txt


# ─────────────────────────────────────────────────────────────────────────────
# Live integration — opt-in via env var, network'lü
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(
    os.getenv("NAME_LOOKUP_GOLDEN") != "1",
    reason="Live golden run requires Overpass network; set NAME_LOOKUP_GOLDEN=1 to enable",
)
def test_kadikoy_top1_meets_threshold():
    """
    Gerçek Overpass çağrısıyla Kadıköy üzerinde golden ölçer.
    `expected_osm_id` <TODO> olan satırlar atlanır; doldurulduğunda
    eşik kontrolü etkin olur.

    İlk hedef eşik: Top-1 ≥ 70% (template doldurulunca yeniden ayarla).
    """
    from tests.golden_runner import run_against_district

    metrics, result = run_against_district(KADIKOY_CSV, "Kadıköy")
    print(format_report(metrics, "Kadıköy"))   # pytest -s ile görünür

    if metrics.matched_total == 0:
        pytest.skip("Henüz <TODO>'lar doldurulmadı — ölçüm yapılamadı")

    assert metrics.top1_pct >= 70.0, (
        f"Top-1 doğruluk eşik altında: {metrics.top1_pct:.1f}% "
        f"({metrics.top1_correct}/{metrics.matched_total})"
    )
