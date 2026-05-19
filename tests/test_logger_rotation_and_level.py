"""
Regresyon: src/logger.py LOG_LEVEL env değerini honoring etmeli ve
RotatingFileHandler ile dosya boyutu sınırlanmalı (önceki sınırsız
FileHandler logs/app.log'un GB seviyesine çıkmasına yol açabiliyordu).

LOG_LEVEL geçersiz/boş ise sessizce INFO'ya düşmeli (kullanıcı yanlış
env değeri ile uygulamayı çökertmesin).
"""
from __future__ import annotations

import contextlib
import importlib
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _reload_logger():
    """src.logger modülünü yeniden yükler — env override değişikliklerini test et."""
    if "src.logger" in sys.modules:
        del sys.modules["src.logger"]
    return importlib.import_module("src.logger")


def _reset_named_logger(name: str) -> None:
    """get_logger handler cache'ini bypass etmek için adlandırılmış logger'ı sıfırla."""
    lg = logging.getLogger(name)
    for h in list(lg.handlers):
        lg.removeHandler(h)
        with contextlib.suppress(Exception):
            h.close()


def test_resolve_level_valid_names():
    logger_mod = _reload_logger()
    assert logger_mod._resolve_level("DEBUG", logging.INFO) == logging.DEBUG
    assert logger_mod._resolve_level("warning", logging.INFO) == logging.WARNING
    assert logger_mod._resolve_level("  Error ", logging.INFO) == logging.ERROR
    assert logger_mod._resolve_level("CRITICAL", logging.INFO) == logging.CRITICAL


def test_resolve_level_invalid_falls_back():
    logger_mod = _reload_logger()
    assert logger_mod._resolve_level("BOGUS", logging.INFO) == logging.INFO
    assert logger_mod._resolve_level("", logging.WARNING) == logging.WARNING
    assert logger_mod._resolve_level(None, logging.WARNING) == logging.WARNING


def test_default_console_level_is_info(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    logger_mod = _reload_logger()
    _reset_named_logger("test.default_level")
    log = logger_mod.get_logger("test.default_level")
    stream_handlers = [h for h in log.handlers if isinstance(h, logging.StreamHandler)
                       and not isinstance(h, RotatingFileHandler)]
    assert stream_handlers, "Konsol handler kurulmadı"
    assert stream_handlers[0].level == logging.INFO


def test_log_level_env_honoured(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    logger_mod = _reload_logger()
    _reset_named_logger("test.env_level")
    log = logger_mod.get_logger("test.env_level")
    stream_handlers = [h for h in log.handlers if isinstance(h, logging.StreamHandler)
                       and not isinstance(h, RotatingFileHandler)]
    assert stream_handlers[0].level == logging.WARNING


def test_log_level_invalid_does_not_crash(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "TOTALLY_BOGUS")
    logger_mod = _reload_logger()
    _reset_named_logger("test.invalid_level")
    log = logger_mod.get_logger("test.invalid_level")
    stream_handlers = [h for h in log.handlers if isinstance(h, logging.StreamHandler)
                       and not isinstance(h, RotatingFileHandler)]
    # Geçersiz env değeri sessizce INFO'ya düşer
    assert stream_handlers[0].level == logging.INFO


def test_file_handler_is_rotating(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    logger_mod = _reload_logger()
    _reset_named_logger("test.rotating_check")
    log = logger_mod.get_logger("test.rotating_check")
    rotating = [h for h in log.handlers if isinstance(h, RotatingFileHandler)]
    assert rotating, "RotatingFileHandler kurulmadı — sınırsız büyüme riski"
    # Varsayılan 10 MB × 3 backup
    assert rotating[0].maxBytes == 10 * 1024 * 1024
    assert rotating[0].backupCount == 3


def test_file_handler_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_MAX_BYTES", "2048")
    monkeypatch.setenv("LOG_BACKUP_COUNT", "5")
    logger_mod = _reload_logger()
    _reset_named_logger("test.env_rotation")
    log = logger_mod.get_logger("test.env_rotation")
    rotating = [h for h in log.handlers if isinstance(h, RotatingFileHandler)]
    assert rotating[0].maxBytes == 2048
    assert rotating[0].backupCount == 5


def _close_all_app_log_handlers():
    """
    Diskteki logs/app.log dosyasını tutan TÜM handler'ları kapat.
    Windows'ta açık handle olan dosya rename edilemez; bu fonksiyon olmadan
    test suite içinde önceki testlerin oluşturduğu src.* logger'ları rotasyonu
    engeller (WinError 32). Tüm test sonrası loggerlar zaten get_logger ile
    yeniden init olduğunda fresh handler alır — kalıcı yan etki yok.
    """
    manager = logging.Logger.manager
    for name in list(manager.loggerDict.keys()):
        lg = logging.getLogger(name)
        for h in list(lg.handlers):
            # RotatingFileHandler veya FileHandler tabanlı tüm dosya handler'ları
            if isinstance(h, logging.FileHandler):
                lg.removeHandler(h)
                with contextlib.suppress(Exception):
                    h.close()


def test_rotation_actually_happens(tmp_path, monkeypatch):
    """
    Küçük maxBytes ile zorlayıp gerçek bir rotasyon dönüşünün diskte
    oluştuğunu doğrula.

    Windows-safe refactor:
        Eski versiyon paylaşımlı `src/../logs/app.log` dosyasını kullanıyordu;
        aynı anda başka bir process (Streamlit oturumu, başka test runner)
        bu dosyayı açık tutuyorsa Windows `app.log → app.log.1` rename'i
        WinError 32 ile düşürüyor — test koşullu olarak fail. Yeni versiyon
        `ISTANBUL_LOG_DIR` env var override ile izole `tmp_path` kullanır;
        global log dizinine hiç dokunmaz, paralel process'lerden bağımsız.
    """
    # İzole log dizinine yönlendir — bu test global logs/app.log'a dokunmaz.
    monkeypatch.setenv("ISTANBUL_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_MAX_BYTES", "512")
    monkeypatch.setenv("LOG_BACKUP_COUNT", "2")

    # Önceki testlerden kalan handle'ları temizle (zaten artık bizim
    # tmp_path'i kullanıyoruz ama belt-and-suspenders).
    _close_all_app_log_handlers()
    logger_mod = _reload_logger()
    _reset_named_logger("test.actual_rotation")

    log_path = tmp_path / "app.log"
    backup1 = tmp_path / "app.log.1"

    log = logger_mod.get_logger("test.actual_rotation")
    # 512 byte'ı geçecek kadar mesaj yaz (her satır > 80 byte)
    for i in range(100):
        log.info(f"row {i} - filler line long enough to bust 512 bytes " + "x" * 50)

    # Handle'ı kapat ki dosya boyutu doğru ölçülsün ve OS flush etsin
    for h in list(log.handlers):
        if isinstance(h, RotatingFileHandler):
            with contextlib.suppress(Exception):
                h.close()

    # En az bir rotasyon backup'ı oluşmuş olmalı
    assert backup1.exists(), (
        f"Rotasyon tetiklenmedi; {backup1} oluşmadı. "
        f"tmp_path içeriği: {list(tmp_path.iterdir())}"
    )
    # Ana dosya yine var ve boyutu maxBytes civarı
    assert log_path.exists()

    # Cleanup
    for h in list(log.handlers):
        log.removeHandler(h)
        with contextlib.suppress(Exception):
            h.close()
    for p in [backup1, log_path.with_name("app.log.2")]:
        if p.exists():
            with contextlib.suppress(PermissionError):
                p.unlink()
