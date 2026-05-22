"""
Sprint 2 #9: typed stale-banner signature'ları regresyonu.

components/signatures.py'daki ODSignature + ResultSignature dataclass'ları,
signature_diff() ve coerce_signature() helper'ları için kapsamlı testler.
Tuple-bazlı backward-compat parser'ı eski session'ları kırmasın diye
ayrıca doğrulanır.
"""
from __future__ import annotations

from components.signatures import (
    ODSignature,
    ResultSignature,
    coerce_signature,
    signature_diff,
)

# ── ODSignature ───────────────────────────────────────────────────────────

def test_od_signature_equality():
    """Aynı alanlar = aynı dataclass instance (frozen + auto __eq__)."""
    a = ODSignature(district="Kadıköy", mode="walk", speed_kph=5.0)
    b = ODSignature(district="Kadıköy", mode="walk", speed_kph=5.0)
    assert a == b


def test_od_signature_inequality():
    a = ODSignature(district="Kadıköy", mode="walk", speed_kph=5.0)
    b = ODSignature(district="Kadıköy", mode="drive", speed_kph=5.0)
    assert a != b


def test_od_signature_from_legacy_3tuple():
    """Yeni 3-tuple → (district, mode, speed)."""
    sig = ODSignature.from_legacy_tuple(("Kadıköy", "drive", 30.0))
    assert sig.district == "Kadıköy"
    assert sig.mode == "drive"
    assert sig.speed_kph == 30.0


def test_od_signature_from_legacy_2tuple():
    """Eski 2-tuple (walking-only zamanlar) → mode="walk" default."""
    sig = ODSignature.from_legacy_tuple(("Kadıköy", 5.0))
    assert sig.district == "Kadıköy"
    assert sig.mode == "walk"
    assert sig.speed_kph == 5.0


def test_od_signature_from_legacy_empty():
    """Boş tuple → safe defaults."""
    sig = ODSignature.from_legacy_tuple(())
    assert sig.district is None
    assert sig.mode == "walk"


# ── ResultSignature ───────────────────────────────────────────────────────

def test_result_signature_equality_full():
    a = ResultSignature(
        p=5, amac="min_sum", capacity=True, solver_mode="ilp",
        m2_per_person=1.5, n_restarts=3, random_state=42,
    )
    b = ResultSignature(
        p=5, amac="min_sum", capacity=True, solver_mode="ilp",
        m2_per_person=1.5, n_restarts=3, random_state=42,
    )
    assert a == b


def test_result_signature_density_off_uses_none():
    a = ResultSignature(
        p=5, amac="min_sum", capacity=False, solver_mode="ilp",
        m2_per_person=None,
    )
    assert a.m2_per_person is None
    assert a.n_restarts == 1  # default


def test_result_signature_legacy_4tuple():
    """Eski 4-tuple (p, amac, capacity, solver) → density=None default."""
    sig = ResultSignature.from_legacy_tuple((5, "min_sum", True, "ilp"))
    assert sig.p == 5
    assert sig.amac == "min_sum"
    assert sig.capacity is True
    assert sig.solver_mode == "ilp"
    assert sig.m2_per_person is None
    assert sig.n_restarts == 1


def test_result_signature_legacy_5tuple():
    """5-tuple (density eklenmiş) → density alanı dolu."""
    sig = ResultSignature.from_legacy_tuple((3, "min_max", True, "kmedoids", 2.0))
    assert sig.m2_per_person == 2.0
    assert sig.n_restarts == 1  # default


def test_result_signature_legacy_7tuple_with_kmed():
    """7-tuple → K-Med fields dolu."""
    sig = ResultSignature.from_legacy_tuple(
        (3, "min_p95", False, "kmedoids", None, 5, 42)
    )
    assert sig.n_restarts == 5
    assert sig.random_state == 42


# ── signature_diff ────────────────────────────────────────────────────────

def test_diff_identical_returns_empty():
    a = ODSignature(district="Kadıköy", mode="walk", speed_kph=5.0)
    b = ODSignature(district="Kadıköy", mode="walk", speed_kph=5.0)
    assert signature_diff(a, b) == []


def test_diff_single_change_od():
    a = ODSignature(district="Kadıköy", mode="walk", speed_kph=5.0)
    b = ODSignature(district="Kadıköy", mode="drive", speed_kph=5.0)
    diffs = signature_diff(a, b)
    assert len(diffs) == 1
    assert "transport mode" in diffs[0]


def test_diff_multiple_changes_result():
    a = ResultSignature(
        p=5, amac="min_sum", capacity=False, solver_mode="auto",
        m2_per_person=None,
    )
    b = ResultSignature(
        p=7, amac="min_max", capacity=False, solver_mode="auto",
        m2_per_person=None,
    )
    diffs = signature_diff(a, b)
    assert len(diffs) == 2  # p + amac
    assert any("p " in d for d in diffs)
    assert any("objective" in d for d in diffs)


def test_diff_density_change_formatting():
    """Density float değişimi 2-decimal format ile gösterilmeli."""
    a = ResultSignature(
        p=3, amac="min_sum", capacity=True, solver_mode="ilp",
        m2_per_person=1.5,
    )
    b = ResultSignature(
        p=3, amac="min_sum", capacity=True, solver_mode="ilp",
        m2_per_person=2.5,
    )
    diffs = signature_diff(a, b)
    assert len(diffs) == 1
    assert "1.50" in diffs[0] and "2.50" in diffs[0]


def test_diff_none_inputs_return_empty():
    """None argümanlar uyarı tetiklemesin (bilinmeyen state)."""
    assert signature_diff(None, ODSignature(district=None, mode="walk", speed_kph=5.0)) == []
    assert signature_diff(ODSignature(district=None, mode="walk", speed_kph=5.0), None) == []


def test_diff_mismatched_types_return_empty():
    """ODSignature vs ResultSignature karşılaştırması yasa, boş döner."""
    od = ODSignature(district=None, mode="walk", speed_kph=5.0)
    rs = ResultSignature(
        p=1, amac="min_sum", capacity=False, solver_mode="auto",
        m2_per_person=None,
    )
    assert signature_diff(od, rs) == []


# ── coerce_signature ──────────────────────────────────────────────────────

def test_coerce_already_typed_returns_same_instance():
    """Zaten doğru tip → değiştirme."""
    od = ODSignature(district="Kadıköy", mode="walk", speed_kph=5.0)
    assert coerce_signature(od, ODSignature) is od


def test_coerce_tuple_parses_to_dataclass():
    """Tuple → dataclass (backward-compat)."""
    res = coerce_signature(("Kadıköy", "drive", 30.0), ODSignature)
    assert isinstance(res, ODSignature)
    assert res.mode == "drive"


def test_coerce_none_returns_none():
    assert coerce_signature(None, ODSignature) is None


def test_coerce_unknown_type_returns_none():
    """List veya dict gibi unsupported tipler → None (defensive)."""
    assert coerce_signature([1, 2, 3], ODSignature) is None
    assert coerce_signature({"x": 1}, ODSignature) is None
