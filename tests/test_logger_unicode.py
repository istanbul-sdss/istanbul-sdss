"""
Regresyon (P2.3): Logger emoji/özel Unicode karakter taşıyan mesajlarda
UnicodeEncodeError fırlatmamalı.

Audit bulgusu: Önceki StreamHandler(sys.stdout) Windows cp1254 console'da
"✅", "→", emoji vb. yazarken patlıyor; CLI/test workflow'unda traceback
oluşuyordu. Artık _utf8_safe_stream wrapper UTF-8 + errors='replace' kullanır.
"""
from __future__ import annotations

import io
import logging
import sys

from src.logger import _utf8_safe_stream, get_logger


def test_utf8_safe_stream_handles_emoji_on_cp1254_buffer():
    """
    cp1254 BufferedWriter taklit edilse bile wrapper UTF-8 yazabilmeli
    (errors='replace' ile bozuk karakterler silinir, traceback olmaz).
    """
    raw_buf = io.BytesIO()
    cp1254_stream = io.TextIOWrapper(raw_buf, encoding="cp1254", errors="strict")
    safe = _utf8_safe_stream(cp1254_stream)
    # Doğrudan bozuk emoji yaz — patlamaması yeterli
    safe.write("✅ Tamam · → adım 1\n")
    safe.flush()
    # Veri buffer'a yazıldı (replace fallback olsa bile içerik gitti)
    assert raw_buf.getvalue(), "Stream UTF-8 wrapper'a hiç yazmadı"


def test_logger_does_not_crash_on_emoji():
    """
    Gerçek logger ile mesaj gönder — UnicodeEncodeError fırlamamalı.
    """
    log = get_logger("test.unicode")
    # Aşağıdakilerin hiçbiri exception fırlatmamalı
    log.info("✅ İşlem tamamlandı — 12 kayıt")
    log.warning("⚠️ Eksik veri tespit edildi → fallback uygulandı")
    log.error("❌ Bağlantı koptu, retry yapılıyor")
    # Buraya geldiyse pas
