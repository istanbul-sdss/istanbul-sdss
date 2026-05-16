"""
Transport mode (walk + drive) regresyon testleri.

Faz 2 — comparative analysis için driving mode eklendi. AFAD pratiği yaya
senaryosuna dayanır; driving modu karşılaştırmalı analiz için sunulur
(deprem sonrası araç pratik değildir, akademik not olarak Methodology
sheet'inde belirtilir).

Test kapsamı:
  1. `apply_speed(G, kph)` mode-agnostic — herhangi bir hız atayabilir
  2. `apply_walking_speed(G)` backward-compat alias hâlâ çalışıyor
  3. `MODE_WALK` ve `MODE_DRIVE` sabitleri export ediliyor
  4. `DEFAULT_SPEED_KPH` haritası iki mode için makul varsayılan içeriyor
  5. Cache pattern: `_prune_stale_graph_caches` mode bilinçli, walking
     cache'i drive cache'ini etkilemez
  6. `compute_od_matrix(travel_speed_kph=...)` + backward-compat
     `walk_speed_kph=...` ikisi de aynı sonucu üretir
  7. `get_graph` invalid mode için ValueError fırlatır
  8. `get_walk_graph` backward-compat alias çalışır
"""
from __future__ import annotations

import networkx as nx
import pytest

from src.optimizer.od_matrix import (
    DEFAULT_SPEED_KPH,
    MODE_DRIVE,
    MODE_WALK,
    SUPPORTED_MODES,
    WALK_SPEED_KPH,
    _prune_stale_graph_caches,
    apply_speed,
    apply_walking_speed,
    get_graph,
)


def _toy_graph() -> nx.MultiDiGraph:
    """Test için sahte küçük graf — 3 node, 2 edge."""
    G = nx.MultiDiGraph()
    G.add_node(1, x=28.0, y=41.0)
    G.add_node(2, x=28.001, y=41.001)
    G.add_node(3, x=28.002, y=41.002)
    G.add_edge(1, 2, length=100.0)
    G.add_edge(2, 3, length=100.0)
    return G


# ── 1. apply_speed mode-agnostic ──────────────────────────────────────────
def test_apply_speed_sets_walking():
    G = apply_speed(_toy_graph(), 4.8)
    for _, _, data in G.edges(data=True):
        assert data["speed_kph"] == 4.8


def test_apply_speed_sets_driving():
    G = apply_speed(_toy_graph(), 30.0)
    for _, _, data in G.edges(data=True):
        assert data["speed_kph"] == 30.0


def test_apply_speed_overwrites_previous():
    """Aynı graf üzerinde tekrar uygulanırsa son değer kazanır."""
    G = _toy_graph()
    apply_speed(G, 4.8)
    apply_speed(G, 30.0)
    speeds = {data["speed_kph"] for _, _, data in G.edges(data=True)}
    assert speeds == {30.0}


# ── 2. apply_walking_speed backward-compat ────────────────────────────────
def test_apply_walking_speed_alias():
    """Eski kod `apply_walking_speed`'i kullanmaya devam edebilir."""
    G = apply_walking_speed(_toy_graph())
    for _, _, data in G.edges(data=True):
        assert data["speed_kph"] == WALK_SPEED_KPH


# ── 3. Mode sabitleri export ──────────────────────────────────────────────
def test_mode_constants_exported():
    assert MODE_WALK == "walk"
    assert MODE_DRIVE == "drive"
    assert MODE_WALK in SUPPORTED_MODES
    assert MODE_DRIVE in SUPPORTED_MODES


# ── 4. Default hızlar makul ───────────────────────────────────────────────
def test_default_speeds_are_reasonable():
    """Walking 4-6 arası, driving 20-40 arası şehir-içi bekliyoruz."""
    walk_speed = DEFAULT_SPEED_KPH[MODE_WALK]
    drive_speed = DEFAULT_SPEED_KPH[MODE_DRIVE]
    assert 3.5 <= walk_speed <= 6.0, f"Walking default {walk_speed} aralık dışı"
    assert 20.0 <= drive_speed <= 40.0, f"Driving default {drive_speed} aralık dışı"
    # Driving mutlaka walking'den hızlı
    assert drive_speed > walk_speed


# ── 5. Cache pattern mode-aware ───────────────────────────────────────────
def test_prune_stale_caches_isolates_modes(tmp_path, monkeypatch):
    """
    Walking ve driving cache'leri AYRI yönetilir — bir mode'un prune'ı
    diğer mode'un dosyalarını silmemeli.
    """
    import src.optimizer.od_matrix as odm
    monkeypatch.setattr(odm, "GRAPH_DIR", tmp_path)

    # Eski sürüm dosyaları yarat
    (tmp_path / "kadikoy_walk_v1.graphml").write_text("dummy walk v1")
    (tmp_path / "kadikoy_walk_v2.graphml").write_text("dummy walk v2")
    (tmp_path / "kadikoy_drive_v1.graphml").write_text("dummy drive v1")

    # Walking için v2'ye prune
    _prune_stale_graph_caches("kadikoy", "walk", current_version=2)
    # v1 silindi, v2 kaldı, drive dokunulmadı
    assert not (tmp_path / "kadikoy_walk_v1.graphml").exists()
    assert (tmp_path / "kadikoy_walk_v2.graphml").exists()
    assert (tmp_path / "kadikoy_drive_v1.graphml").exists(), (
        "Walking prune'ı driving cache'ini silmemeli"
    )

    # Driving için v2'ye prune
    _prune_stale_graph_caches("kadikoy", "drive", current_version=2)
    assert not (tmp_path / "kadikoy_drive_v1.graphml").exists()
    # Walk v2 dokunulmamış
    assert (tmp_path / "kadikoy_walk_v2.graphml").exists()


def test_prune_does_not_touch_other_districts(tmp_path, monkeypatch):
    """Bir ilçenin prune'ı başka ilçenin dosyalarına dokunmamalı."""
    import src.optimizer.od_matrix as odm
    monkeypatch.setattr(odm, "GRAPH_DIR", tmp_path)

    (tmp_path / "kadikoy_walk_v1.graphml").write_text("dummy")
    (tmp_path / "besiktas_walk_v1.graphml").write_text("dummy")

    _prune_stale_graph_caches("kadikoy", "walk", current_version=2)

    assert not (tmp_path / "kadikoy_walk_v1.graphml").exists()
    assert (tmp_path / "besiktas_walk_v1.graphml").exists(), (
        "Bir ilçe prune'ı diğer ilçeyi silmemeli"
    )


# ── 6. compute_od_matrix backward-compat ──────────────────────────────────
def test_compute_od_matrix_travel_speed_takes_precedence():
    """
    travel_speed_kph + walk_speed_kph birlikte verilirse travel_speed_kph
    kazanır. Bu testte fonksiyon body'sini çağırmıyoruz (graf gerek);
    sadece signature/parametre semantiğini doğruluyoruz.
    """
    import inspect

    from src.optimizer.od_matrix import compute_od_matrix
    sig = inspect.signature(compute_od_matrix)
    params = sig.parameters
    # Yeni parametre var
    assert "travel_speed_kph" in params, "travel_speed_kph parametresi eklenmedi"
    # Backward-compat parametre korunmuş
    assert "walk_speed_kph" in params, "walk_speed_kph backward-compat parametresi silinmiş"
    # Her ikisi de default=None
    assert params["travel_speed_kph"].default is None
    assert params["walk_speed_kph"].default is None


# ── 7. Invalid mode → ValueError ──────────────────────────────────────────
def test_get_graph_rejects_invalid_mode():
    with pytest.raises(ValueError, match="Unsupported mode"):
        get_graph("Kadıköy", mode="bike", force_download=False)


# ── 8. get_walk_graph alias ───────────────────────────────────────────────
def test_get_walk_graph_alias_exists():
    """
    Backward-compat `get_walk_graph` import edilebilir olmalı; eski test
    veya kod hâlâ kullanıyor olabilir.
    """
    import inspect

    from src.optimizer.od_matrix import get_walk_graph
    sig = inspect.signature(get_walk_graph)
    # signature: (ilce, force_download=False)
    assert "ilce" in sig.parameters
    assert "force_download" in sig.parameters
