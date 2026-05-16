"""
Regresyon: Yürüme grafındaki edge'lerin SABİT yürüyüş hızı taşıması.

Audit bulgusu (P1.1): get_walk_graph() önceden ox.add_edge_speeds(G) çağırıp
araç hızlarını imput ediyordu. Sonuç: 480 m'lik bir cadde edge'i `maxspeed=50`
yüzünden ~30 sn'de geçilmiş gibi gösteriliyordu — yürüyüşçü için ~6 dk olmalı.
P-Median'ın kapsama yüzdeleri ve max süreleri sistematik iyimser çıkıyordu.

Çözüm: Tüm edge'lere sabit `speed_kph = 4.8` (typical adult walking pace)
atanır, sonra `add_edge_travel_times` çağrılır. Cache versiyon etiketi
(_walk_v2 suffix) eski yanlış-süreli graphml'leri otomatik invalid eder.
"""
from __future__ import annotations

import networkx as nx
import pytest

from src.optimizer.od_matrix import (
    GRAPH_CACHE_VERSION,
    WALK_SPEED_KPH,
    apply_walking_speed,
)


def _make_simple_graph() -> nx.MultiDiGraph:
    """İki node, 480 m'lik tek edge — yürüyüşle ~6 dk olmalı."""
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"  # OSMnx graph_to_gdfs için zorunlu
    G.add_node(1, x=29.0, y=41.0)
    G.add_node(2, x=29.005, y=41.0)
    # length attribute metre cinsinden — OSMnx convention
    G.add_edge(1, 2, key=0, length=480.0, highway="residential")
    return G


def test_walk_speed_constant_is_realistic_pace():
    """4.8 km/h tipik yetişkin yürüyüş hızı — bu sabit hareketsizleşmesin."""
    assert 3.5 <= WALK_SPEED_KPH <= 5.5, (
        f"WALK_SPEED_KPH={WALK_SPEED_KPH} gerçekçi bir yetişkin yürüyüş "
        f"aralığında değil (3.5-5.5 km/h beklenir). AFAD/uluslararası "
        f"karar destek pratiği genelde 4.8 km/h kullanır."
    )


def test_apply_walking_speed_overrides_all_edges():
    """Edge'lere sabit yürüyüş hızı atanır, hiçbiri default'a düşmez."""
    G = _make_simple_graph()
    G2 = apply_walking_speed(G)
    speeds = [data.get("speed_kph") for _, _, data in G2.edges(data=True)]
    assert all(s == WALK_SPEED_KPH for s in speeds), (
        f"REGRESYON: yürüyüş grafında edge'lere {WALK_SPEED_KPH} km/h "
        f"yerine farklı hızlar atanmış: {speeds}"
    )


def test_walk_travel_time_realistic():
    """480 m edge → 6 dk = 360 sn (4.8 km/h hızla). ±10% tolerans."""
    G = apply_walking_speed(_make_simple_graph())
    import osmnx as ox
    G = ox.add_edge_travel_times(G)

    travel_times = [
        data.get("travel_time")
        for _, _, data in G.edges(data=True)
    ]
    assert len(travel_times) == 1
    tt = travel_times[0]
    expected = 480.0 / (WALK_SPEED_KPH * 1000 / 3600)  # m / (m/s) = sn
    assert tt == pytest.approx(expected, rel=0.10), (
        f"REGRESYON: 480 m edge'in yürüyüş süresi yanlış. "
        f"Beklenen ~{expected:.0f} sn (yetişkin yürüyüş), gelen {tt:.1f} sn. "
        f"add_edge_speeds yine araç hızı imput ediyor olabilir."
    )


def test_graph_cache_version_in_filename():
    """
    Cache versiyon etiketi dosya adında olmalı — eski (_walk.graphml) ve yeni
    (_walk_v2.graphml) ayrı dosyalar. Aksi halde eski yanlış-süreli graf
    sessizce yüklenmeye devam eder.
    """
    assert GRAPH_CACHE_VERSION >= 2, (
        f"GRAPH_CACHE_VERSION={GRAPH_CACHE_VERSION}; P1.1 düzeltmesinden sonra "
        f"versiyon en az 2 olmalı. Eski cache dosyaları (_walk.graphml) "
        f"yanlış travel_time'larla diskte kalmasın."
    )
