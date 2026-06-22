"""
src/config/settings.py

Merkezi yapılandırma — tüm sabitler ve ayarlar tek yerden yönetilir.
Ortam değişkeni veya doğrudan değiştirme ile override edilebilir.
"""

from __future__ import annotations

import os
from pathlib import Path

# ── PROJE KÖK KLASÖRÜ ────────────────────────────────────────────────────────
ROOT_DIR   = Path(__file__).parent.parent.parent
DATA_DIR   = ROOT_DIR / "data"
MAH_DIR    = DATA_DIR / "mahalleleri"
OUTPUT_DIR = ROOT_DIR / "output"
CACHE_DIR  = ROOT_DIR / "cache"
LOG_DIR    = ROOT_DIR / "logs"

# Klasörler yoksa oluştur
for d in [OUTPUT_DIR, CACHE_DIR, LOG_DIR, MAH_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# String versiyonlar — pipeline/app'te str beklenen yerlerde kullan
MAH_DIR_STR    = str(MAH_DIR)
OUTPUT_DIR_STR = str(OUTPUT_DIR)

# ── CRS ──────────────────────────────────────────────────────────────────────
WGS84       = "EPSG:4326"
UTM_IST     = "EPSG:32635"   # İstanbul — UTM Zone 35N

# ── LOGLAMA ───────────────────────────────────────────────────────────────────
LOG_LEVEL  = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_FILE   = LOG_DIR / "app.log"

# ── OPTİMİZASYON SABİTLERİ ───────────────────────────────────────────────────
# Bu değerler optimizasyon davranışını belirler — değiştirmeden önce ilgili
# regresyon testlerine bakın (tests/test_walk_graph_speed.py vb.).

# Yürüyüş hızı (km/h). 4.8 = AFAD/uluslararası karar destek pratiği —
# tipik yetişkin tempo. Eğim/merdiven dikkate alınmaz; yatay tahmin.
WALK_SPEED_KPH = float(os.getenv("WALK_SPEED_KPH", "4.8"))

# Yürüme grafı cache versiyonu. Hız modeli veya graph üretim mantığı değişirse
# bu sayıyı artır → eski .graphml dosyaları otomatik bypass edilir.
GRAPH_CACHE_VERSION = 2

# Sokak ağı erişilemediğinde kuş uçuşu × detour ile yedek mod.
# Şehir-içi yaya literatür aralığı 1.3-1.5; afet bağlamında temkinli yüksek değer.
HAVERSINE_DETOUR_FACTOR = float(os.getenv("HAVERSINE_DETOUR_FACTOR", "1.4"))

# ILP/Heuristic otomatik geçiş eşiği. Üstünde ILP CBC ile pratik değil;
# kullanıcı solver=ilp seçerse override edilir.
ILP_THRESHOLD = int(os.getenv("ILP_THRESHOLD", "5000"))

# ILP çözücü zaman limiti (saniye). 5 dk varsayılan; kullanıcı UI'dan uzatabilir.
ILP_TIME_LIMIT_SN = int(os.getenv("ILP_TIME_LIMIT_SN", "300"))

# Heuristic local search üst sınırı. 200 üzerinde marjinal kazanç çok az.
HEURISTIC_MAX_ITER = int(os.getenv("HEURISTIC_MAX_ITER", "200"))

# Fairness modu için yüzdelik. 95 = AFAD karar destek için makul outlier toleransı.
P95_PERCENTILE = 95.0

# Nüfus tahmin sabitleri (population_estimator.py). TÜİK 2023 bazlı.
HOUSEHOLD_SIZE_IST     = 3.24    # kişi/hane
AVG_DWELLING_M2_GROSS  = 120.0   # m²/hane
NET_USAGE_RATIO        = 0.85    # net/brüt
POP_PER_M2_CONSERVATIVE = 0.025  # kişi/m² (kat başına, brüt)
DEFAULT_BUILDING_LEVELS = 4      # OSM'de kat sayısı yoksa fallback

# AFAD acil toplanma alanı standardı.
AFAD_M2_PER_PERSON = 1.5         # kişi başına minimum m²

# Toplanma alanı varsayılan alan fallback'i (Point geometry, alan kolonu yok).
DEFAULT_ASSEMBLY_AREA_FALLBACK_M2 = 1000.0

# ── İSTANBUL ─────────────────────────────────────────────────────────────────
ISTANBUL_ILCELER = [
    "Adalar", "Arnavutköy", "Ataşehir", "Avcılar", "Bağcılar",
    "Bahçelievler", "Bakırköy", "Başakşehir", "Bayrampaşa", "Beşiktaş",
    "Beykoz", "Beylikdüzü", "Beyoğlu", "Büyükçekmece", "Çatalca",
    "Çekmeköy", "Esenler", "Esenyurt", "Eyüpsultan", "Fatih",
    "Gaziosmanpaşa", "Güngören", "Kadıköy", "Kağıthane", "Kartal",
    "Küçükçekmece", "Maltepe", "Pendik", "Sancaktepe", "Sarıyer",
    "Şile", "Silivri", "Şişli", "Sultanbeyli", "Sultangazi",
    "Tuzla", "Ümraniye", "Üsküdar", "Zeytinburnu",
]
