"""
src/logger.py

Merkezi loglama yapılandırması.
Her modül: from src.logger import get_logger; log = get_logger(__name__)

P2.3 düzeltmesi: Windows console (cp1254) emoji/özel karakter yazarken
UnicodeEncodeError fırlatıyordu. Artık StreamHandler UTF-8 stream wrapper
kullanır; sistem desteklemese bile `errors="replace"` ile karakter düşürerek
hayatta kalır. Streamlit UI'sı bundan etkilenmez (kendi log akışını kullanır)
ama CLI/test/dev workflow'unda traceback olmaz.
"""

from __future__ import annotations

import io
import logging
import os
import sys
import warnings
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Log rotasyonu varsayılanları. 10 MB × 3 backup = en fazla 40 MB disk taahhüdü.
# Önceki davranış (sınırsız FileHandler) logs/app.log dosyasının zamanla GB
# seviyesine çıkmasına yol açabiliyordu; rotasyon bu sızıntıyı kapatır.
# Env override: LOG_MAX_BYTES, LOG_BACKUP_COUNT.
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_DEFAULT_BACKUP_COUNT = 3


def _resolve_level(name: str | None, default: int) -> int:
    """
    LOG_LEVEL env değerini logging seviyesine çevir.
    Geçersiz/boş değerde sessizce default'a düş — yanlış env değeri kullanıcının
    uygulamasını çökertmesin.
    """
    if not name:
        return default
    level = logging.getLevelName(name.strip().upper())
    return level if isinstance(level, int) else default

# ── Üçüncü-parti uyumsuzluk gürültüsünü bastır (H6) ──────────────────────────
# pyproj 3.7.x + numpy 2.x + geopandas 1.1.x: tek-noktalı `to_crs` çağrısında
# pyproj `_transform_point` ndim>0 array'i scalar bağlamında alıyor →
# `DeprecationWarning`. Bu bizim kullanımımızda yapısal: representative_point
# çıkışını tek-elemanlı `GeoSeries.to_crs` ile WGS84'e geri çeviriyoruz
# (spatial_service.add_representative_points, data_loader._to_point_gdf).
# Kaynaktan çözüm yok — geopandas internal `array.transform` yolunu kullanıyor.
# Upstream pyproj/geopandas birlikte düzeltene kadar bastırıyoruz; test
# loglarındaki 38 gürültü satırı temizlenir. Yeni sürümlerde bu filtre
# kaldırılmalı (en erken pyproj > 3.7 veya geopandas > 1.1 ile).
warnings.filterwarnings(
    "ignore",
    message=r"Conversion of an array with ndim > 0 to a scalar is deprecated",
    category=DeprecationWarning,
    module=r"pyproj\..*",
)


def _utf8_safe_stream(stream):
    """
    Verilen text stream'i UTF-8 ve `errors="replace"` ile sarar.
    Windows cp1254 console üzerinde emoji/özel karakter güvenli yazılır.
    """
    # Python 3.7+ TextIOWrapper.reconfigure mevcut → mümkünse orijinal stream'i
    # in-place yeniden yapılandır (referansları bozmamak için).
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
            return stream
        except Exception:
            pass
    # Düz dosya wrapper'ı: buffer var mı?
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        try:
            return io.TextIOWrapper(
                buffer, encoding="utf-8", errors="replace",
                line_buffering=True,
            )
        except Exception:
            pass
    return stream


# Modül yüklenirken stdout/stderr'i UTF-8'e ayarla. Streamlit yeniden başlatma
# senaryolarında zarar yok (idempotent).
sys.stdout = _utf8_safe_stream(sys.stdout)
sys.stderr = _utf8_safe_stream(sys.stderr)


def get_logger(name: str) -> logging.Logger:
    """
    Modül adına göre yapılandırılmış logger döner.
    İlk çağrıda handler'ları kurar, sonraki çağrılarda var olanı döner.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    # Logger seviyesi her zaman DEBUG; handler'lar kendi seviyelerini filtreler.
    # Konsol LOG_LEVEL env'ine göre kısılabilir (default INFO), dosya tam detayı
    # tutar (debug/postmortem analizleri için).
    logger.setLevel(logging.DEBUG)
    console_level = _resolve_level(os.getenv("LOG_LEVEL"), logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # Konsol handler — sys.stdout zaten utf-8 wrapper (yukarıda ayarlandı)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(console_level)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # Dosya handler — RotatingFileHandler ile sınırsız büyüme engellenir.
    #
    # Windows multi-process güvenliği:
    #   • `delay=True` → dosya ilk log mesajına kadar AÇILMAZ. Aynı anda
    #     birden fazla Python process aynı app.log'a yazıyorsa (örn. veri
    #     toplama tool'u + optimizer tool aynı anda açık) erken-açılan
    #     handler dosyayı kilitler ve rotation rename'i Windows'ta
    #     PermissionError [WinError 32] ile düşer. Lazy open bu kilit
    #     pencereyi daraltır — handler get_logger çağrısında değil, ilk
    #     log emit anında dosyaya dokunur.
    #   • Multi-worker production deployment için ileri seviye çözüm
    #     QueueHandler/QueueListener'dır; akademik kapsam için
    #     `delay=True` yeterli iyileşme sağlar (CI'da `delay`'siz versiyon
    #     da geçiyordu, ama lokal dev'de aynı anda iki app çalıştırınca
    #     test rotation kırılıyordu).
    try:
        # Log dizini: ISTANBUL_LOG_DIR env var ile override edilebilir.
        # Bu override testlerin izole `tmp_path` kullanmasını mümkün kılar —
        # paylaşımlı `logs/app.log` üzerinde Windows handle kilit yarışını
        # tetiklemez. Production'da env var set edilmez, default kullanılır.
        log_dir_override = os.getenv("ISTANBUL_LOG_DIR")
        if log_dir_override:
            log_dir = Path(log_dir_override)
        else:
            log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        max_bytes = int(os.getenv("LOG_MAX_BYTES", str(_DEFAULT_MAX_BYTES)))
        backup_count = int(os.getenv("LOG_BACKUP_COUNT", str(_DEFAULT_BACKUP_COUNT)))
        fh = RotatingFileHandler(
            log_dir / "app.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
            delay=True,   # lazy open — Windows kilit penceresini daraltır
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass  # Log dosyası açılamazsa sessizce devam et

    logger.propagate = False
    return logger
