"""
components/signatures.py — Stale-banner için tipli signature'lar.

Optimizer UI iki ayrı "değişiklik tespit" katmanı kullanır:

  • **ODSignature**  → OD matrisi hangi (district, mode, speed) ile üretildi?
    Step 2 sonunda yazılır, Step 3'te karşılaştırılır.
  • **ResultSignature** → Optimization sonucu hangi (p, amac, capacity,
    solver_mode, m2_per_person, n_restarts, random_state) ile üretildi?
    Step 3 sonunda yazılır, Step 4'te karşılaştırılır.

Daha önce session_state'e tuple yazılıyordu. Alan eklendikçe pozisyon-bazlı
backward-compat `if len(_sig) >= N else default` patches yığılmaya başladı
(audit gözlemi 3.3). Bu modül tuple'ları frozen dataclass'lara çevirip
karşılaştırma + diff mantığını tek noktaya toplar:

  • Yeni alan eklemek = dataclass'a yeni field eklemek + default vermek
  • Backward-compat = `from_legacy_tuple()` helper'ları
  • Diff = `signature_diff(old, new) -> list[str]` insanlık-okur farkları
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any


@dataclass(frozen=True)
class ODSignature:
    """OD matrisinin yeniden hesaplanmasını gerektiren parametreler."""

    district: str | None
    mode: str             # "walk" | "drive"
    speed_kph: float

    @classmethod
    def from_legacy_tuple(cls, t: tuple) -> ODSignature:
        """Eski 2-tuple veya 3-tuple → dataclass."""
        if not t:
            return cls(district=None, mode="walk", speed_kph=0.0)
        district = t[0]
        if len(t) >= 3:
            mode = str(t[1])
            speed = float(t[-1])
        else:
            mode = "walk"
            speed = float(t[-1]) if len(t) >= 2 else 0.0
        return cls(district=district, mode=mode, speed_kph=speed)


@dataclass(frozen=True)
class ResultSignature:
    """Optimization sonucunun yeniden hesaplanmasını gerektiren parametreler."""

    p: int
    amac: str             # "min_sum" | "min_max" | "min_p95"
    capacity: bool
    solver_mode: str      # "auto" | "ilp" | "heuristic"
    m2_per_person: float | None  # None when capacity OFF
    n_restarts: int = 1
    random_state: int | None = None

    @classmethod
    def from_legacy_tuple(cls, t: tuple) -> ResultSignature:
        """Eski 4-tuple veya 5-tuple → dataclass; eksik alanlar default."""
        if not t:
            return cls(
                p=1, amac="min_sum", capacity=False,
                solver_mode="auto", m2_per_person=None,
            )
        # Pozisyonel parse (eski yazım sırası)
        p = int(t[0]) if len(t) >= 1 else 1
        amac = str(t[1]) if len(t) >= 2 else "min_sum"
        capacity = bool(t[2]) if len(t) >= 3 else False
        solver_mode = str(t[3]) if len(t) >= 4 else "auto"
        m2 = (
            (float(t[4]) if t[4] is not None else None)
            if len(t) >= 5 else None
        )
        n_restarts = int(t[5]) if len(t) >= 6 else 1
        seed = (
            (int(t[6]) if t[6] is not None else None)
            if len(t) >= 7 else None
        )
        return cls(
            p=p, amac=amac, capacity=capacity, solver_mode=solver_mode,
            m2_per_person=m2, n_restarts=n_restarts, random_state=seed,
        )


# ── Karşılaştırma helper'ı ─────────────────────────────────────────────────

# Alanın insanca ismi (UI'da diff mesajında görünür) ve gerekirse özel
# formatlayıcı. None → default repr.
_FIELD_LABELS: dict[str, str] = {
    "district":      "district",
    "mode":          "transport mode",
    "speed_kph":     "speed (km/h)",
    "p":             "p",
    "amac":          "objective",
    "capacity":      "capacity",
    "solver_mode":   "solver",
    "m2_per_person": "density m²/person",
    "n_restarts":    "K-Med restarts",
    "random_state":  "K-Med seed",
}


def _fmt_value(field_name: str, value: Any) -> str:
    """Diff mesajında okunabilir format."""
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, float):
        return f"{value:.2f}"
    return repr(value) if isinstance(value, str) else str(value)


def signature_diff(old: Any, new: Any) -> list[str]:
    """
    İki signature dataclass'ı karşılaştırır, insanca diff mesajları döner.
    Tip aynı değilse boş liste — bilinmeyen şekildeki signature uyarı
    üretmesin.
    """
    if old is None or new is None:
        return []
    if type(old) is not type(new):
        return []
    diffs: list[str] = []
    old_d = asdict(old)
    new_d = asdict(new)
    for f in fields(old):
        a = old_d.get(f.name)
        b = new_d.get(f.name)
        if a != b:
            label = _FIELD_LABELS.get(f.name, f.name)
            diffs.append(f"{label} ({_fmt_value(f.name, a)} → {_fmt_value(f.name, b)})")
    return diffs


def coerce_signature(raw: Any, kind: type) -> Any:
    """
    Session_state'ten gelen değeri verilen dataclass tipine zorla.
      • Zaten o tipte ise: olduğu gibi döndür
      • Tuple ise: kind.from_legacy_tuple() ile parse et
      • None / başka: None döndür (UI bunu bypass eder)
    """
    if raw is None:
        return None
    if isinstance(raw, kind):
        return raw
    if isinstance(raw, tuple) and hasattr(kind, "from_legacy_tuple"):
        try:
            return kind.from_legacy_tuple(raw)
        except Exception:
            return None
    return None
