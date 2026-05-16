"""
Regresyon: OD matrisi yürüyüş grafını yönsüz olarak ele almalı.

Audit bulgusu: compute_od_matrix() önceden G_proj.reverse() ile ters graf
üzerinde Dijkstra çalıştırıyordu. Bu, araç ağları için anlamlı (oneway tag'leri
yön belirler) ama yürüyüş için yanlış — yaya tek yön sokakta da ters
yürüyebilir. Sonuç: bir kısım bina yapay olarak ulaşılamaz görünüyordu.

Çözüm: Grafı `to_undirected()` ile yönsüze çevir, oradan Dijkstra çalıştır.
"""
from __future__ import annotations

import networkx as nx
import numpy as np


def _make_oneway_chain() -> nx.MultiDiGraph:
    """
    Üç node'lu zincir: A → B → C (tek yön).
    Yürüyüşçü için A, B, C arası birbirine ulaşılabilir olmalı.
    """
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"
    G.add_node("A", x=29.000, y=41.000)
    G.add_node("B", x=29.005, y=41.000)
    G.add_node("C", x=29.010, y=41.000)
    # Tek yönlü edge'ler — araç ağında yürüyüş için tipik tag durumu
    G.add_edge("A", "B", key=0, length=480.0, travel_time=360.0)
    G.add_edge("B", "C", key=0, length=480.0, travel_time=360.0)
    return G


def test_undirected_walk_graph_allows_reverse_traversal():
    """
    Yönsüz çevrim sonrası A↔C arası simetrik ulaşılabilir olmalı.
    Eski davranış (G.reverse()) C→A çalışırdı ama A→C çalışmazdı.
    """
    G = _make_oneway_chain()
    G_und = G.to_undirected(as_view=False)

    # C'den her iki yöne de ulaşılabilmeli
    lengths_from_c = nx.single_source_dijkstra_path_length(
        G_und, "C", weight="travel_time"
    )
    assert "A" in lengths_from_c
    assert "B" in lengths_from_c
    assert lengths_from_c["A"] == 720.0
    assert lengths_from_c["B"] == 360.0

    # A'dan her iki yöne de ulaşılabilmeli (yönsüz olduğu için simetrik)
    lengths_from_a = nx.single_source_dijkstra_path_length(
        G_und, "A", weight="travel_time"
    )
    assert "C" in lengths_from_a
    assert lengths_from_a["C"] == 720.0


def test_directed_reverse_breaks_walking_symmetry():
    """
    Karşıt: G.reverse() yaklaşımı asimetri yaratır — bu yüzden bıraktık.
    Test, eski davranışı dokümante eder; uygulamada KULLANILMAMALI.
    """
    G = _make_oneway_chain()
    G_rev = G.reverse(copy=True)

    # Ters graf: C'den A'ya ulaşılabilir (A→B→C zinciri ters döner)
    lengths_from_c_rev = nx.single_source_dijkstra_path_length(
        G_rev, "C", weight="travel_time"
    )
    assert "A" in lengths_from_c_rev

    # Ama orijinal grafta A'dan C'ye ulaşılır, ters grafta A'dan C'ye ULAŞILMAZ
    lengths_from_a_orig = nx.single_source_dijkstra_path_length(
        G, "A", weight="travel_time"
    )
    lengths_from_a_rev = nx.single_source_dijkstra_path_length(
        G_rev, "A", weight="travel_time"
    )
    assert "C" in lengths_from_a_orig
    assert "C" not in lengths_from_a_rev, (
        "Bu test eski G.reverse() yaklaşımının yarattığı asimetriyi "
        "dokümante eder. Yürüyüş için yanlıştır; üretimde to_undirected() "
        "kullanıyoruz."
    )


def test_undirected_preserves_isolated_components():
    """
    to_undirected() bağlantısız bileşenleri birleştirmez — sadece yönü kaldırır.
    Bu, validate_graph() raporunun anlamlı kalması için önemli.
    """
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"
    # Bileşen 1
    G.add_node(1, x=29.0, y=41.0)
    G.add_node(2, x=29.005, y=41.0)
    G.add_edge(1, 2, key=0, length=480.0, travel_time=360.0)
    # Bileşen 2 (bağlantısız)
    G.add_node(3, x=29.1, y=41.05)
    G.add_node(4, x=29.105, y=41.05)
    G.add_edge(3, 4, key=0, length=480.0, travel_time=360.0)

    G_und = G.to_undirected(as_view=False)
    d = nx.single_source_dijkstra_path_length(G_und, 1, weight="travel_time")
    assert 2 in d
    assert 3 not in d, "to_undirected bağlantısız bileşenleri birleştirmemeli"
    assert 4 not in d
