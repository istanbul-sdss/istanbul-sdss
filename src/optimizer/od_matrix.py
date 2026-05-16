"""
src/optimizer/od_matrix.py

OSMnx + NetworkX ile bina → toplanma alanı OD (Origin-Destination) matrisi.

Algoritma:
  1. İlçe yürüme ağını indir / önbellekten yükle (osmnx)
  2. Her bina ve toplanma alanı için en yakın graph node'unu bul (vektörize)
  3. Her toplanma alanından tersine Dijkstra ile tüm node'lara mesafe hesapla
  4. [N_bina × N_toplanma] matrisini döndür (dakika cinsinden)

Ölçek:
  Kadıköy: ~6.500 bina × ~20 toplanma → ~2 dakika
  Büyük ilçe: ~25.000 × 50 → ~10-15 dakika
"""

from __future__ import annotations

import time
from collections.abc import Callable

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd

from src.config.settings import (
    CACHE_DIR,
)
from src.config.settings import (
    GRAPH_CACHE_VERSION as _SETTINGS_GRAPH_CACHE_VERSION,
)
from src.config.settings import (
    HAVERSINE_DETOUR_FACTOR as _SETTINGS_HAVERSINE_DETOUR_FACTOR,
)
from src.config.settings import (
    WALK_SPEED_KPH as _SETTINGS_WALK_SPEED_KPH,
)
from src.logger import get_logger

log = get_logger(__name__)

WGS84   = "EPSG:4326"
UTM_IST = "EPSG:32635"

# ── OSMnx ayarları ────────────────────────────────────────────────────────────
ox.settings.use_cache    = True
ox.settings.cache_folder = str(CACHE_DIR)
ox.settings.log_console  = False

# osmnx 1.x / 2.x uyumluluğu: 2.0'da `timeout` → `requests_timeout` olarak yeniden adlandırıldı
if hasattr(ox.settings, "requests_timeout"):
    ox.settings.requests_timeout = 180
else:
    ox.settings.timeout = 180

# KRİTİK: osmnx 2.x'te varsayılan True. Aktifken her sorguda `/api/status`
# polling'i yapıp slot bekliyor → küçük sorgularda bile 60-180s ceza.
# Single-user use-case için kapatmak güvenli.
if hasattr(ox.settings, "overpass_rate_limit"):
    ox.settings.overpass_rate_limit = False

# osmnx 2.x `overpass_url` ayarına `/interpreter` suffix'ini kendisi ekler;
# osmnx 1.x tam URL bekler. İki sürümde de çalışsın diye base URL tutuyor,
# osmnx sürümüne göre suffix'i dinamik ekliyoruz.
# Overpass mirror listesi: overpass-api.de > lz4 > kumi
# (osm.ch global değil; osmnx 504'te internal retry yapar → upstream
#  outage'da sorgu uzun sürebilir. Detay: src/services/osm_service.py)
_OVERPASS_BASES = [
    "https://overpass-api.de/api",
    "https://lz4.overpass-api.de/api",
    "https://overpass.kumi.systems/api",
]

_OSMNX_V2 = hasattr(ox.settings, "requests_timeout")

OVERPASS_URLS = [
    (b if _OSMNX_V2 else f"{b}/interpreter") for b in _OVERPASS_BASES
]

GRAPH_DIR = CACHE_DIR / "graphs"
GRAPH_DIR.mkdir(exist_ok=True)


# ── Yürüyüş hızı / cache versiyonu ────────────────────────────────────────────
# Audit bulgusu (P1.1): Önceden ox.add_edge_speeds(G) çağırıyordu — bu fonksiyon
# `maxspeed` tag'lerinden ve highway tipinden ARAÇ hızı imput eder (ör. yerel
# yol → 50 km/h). Sonuç: yürüyüş süreleri sistematik iyimser → P-Median'ın
# kapsama / max süre KPI'ları yanlış. Tipik yetişkin yürüyüş hızı kullanıyoruz.
# Sabitler src/config/settings.py'da merkezileştirildi. Bu modülde alias
# olarak yeniden ihraç edilir (mevcut import'lar kırılmaz).
WALK_SPEED_KPH = _SETTINGS_WALK_SPEED_KPH
GRAPH_CACHE_VERSION = _SETTINGS_GRAPH_CACHE_VERSION
HAVERSINE_DETOUR_FACTOR = _SETTINGS_HAVERSINE_DETOUR_FACTOR


# Ulaşım modu sabitleri — UI ve cache pattern'ı bu sözleşmeye uyar.
MODE_WALK = "walk"
MODE_DRIVE = "drive"
SUPPORTED_MODES = (MODE_WALK, MODE_DRIVE)

# Mode başına varsayılan hızlar (km/h). Walking 4.8 = AFAD/uluslararası
# karar destek pratiği. Driving 30 = şehir içi tipik ortalama (trafiği
# de yansıtır — açık otoyolda daha yüksek olabilir).
DEFAULT_SPEED_KPH = {
    MODE_WALK:  WALK_SPEED_KPH,
    MODE_DRIVE: 30.0,
}


def apply_speed(G: nx.MultiDiGraph, speed_kph: float) -> nx.MultiDiGraph:
    """
    Tüm edge'lere SABİT hız atar (km/h). Mode-agnostic varyant.

    Edge attribute'una `speed_kph` yazar; sonrasında çağrılan
    `ox.add_edge_travel_times` bu değeri kullanarak `travel_time` üretir.

    Notlar:
      • Walking için 4.8 km/h önerilir (AFAD/uluslararası pratiği).
      • Driving için kullanıcı OSM `maxspeed` tag'lerini değil sabit bir
        ortalamayı tercih ediyor — şehir içi tipik 25-35 km/h trafik dahil.
        `ox.add_edge_speeds` alternatifi maxspeed tag'lerini kullanır ama
        bu çalışmada `comparative analysis` amaçlı tek ortalama yeterli.
    """
    nx.set_edge_attributes(G, float(speed_kph), "speed_kph")
    return G


def apply_walking_speed(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """
    Backward-compat: `apply_speed(G, WALK_SPEED_KPH)` ile aynı.

    Eski test/import'lar (tests/test_walk_graph_speed.py) bu adı kullanıyor;
    yeni kodda `apply_speed(G, speed_kph)` tercih edilir.
    """
    return apply_speed(G, WALK_SPEED_KPH)


# ── Graf sağlık kontrolü ──────────────────────────────────────────────────────

def validate_graph(G: nx.MultiDiGraph) -> dict:
    """
    Yürüme grafının temel sağlık göstergelerini döner.

    - `connected_components` > 1 ise graf parçalıdır; bazı binalar/alanlar
      birbirine ulaşamaz. En büyük bileşen dışındaki binalar için OD
      değerleri +inf olur ve p_median bunları `ulasilamaz_binalar`'a atar.
    - `ratio_in_largest` küçükse (< 0.95) ilçe için indirme alanını
      genişletmek veya coastal/bridge kırılmalarını kontrol etmek gerekir.

    Return:
        dict: node_count, edge_count, connected_components,
              largest_component_nodes, ratio_in_largest
    """
    UG = G.to_undirected(as_view=True) if G.is_directed() else G
    components = list(nx.connected_components(UG))
    largest = max(components, key=len) if components else set()
    n = G.number_of_nodes()
    return {
        "node_count":               n,
        "edge_count":               G.number_of_edges(),
        "connected_components":     len(components),
        "largest_component_nodes":  len(largest),
        "ratio_in_largest":         (len(largest) / n) if n else 0.0,
    }


# ── Graf çekme / önbellekleme ─────────────────────────────────────────────────

def _normalize_ilce_slug(ilce: str) -> str:
    """
    İlçe adını dosya adına uygun, **güvenli** ASCII slug'a çevir.

    P1-02 güvenlik düzeltmesi: Önceki versiyon yalnızca Türkçe karakter
    haritası uygulayıp boşlukları `_` yapıyordu — `/`, `\\`, `..`, `:`,
    `<`, `*`, `?`, `|`, ASCII kontrol karakterleri ve diğer dosya-sistemi
    uyumsuz karakterler **filtrelenmiyordu**. Custom district girdisinde:

      • `../../etc/passwd` → cache klasörü dışına dosya yazma riski
      • `con` / `nul` / `prn` (Windows reserved names)
      • Windows-yasaklı `< > : " | ? *`
      • Tab/newline/control karakterleri → dosya adı bozulması

    Yeni davranış:
      1. Önce Türkçe karakter haritası (ı→i, ğ→g, vs.)
      2. Whitelist: yalnızca `[a-z0-9_]` karakterleri kabul; geri kalan → `_`
      3. Ardışık `_` tek `_`'a indirgenir
      4. Baş/son `_` temizlenir
      5. Boş sonuç → ValueError (caller'a "geçerli ad gerekli" sinyali)

    Whitelist'a `_` dahil çünkü çok kelimeli ilçe adları (örn. "Adalar Mahallesi")
    boşluk → `_` dönüşümünden korunmalı. Nokta (`.`) WHITELIST DIŞINDA:
    `..` path traversal saldırısını kökten önler.

    Path containment kontrolü ayrıca `get_graph` içinde `resolve()` ile yapılır.
    """
    import re as _re

    # 1. Türkçe karakter normalleştirme
    s = (
        str(ilce).lower()
        .replace("ı","i").replace("ğ","g").replace("ü","u")
        .replace("ş","s").replace("ö","o").replace("ç","c")
        .replace("â","a").replace("î","i").replace("û","u")
    )
    # 2. Whitelist — `[a-z0-9_]` dışındaki her şey `_`'a dönüşür. Boşluk,
    # nokta, slash, kontrol karakterleri otomatik filtrelenir.
    s = _re.sub(r"[^a-z0-9_]+", "_", s)
    # 3. Ardışık `_` tek `_`'a indir
    s = _re.sub(r"_+", "_", s)
    # 4. Baş/son `_` temizle
    s = s.strip("_")
    # 5. Boş slug → caller'a açık hata
    if not s:
        raise ValueError(
            f"İlçe adı geçerli bir dosya slug üretmedi: {ilce!r}. "
            f"En az bir alfanumerik karakter içermelidir."
        )
    return s


def _prune_stale_graph_caches(slug: str, mode: str, current_version: int) -> None:
    """
    Eski cache versiyonlu graf dosyalarını sil (H5 düzeltmesi).

    Mode bilinçli: `<slug>_<mode>_v<N>.graphml` desenine uyan ve current
    versiyondan KÜÇÜK olan dosyaları temizler. Walking ve driving cache'leri
    birbirine müdahale etmez (farklı mode → farklı pattern).

    Bu fonksiyon yalnızca AYNI ilçenin AYNI mode'una ait dosyalarına dokunur.
    """
    try:
        for old in GRAPH_DIR.glob(f"{slug}_{mode}_v*.graphml"):
            stem = old.stem  # ör. "kadikoy_walk_v1"
            try:
                ver = int(stem.rsplit("_v", 1)[1])
            except (IndexError, ValueError):
                continue
            if ver < current_version:
                try:
                    size_mb = old.stat().st_size / (1024 * 1024)
                    old.unlink()
                    log.info(
                        f"Eski graf cache silindi: {old.name} "
                        f"(v{ver} < v{current_version}, {size_mb:.1f} MB)"
                    )
                except OSError as e:
                    log.debug(f"Eski cache silinemedi {old.name}: {e}")
    except OSError as e:
        log.debug(f"Eski cache taraması atlandı: {e}")


def get_graph(
    ilce: str,
    mode: str = MODE_WALK,
    force_download: bool = False,
) -> nx.MultiDiGraph:
    """
    İlçe ulaşım ağını döner. Mode `walk` veya `drive`. Önbellekte varsa
    diskten yükler (~1s), yoksa Overpass'tan indirir (~30-120s).

    Cache şeması:
      <slug>_walk_v<N>.graphml   — yaya ağı (4.8 km/h sabit)
      <slug>_drive_v<N>.graphml  — araç ağı (kullanıcı varsayılan 30 km/h)

    Walking ve driving cache'leri bağımsızdır; biri diğerini etkilemez.

    NOT: Bu fonksiyon edge'lere `speed_kph = DEFAULT_SPEED_KPH[mode]` ile
    BAŞLANGIÇ hızı atar ve `travel_time` üretir. Kullanıcı UI'da farklı bir
    hız seçerse, `compute_od_matrix(..., travel_speed_kph=...)` çağrısı
    edge'lere yeniden uygulanır — graf cache'i invalid OLMAZ (cache yalnızca
    geometri/topoloji için), sadece travel_time runtime'da güncellenir.
    """
    if mode not in SUPPORTED_MODES:
        raise ValueError(
            f"Unsupported mode {mode!r}; expected one of {SUPPORTED_MODES}"
        )

    safe = _normalize_ilce_slug(ilce)
    cache_path = GRAPH_DIR / f"{safe}_{mode}_v{GRAPH_CACHE_VERSION}.graphml"

    # P1-02 güvenlik kontrolü: slug whitelist'i geçtikten sonra bile defansif
    # bir path containment doğrulaması yap. `resolve()` symlink/relative
    # ifadeleri normalize eder; `is_relative_to` 3.9+ ile cache_path'in
    # GRAPH_DIR altında kalıp kalmadığını kesin doğrular. Slug whitelist
    # zaten yeterli ama defense-in-depth iki katmanı koruyalım.
    try:
        cache_path.resolve().relative_to(GRAPH_DIR.resolve())
    except ValueError as exc:
        raise ValueError(
            f"Cache path containment ihlali: {ilce!r} ürettiği slug "
            f"({safe!r}) GRAPH_DIR dışına çıkıyor. Bu beklenmeyen bir "
            f"durum — geçerli bir ilçe adı girin."
        ) from exc

    # Eski sürüm cache'lerini bu mode için temizle (H5 düzeltmesi).
    _prune_stale_graph_caches(safe, mode, GRAPH_CACHE_VERSION)

    if cache_path.exists() and not force_download:
        log.info(f"Graf önbellekten yükleniyor: {cache_path.name}")
        G = ox.load_graphml(cache_path)
        log.info(f"Graf yüklendi: {G.number_of_nodes():,} node, {G.number_of_edges():,} edge")
        try:
            h = validate_graph(G)
            log.info(
                f"Graf sağlık ({mode}): {h['connected_components']} bileşen · "
                f"en büyük bileşen {h['ratio_in_largest']*100:.1f}%"
            )
            if h["ratio_in_largest"] < 0.95 and h["connected_components"] > 1:
                log.warning(
                    f"{mode.capitalize()} ağı parçalı — bazı binalar ulaşılamaz "
                    f"olarak işaretlenebilir. İlçe sınırını genişletmek veya "
                    f"komşu ilçelerle birleştirmek yardımcı olabilir."
                )
        except Exception as e:
            log.warning(f"Graf sağlık kontrolü başarısız: {e}")
        return G

    log.info(f"Graf indiriliyor: {ilce} (mode={mode})")
    last_err = None
    for url in OVERPASS_URLS:
        try:
            ox.settings.overpass_url = url
            G = ox.graph_from_place(
                f"{ilce}, İstanbul, Türkiye",
                network_type=mode,
                simplify=True,
            )
            # Mode'a göre varsayılan hızı uygula; kullanıcı runtime'da
            # override edebilir (compute_od_matrix).
            G = apply_speed(G, DEFAULT_SPEED_KPH[mode])
            G = ox.add_edge_travel_times(G)
            ox.save_graphml(G, cache_path)
            log.info(f"Graf kaydedildi: {cache_path.name}")
            return G
        except Exception as e:
            last_err = e
            log.warning(f"Graf indirme hatası ({url}): {e}")

    raise RuntimeError(f"{ilce} ağı indirilemedi: {last_err}")


def get_walk_graph(ilce: str, force_download: bool = False) -> nx.MultiDiGraph:
    """
    Backward-compat alias. Yeni kodda `get_graph(ilce, mode="walk", ...)`
    tercih edilir.
    """
    return get_graph(ilce, mode=MODE_WALK, force_download=force_download)


# ── OD Matrisi ────────────────────────────────────────────────────────────────

def compute_od_matrix(
    G: nx.MultiDiGraph,
    binalar_gdf: gpd.GeoDataFrame,
    toplanma_gdf: gpd.GeoDataFrame,
    max_dakika: float = 30.0,
    progress_cb: Callable | None = None,
    travel_speed_kph: float | None = None,
    walk_speed_kph: float | None = None,   # backward-compat alias
    transport_mode: str | None = None,
) -> np.ndarray:
    """
    [N_bina × N_toplanma] OD matrisi hesaplar.

    Değerler: süre (dakika) — graf hangi mode'da indirildiyse (`walk` veya
    `drive`) o ulaşım modunun süresidir.
    Ulaşılamaz hücreler: +inf (p_median bunları `ulasilamaz_binalar`'a atar).

    Parametreler:
        G                : osmnx ulaşım grafı (walk veya drive)
        binalar_gdf      : bina nokta GDF (geometry=Point, WGS84)
        toplanma_gdf     : toplanma alanı nokta GDF (geometry=Point, WGS84)
        max_dakika       : Dijkstra cutoff (üstündeki mesafeler hesaplanmaz
                           → inf). np.inf verilirse cutoff uygulanmaz.
        progress_cb      : ilerleme mesajı callback (opsiyonel)
        travel_speed_kph : Hız (km/h). None → modül varsayılanı (walk: 4.8).
                           Driving mode için kullanıcı genelde ~30 km/h
                           geçer. Bu parametre graf cache'ini invalidate
                           ETMEZ — Dijkstra `length` (metre) ile çalışır,
                           sonuçta hıza bölünerek süreye çevrilir.
        walk_speed_kph   : DEPRECATED — `travel_speed_kph` ile aynı anlam,
                           backward-compat için tutuluyor. İkisi birden
                           verilirse `travel_speed_kph` kazanır.
        transport_mode   : "walk" | "drive" | None. Bu parametre yön
                           semantiğini belirler:
                             • walk  → graf yönsüze çevrilir (yaya yön
                                       kısıtlarından bağımsız)
                             • drive → graf yönlü kalır + REVERSED view ile
                                       Dijkstra (toplanma alanından çalışıp
                                       bina→alan yönündeki yolları bulmak
                                       için)
                           None verilirse `G.graph["network_type"]`'ten
                           çıkarılır (OSMnx bu attribute'u set eder); o da
                           yoksa "walk" varsayılır (backward-compat).
    """
    def cb(msg: str):
        log.info(msg)
        if progress_cb:
            progress_cb(msg)

    # travel_speed_kph yeni isim; walk_speed_kph eski alias. Önceliği yeni
    # parametreye veriyoruz, ikisi de None ise modül varsayılanı.
    _speed_arg = travel_speed_kph if travel_speed_kph is not None else walk_speed_kph
    speed = float(_speed_arg) if _speed_arg else WALK_SPEED_KPH
    if speed <= 0:
        raise ValueError(f"travel_speed_kph={_speed_arg} pozitif olmalı")

    n_bina     = len(binalar_gdf)
    n_toplanma = len(toplanma_gdf)

    cb(f"OD matrisi başlıyor: {n_bina:,} bina × {n_toplanma} toplanma alanı · "
       f"hız={speed:.1f} km/h")

    # ── 1. Koordinatlar + Node snap ───────────────────────────────────────────
    # nearest_nodes, unprojected grafta scikit-learn gerektirir.
    # Grafı UTM'e yansıtarak bu bağımlılıktan kaçınıyoruz.
    cb("Node'lara snap ediliyor (graf UTM'e yansıtılıyor)...")
    G_proj = ox.project_graph(G, to_crs=UTM_IST)

    # Bina / toplanma geometrilerini UTM'e projekte et (GeoSeries üstünden, GDF wrap gereksiz)
    b_utm_geom = binalar_gdf.to_crs(UTM_IST).geometry
    t_gdf      = toplanma_gdf.to_crs(WGS84)   # isim kolonu için WGS84 kopyası aşağıda kullanılır
    t_utm_geom = toplanma_gdf.to_crs(UTM_IST).geometry

    bina_nodes     = ox.nearest_nodes(G_proj, X=b_utm_geom.x.values, Y=b_utm_geom.y.values)
    toplanma_nodes = ox.nearest_nodes(G_proj, X=t_utm_geom.x.values, Y=t_utm_geom.y.values)

    # ── 3. Mode-aware graf yönü ───────────────────────────────────────────────
    # Doğruluk düzeltmesi (P1-01): driving mode'da tek-yönlü yolları yok
    # saymamak gerekir. İki ayrı strateji:
    #
    #   • Walking: yaya yön kısıtlarından bağımsız → graf yönsüze çevrilir.
    #     Dijkstra'yı toplanma alanından başlatmak symmetric mesafe verir.
    #
    #   • Driving: oneway yollar gerçektir. Dijkstra'yı toplanma alanından
    #     başlatıp `G_proj` üzerinde çalıştırırsak alan-OUT yönündeki yolları
    #     buluruz (alan→bina). Biz ise bina→alan yönündeki süreleri istiyoruz.
    #     Çözüm: REVERSED view kullan. Reversed graph'ta alanın OUT-edge'leri
    #     orijinal graph'ta alana INCOMING edge'lerdir → tam istediğimiz
    #     "bina'dan başlayıp alana ulaşan yol"un tersinden katedilmiş hâli;
    #     uzunluklar aynı kalır. `copy=False` view tabanlı → cache'lenmiş
    #     orijinal graf bozulmaz.
    inferred_mode = (
        transport_mode if transport_mode is not None
        else G.graph.get("network_type", MODE_WALK)
    )
    if inferred_mode == MODE_DRIVE:
        G_und = G_proj.reverse(copy=False)
        cb("Mode=drive: directed graph + reversed Dijkstra (oneway korunur)")
    else:
        G_und = G_proj.to_undirected(as_view=False)
        cb(f"Mode={inferred_mode}: undirected graph (yön bağımsız)")

    # Dijkstra `length` (metre) üzerinden çalışır; sonra hıza böleriz.
    # Avantaj: kullanıcı hızı değiştirdiğinde graf cache invalidate olmaz.
    # max_dakika'yı metre cinsinden cutoff'a çevir: süre*60 sn * hız_m/s.
    speed_m_per_min = speed * 1000.0 / 60.0     # km/h → m/dk
    if np.isfinite(max_dakika):
        cutoff_metre = float(max_dakika) * speed_m_per_min
    else:
        cutoff_metre = None   # cutoff yok → tüm mesafeleri hesapla

    od_metre = np.full((n_bina, n_toplanma), np.inf, dtype=np.float32)

    t0 = time.time()
    for j, t_node in enumerate(toplanma_nodes):
        t_adi = t_gdf.iloc[j].get("ad", f"Alan {j+1}")
        cb(f"  [{j+1}/{n_toplanma}] {t_adi} — Dijkstra hesaplanıyor...")

        try:
            lengths = nx.single_source_dijkstra_path_length(
                G_und, t_node, weight="length", cutoff=cutoff_metre
            )
        except Exception as e:
            log.warning(f"Dijkstra hatası (toplanma {j+1}): {e}")
            continue

        for i, b_node in enumerate(bina_nodes):
            mt = lengths.get(b_node)
            if mt is not None:
                od_metre[i, j] = mt

    # Metre → dakika (hıza bölme)
    od = od_metre / speed_m_per_min

    elapsed = time.time() - t0
    erisilebilir = int(np.isfinite(od).sum())
    total = n_bina * n_toplanma
    cb(
        f"OD matrisi tamamlandı: {elapsed:.1f}s | "
        f"erişilebilir hücre: {erisilebilir:,}/{total:,} "
        f"(%{(erisilebilir/total*100 if total else 0):.1f})"
    )

    return od


def compute_od_matrix_haversine(
    binalar_gdf: gpd.GeoDataFrame,
    toplanma_gdf: gpd.GeoDataFrame,
    detour_factor: float = HAVERSINE_DETOUR_FACTOR,
    travel_speed_kph: float | None = None,
    progress_cb: Callable | None = None,
    walk_speed_kph: float | None = None,   # backward-compat alias
) -> np.ndarray:
    """
    Sokak ağı yedeği: kuş uçuşu mesafe × detour faktörü ile süre tahmini.

    Sokak ağı yüklenemediğinde (Overpass tüm mirror'larda 504, internet yok,
    OSM verisi cevapsız kaldı) acil durum aracının çalışmaya devam etmesi
    kritik. Bu fonksiyon UTM projeksiyonunda Öklid mesafesi hesaplar, detour
    faktörüyle çarpar (varsayılan 1.4 — şehir-içi tipik), hıza bölerek süre
    üretir.

    `travel_speed_kph`: walk için 4.8, drive için 30 (kullanıcı override
    edebilir). `walk_speed_kph` eski alias, backward-compat için tutuluyor.

    Doğruluk uyarısı: Bu *yaklaşık* bir tahmindir. Gerçek sokak ağına göre
    %20-40 sapabilir, özellikle nehir/duvar/dik yamaçlarda. UI'da kullanıcıya
    "tahmin modunda" badge'i gösterilmelidir.
    """
    def cb(msg: str):
        log.info(msg)
        if progress_cb:
            progress_cb(msg)

    _speed_arg = travel_speed_kph if travel_speed_kph is not None else walk_speed_kph
    speed = float(_speed_arg) if _speed_arg else WALK_SPEED_KPH
    if speed <= 0:
        raise ValueError(f"travel_speed_kph={_speed_arg} pozitif olmalı")

    n_bina = len(binalar_gdf)
    n_alan = len(toplanma_gdf)
    cb(f"Haversine OD (yedek mod): {n_bina:,} bina × {n_alan} alan, "
       f"detour={detour_factor}, hız={speed} km/h")

    b_utm = binalar_gdf.to_crs(UTM_IST).geometry
    t_utm = toplanma_gdf.to_crs(UTM_IST).geometry
    bx = b_utm.x.values.reshape(-1, 1)
    by = b_utm.y.values.reshape(-1, 1)
    tx = t_utm.x.values.reshape(1, -1)
    ty = t_utm.y.values.reshape(1, -1)

    dist_m = np.sqrt((bx - tx) ** 2 + (by - ty) ** 2)
    dist_walk_m = dist_m * detour_factor
    speed_m_per_min = (speed * 1000.0) / 60.0
    od_min = (dist_walk_m / speed_m_per_min).astype(np.float32)

    cb(f"Haversine OD tamamlandı: ortalama {float(od_min.mean()):.1f} dk, "
       f"max {float(od_min.max()):.1f} dk")
    return od_min


def od_to_dataframe(
    od: np.ndarray,
    binalar_gdf: gpd.GeoDataFrame,
    toplanma_gdf: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """OD matrisini okunabilir DataFrame'e çevirir (analiz/debug için)."""
    adlar = toplanma_gdf["ad"].tolist() if "ad" in toplanma_gdf.columns else [
        f"Alan {i+1}" for i in range(od.shape[1])
    ]
    return pd.DataFrame(od, columns=adlar).round(2)
