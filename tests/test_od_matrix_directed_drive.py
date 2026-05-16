"""
P1-01 regresyon: driving mode'da tek-yönlü yolların korunması.

Eski davranış: `compute_od_matrix` her zaman `to_undirected()` çağırıyordu →
driving senaryosunda OSM `oneway=yes` etiketleri yok sayılıyor; tek yön
yolların ters yönü de "geçilebilir" sayılıyordu. Bu, AFAD ya da
karşılaştırmalı analiz bağlamında yanıltıcı iyimser süreler üretiyordu.

Düzeltme: `transport_mode="drive"` → directed graph + reversed view ile
Dijkstra; tek yön yollar yön bilgisini korur. `transport_mode="walk"` ya
da varsayılan → eski undirected davranış (yaya oneway'den bağımsızdır,
geriye uyumlu).

Test stratejisi: sentetik 3-node tek-yönlü graf üzerinde
  • walking: ters yön yine geçilebilir
  • driving: ters yön yok → bina ulaşılamaz; doğru yön → ulaşılabilir
"""
from __future__ import annotations

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
from shapely.geometry import Point

from src.optimizer.od_matrix import (
    MODE_DRIVE,
    MODE_WALK,
    UTM_IST,
    compute_od_matrix,
)


def _oneway_graph(network_type: str = "drive") -> nx.MultiDiGraph:
    """
    3 node, tek yönlü A→B ve A→C edge'leri olan sentetik MultiDiGraph.
    OSMnx-uyumlu attribute set'i (length, travel_time, x/y) hazır.

        A ──(100m)──> B
        │
        └─(100m)──> C

      B'den A'ya yol yok (oneway). C'den A'ya yol yok.

    `network_type` attribute'u G.graph'a koyulur — `compute_od_matrix`
    `transport_mode` infer edebilsin.
    """
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"
    G.graph["network_type"] = network_type

    # UTM koordinatları (İstanbul EPSG:32635) — proje edilmiş.
    G.add_node(1, x=600000.0, y=4540000.0)         # A
    G.add_node(2, x=600100.0, y=4540000.0)         # B (100m east of A)
    G.add_node(3, x=600000.0, y=4540100.0)         # C (100m north of A)

    # Edge'ler: tek yönlü
    G.add_edge(1, 2, key=0, length=100.0, travel_time=12.5, oneway=True)
    G.add_edge(1, 3, key=0, length=100.0, travel_time=12.5, oneway=True)
    # Speed attribute (apply_speed çağrıldı varsayımı)
    nx.set_edge_attributes(G, 30.0, "speed_kph")
    return G


def _binalar_at(coords) -> gpd.GeoDataFrame:
    """[(lon, lat), ...] listesinden bina GDF üretir."""
    geom = [Point(lon, lat) for lon, lat in coords]
    return gpd.GeoDataFrame(
        {"weight": [100.0] * len(coords),
         "bina_etiketi": [f"B{i+1}" for i in range(len(coords))]},
        geometry=geom, crs="EPSG:4326",
    )


def _toplanma_at(coords) -> gpd.GeoDataFrame:
    geom = [Point(lon, lat) for lon, lat in coords]
    return gpd.GeoDataFrame(
        {"ad": [f"A{i+1}" for i in range(len(coords))]},
        geometry=geom, crs="EPSG:4326",
    )


def _utm_to_wgs(x_utm, y_utm):
    """Test sahte UTM koordinatlarını WGS84'e geri çevirir."""
    from pyproj import Transformer
    tr = Transformer.from_crs(UTM_IST, "EPSG:4326", always_xy=True)
    lon, lat = tr.transform(x_utm, y_utm)
    return lon, lat


# ── 1. Walking — yön bağımsız (geriye uyumlu) ─────────────────────────────
def test_walking_mode_treats_oneway_as_bidirectional():
    """
    Walking modunda yaya `oneway` tag'ini ihlal eder — undirected graph
    kullanılmalı. Yani B'den A'ya yürünebilir (orijinal edge A→B'ye
    rağmen).
    """
    G = _oneway_graph(network_type="walk")
    G.graph["crs"] = UTM_IST   # zaten UTM koordinatlarda

    # Bina = B (node 2), Toplanma = A (node 1) konumlarında
    lon_b, lat_b = _utm_to_wgs(600100.0, 4540000.0)
    lon_a, lat_a = _utm_to_wgs(600000.0, 4540000.0)

    binalar = _binalar_at([(lon_b, lat_b)])
    toplanma = _toplanma_at([(lon_a, lat_a)])

    od = compute_od_matrix(
        G, binalar, toplanma,
        max_dakika=float("inf"),
        travel_speed_kph=4.8,
        transport_mode=MODE_WALK,
    )

    # Walking undirected: B→A yolu mevcut (100m); 4.8 km/h'de ≈ 1.25 dk
    assert np.isfinite(od[0, 0]), (
        f"Walking modunda B→A undirected geçişli olmalı; od={od[0,0]}"
    )
    # ~1.25 dk bekleniyor (100m / 80 m/min); küçük sapma toleransı
    assert 1.0 < od[0, 0] < 2.0, f"Walking süresi mantıksız: {od[0, 0]} dk"


# ── 2. Driving — oneway korunur ──────────────────────────────────────────
def test_driving_mode_respects_oneway_unreachable():
    """
    KRİTİK BUG (P1-01): driving modunda B→A yolu YOKTUR (tek yön A→B).
    Doğru davranış: bina=B, toplanma=A senaryosunda B→A ulaşılamaz olmalı
    (od[0,0] = +inf).
    """
    G = _oneway_graph(network_type="drive")
    G.graph["crs"] = UTM_IST

    # Bina = B (node 2, sadece A→B yolu var; B→A YOK)
    # Toplanma = A (node 1)
    # Bina'dan toplanma'ya gitmek = B'den A'ya gitmek → driving'de imkânsız
    lon_b, lat_b = _utm_to_wgs(600100.0, 4540000.0)
    lon_a, lat_a = _utm_to_wgs(600000.0, 4540000.0)

    binalar = _binalar_at([(lon_b, lat_b)])
    toplanma = _toplanma_at([(lon_a, lat_a)])

    od = compute_od_matrix(
        G, binalar, toplanma,
        max_dakika=float("inf"),
        travel_speed_kph=30.0,
        transport_mode=MODE_DRIVE,
    )

    # Driving directed: B→A yolu yok → od[0,0] = +inf
    assert not np.isfinite(od[0, 0]), (
        f"Driving modunda B→A ulaşılamaz olmalı (oneway A→B); "
        f"od={od[0,0]} (sonsuz bekleniyordu)"
    )


def test_driving_mode_reachable_correct_direction():
    """
    Driving modunda A→B yolu MEVCUTTUR — yani bina=A, toplanma=B
    senaryosunda A binası B alanına ulaşabilmeli (doğru yön).

    Reversed Dijkstra mantığını doğrular: reversed graph'ta B-OUT =
    orijinal graph'ta B'ye gelen = A→B → A reachable from B-reversed.
    """
    G = _oneway_graph(network_type="drive")
    G.graph["crs"] = UTM_IST

    # Bina = A (kaynak), Toplanma = B (hedef)
    lon_a, lat_a = _utm_to_wgs(600000.0, 4540000.0)
    lon_b, lat_b = _utm_to_wgs(600100.0, 4540000.0)

    binalar = _binalar_at([(lon_a, lat_a)])
    toplanma = _toplanma_at([(lon_b, lat_b)])

    od = compute_od_matrix(
        G, binalar, toplanma,
        max_dakika=float("inf"),
        travel_speed_kph=30.0,
        transport_mode=MODE_DRIVE,
    )

    # A→B yolu var (100m / 30 km/h ≈ 0.2 dk)
    assert np.isfinite(od[0, 0]), (
        f"Driving modunda A→B mevcut olmalı; od={od[0,0]}"
    )
    assert 0.1 < od[0, 0] < 1.0, f"Driving süresi mantıksız: {od[0, 0]} dk"


# ── 3. Asimetri: Walking simetrik, driving değil ─────────────────────────
def test_walk_drive_asymmetry_on_oneway():
    """
    Aynı geometride walking ↔ driving karşı yön davranışı:
      Walking:  A→B reachable, B→A reachable (undirected)
      Driving:  A→B reachable, B→A unreachable (oneway)
    """
    # Senaryo 1: Bina B, Toplanma A
    G_walk = _oneway_graph(network_type="walk")
    G_walk.graph["crs"] = UTM_IST
    G_drive = _oneway_graph(network_type="drive")
    G_drive.graph["crs"] = UTM_IST

    lon_b, lat_b = _utm_to_wgs(600100.0, 4540000.0)
    lon_a, lat_a = _utm_to_wgs(600000.0, 4540000.0)
    binalar = _binalar_at([(lon_b, lat_b)])
    toplanma = _toplanma_at([(lon_a, lat_a)])

    od_w = compute_od_matrix(
        G_walk, binalar, toplanma, max_dakika=float("inf"),
        travel_speed_kph=4.8, transport_mode=MODE_WALK,
    )
    od_d = compute_od_matrix(
        G_drive, binalar, toplanma, max_dakika=float("inf"),
        travel_speed_kph=30.0, transport_mode=MODE_DRIVE,
    )

    # Walking: ters yön de geçilebilir (yaya oneway dinlemez)
    assert np.isfinite(od_w[0, 0])
    # Driving: ters yön yok (oneway korunur)
    assert not np.isfinite(od_d[0, 0])


# ── 4. transport_mode None → graph.network_type infer ────────────────────
def test_transport_mode_inferred_from_graph():
    """
    transport_mode parametresi verilmezse G.graph['network_type']
    okunur. Bu, OSMnx graph_from_place ile çekilen grafların doğal
    behavior'u — caller her seferinde mode'u manuel geçmek zorunda
    değil (kolay kullanım için).
    """
    G = _oneway_graph(network_type="drive")
    G.graph["crs"] = UTM_IST

    lon_b, lat_b = _utm_to_wgs(600100.0, 4540000.0)
    lon_a, lat_a = _utm_to_wgs(600000.0, 4540000.0)
    binalar = _binalar_at([(lon_b, lat_b)])
    toplanma = _toplanma_at([(lon_a, lat_a)])

    # transport_mode VERMEDEN; graf "drive" diye taşıyor
    od = compute_od_matrix(
        G, binalar, toplanma,
        max_dakika=float("inf"),
        travel_speed_kph=30.0,
        # transport_mode=None — graph'tan infer edilsin
    )
    # Drive davranışı: B→A unreachable
    assert not np.isfinite(od[0, 0]), (
        "transport_mode None iken graph.network_type='drive' okunmalı"
    )
