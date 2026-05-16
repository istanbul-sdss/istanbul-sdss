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
import sys
import warnings
from pathlib import Path

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

    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # Konsol handler — sys.stdout zaten utf-8 wrapper (yukarıda ayarlandı)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # Dosya handler
    try:
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        fh = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass  # Log dosyası açılamazsa sessizce devam et

    logger.propagate = False
    return logger
