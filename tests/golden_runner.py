"""
tests/golden_runner.py

Name Lookup için "kalite ölçüm" CLI'ı + reusable helper'lar.

Kullanım (CLI):
    python -m tests.golden_runner --district Kadıköy
    python -m tests.golden_runner --district Kadıköy --csv data/golden/name_lookup_kadikoy.csv

Kullanım (pytest):
    from tests.golden_runner import load_golden, compute_metrics

NOT — Network: prepare_universal_pool Overpass'ı çağırır. CI'da değil,
elle çalıştırılması beklenir. pytest entegrasyonu için:
    NAME_LOOKUP_GOLDEN=1 pytest tests/test_golden_kadikoy.py
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.services.name_lookup_service import (
    MIXED_DEFAULT_THRESHOLD,
    MixedLookupResult,
    UniversalPool,
    match_mixed_list,
    prepare_universal_pool,
)

GOLDEN_DIR = _ROOT / "data" / "golden"
TODO_PLACEHOLDER = "<TODO>"


# ─────────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class GoldenRow:
    input_name:         str
    input_neighborhood: str | None
    expected_status:    str
    expected_osm_ids:   list[str]      # 'A|B' → ['A', 'B']; '' → []
    expected_category:  str
    notes:              str
    is_complete:        bool           # False if expected_osm_id is <TODO>


def load_golden(csv_path: Path) -> list[GoldenRow]:
    """CSV'yi oku, GoldenRow listesine çevir. <TODO> placeholder'ları işaretle."""
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    expected_cols = {
        "input_name", "input_neighborhood", "expected_status",
        "expected_osm_id", "expected_category", "notes",
    }
    missing = expected_cols - set(df.columns)
    if missing:
        raise ValueError(f"Eksik kolonlar: {missing}")
    out: list[GoldenRow] = []
    for _, row in df.iterrows():
        raw_id = str(row["expected_osm_id"]).strip()
        is_todo = raw_id == TODO_PLACEHOLDER or raw_id.lower() == "<todo>"
        ids = [] if (not raw_id or is_todo) else raw_id.split("|")
        nbh = str(row["input_neighborhood"]).strip()
        out.append(GoldenRow(
            input_name=str(row["input_name"]).strip(),
            input_neighborhood=nbh if nbh else None,
            expected_status=str(row["expected_status"]).strip(),
            expected_osm_ids=ids,
            expected_category=str(row["expected_category"]).strip(),
            notes=str(row["notes"]).strip(),
            is_complete=(not is_todo) and (
                row["expected_status"] != "Matched" or bool(ids)
            ),
        ))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class GoldenMetrics:
    total_rows:        int
    skipped_todo:      int           # Beklenen ID'si <TODO> olduğu için ölçülmedi
    measured:          int           # Ölçüme dahil olan satır sayısı

    top1_correct:      int           # best_match.OSM ID == expected (Matched satırlar)
    top3_correct:      int           # expected, top-3 aday içinde
    matched_total:     int           # expected_status="Matched" satır sayısı

    not_found_correct: int           # expected="Not found" iken sistem de NF dedi
    not_found_total:   int

    @property
    def top1_pct(self) -> float:
        return (self.top1_correct / self.matched_total * 100.0) if self.matched_total else 0.0

    @property
    def top3_pct(self) -> float:
        return (self.top3_correct / self.matched_total * 100.0) if self.matched_total else 0.0

    @property
    def nf_pct(self) -> float:
        return (self.not_found_correct / self.not_found_total * 100.0) if self.not_found_total else 0.0


def _ids_match(actual: str | int | None, expected_ids: list[str]) -> bool:
    if actual is None or pd.isna(actual):
        return False
    actual_s = str(actual).strip()
    return actual_s in expected_ids


def _alt_match_ids_from_alts_str(alts_str: str) -> list[str]:
    """
    "Şifa Eczanesi (skor=85) · Aile (skor=78)" formatından OSM ID
    çıkaramayız (alt'lar isim + skor olarak yazılıyor). Bu yüzden top-3
    için ayrı bir mekanizma gerek; mevcut çıktıda alt OSM ID'leri yok.

    Bu helper bilinçli olarak şu an boş döner; top-3 metriği "best_match
    veya alts string'inde isim geçiyor mu" yumuşak kontrolüne düşer.
    """
    return []


def compute_metrics(
    golden: list[GoldenRow],
    result: MixedLookupResult,
) -> GoldenMetrics:
    df = result.df

    # Input Row'a göre hizala
    by_row = {int(r["Input Row"]): r for _, r in df.iterrows()}

    measured = 0
    top1_correct = 0
    top3_correct = 0
    matched_total = 0
    nf_correct = 0
    nf_total = 0
    skipped = 0

    for i, gr in enumerate(golden):
        if not gr.is_complete:
            skipped += 1
            continue
        # Boş/literal nan input'lar match_mixed_list'te filtrelenir → satır
        # çıktıda olmaz; bunlar Not found beklenen satırlarsa "doğru".
        actual_row = by_row.get(i)
        actual_status = (actual_row["Eşleşme Durumu"] if actual_row is not None
                         else "Not found")
        actual_id = (actual_row["OSM ID"] if actual_row is not None else None)

        measured += 1

        if gr.expected_status == "Not found":
            nf_total += 1
            if actual_status == "Not found":
                nf_correct += 1
            continue

        if gr.expected_status == "Matched":
            matched_total += 1
            if _ids_match(actual_id, gr.expected_osm_ids):
                top1_correct += 1
                top3_correct += 1   # top-1 → otomatik top-3
            else:
                # Top-3'te isim eşleşmesi (alts string) — yumuşak kontrol.
                alts = str(actual_row["Alternatif Eşleşmeler"]) if actual_row is not None else ""
                # Heuristik: best_match adı veya alts içinde input adının
                # ana token'ı geçiyor mu? (Tam OSM ID karşılaştırması alts
                # için imkansız çünkü string'de ID yok.)
                if alts and gr.input_name.split()[0].lower() in alts.lower():
                    top3_correct += 1

    return GoldenMetrics(
        total_rows=len(golden),
        skipped_todo=skipped,
        measured=measured,
        top1_correct=top1_correct,
        top3_correct=top3_correct,
        matched_total=matched_total,
        not_found_correct=nf_correct,
        not_found_total=nf_total,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline runner
# ─────────────────────────────────────────────────────────────────────────────
def run_against_district(
    csv_path: Path,
    district: str,
    pool: UniversalPool | None = None,
) -> tuple[GoldenMetrics, MixedLookupResult]:
    golden = load_golden(csv_path)
    if pool is None:
        pool = prepare_universal_pool(district)
    names = [g.input_name for g in golden]
    nbhs = [g.input_neighborhood for g in golden]
    result = match_mixed_list(
        pool, names=names, neighborhoods=nbhs,
        threshold=MIXED_DEFAULT_THRESHOLD,
    )
    metrics = compute_metrics(golden, result)
    return metrics, result


def format_report(metrics: GoldenMetrics, district: str) -> str:
    return (
        f"\nGolden Set Raporu — {district}\n"
        f"{'─' * 50}\n"
        f"Toplam satır       : {metrics.total_rows}\n"
        f"<TODO> atlandı     : {metrics.skipped_todo}\n"
        f"Ölçülen satır      : {metrics.measured}\n"
        f"\n"
        f"Top-1 doğruluk     : {metrics.top1_correct}/{metrics.matched_total} "
        f"({metrics.top1_pct:.1f}%)\n"
        f"Top-3 doğruluk     : {metrics.top3_correct}/{metrics.matched_total} "
        f"({metrics.top3_pct:.1f}%)\n"
        f"Not Found doğruluk : {metrics.not_found_correct}/{metrics.not_found_total} "
        f"({metrics.nf_pct:.1f}%)\n"
        f"{'─' * 50}\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def _main() -> int:
    ap = argparse.ArgumentParser(description="Name Lookup golden set runner")
    ap.add_argument("--district", required=True, help="Örn. Kadıköy")
    ap.add_argument(
        "--csv", default=None,
        help="Golden CSV yolu (default: data/golden/name_lookup_<ilce>.csv)",
    )
    args = ap.parse_args()
    csv = Path(args.csv) if args.csv else (
        GOLDEN_DIR / f"name_lookup_{args.district.lower().replace('ı','i').replace('ö','o').replace('ü','u').replace('ş','s').replace('ç','c').replace('ğ','g')}.csv"
    )
    if not csv.exists():
        print(f"Golden CSV bulunamadı: {csv}", file=sys.stderr)
        return 2
    metrics, _ = run_against_district(csv, args.district)
    print(format_report(metrics, args.district))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
