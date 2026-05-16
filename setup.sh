#!/usr/bin/env bash
# Istanbul SDSS — macOS / Linux kurulum scripti.
# Tek seferlik: virtualenv kurar, bağımlılıkları yükler.

set -e   # ilk hatada dur

echo "================================================================"
echo "  Istanbul SDSS — macOS / Linux Setup"
echo "================================================================"
echo

# Python 3.10+ kontrolü
if ! command -v python3 >/dev/null 2>&1; then
    echo "[HATA] python3 bulunamadı. Python 3.10+ yükleyin:"
    echo "       brew install python   (macOS)"
    echo "       sudo apt install python3 python3-venv   (Ubuntu/Debian)"
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Bulunan Python: $PY_VERSION"

# Gerçek sürüm karşılaştırması (sys.version_info >= (3, 10))
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "[HATA] Python sürümü yetersiz: $PY_VERSION (en az 3.10 gerekli)"
    echo "       Yeni sürüm: brew install python@3.11 / sudo apt install python3.11"
    exit 1
fi

# venv yoksa oluştur
if [ ! -d "venv" ]; then
    echo "[1/2] Sanal ortam oluşturuluyor..."
    python3 -m venv venv
else
    echo "[1/2] Sanal ortam zaten mevcut, atlandı."
fi

# Bağımlılıkları yükle
echo "[2/2] Bağımlılıklar yükleniyor (birkaç dakika sürebilir)..."
# shellcheck disable=SC1091
source venv/bin/activate
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt

echo
echo "================================================================"
echo "  Kurulum tamamlandı."
echo "  Çalıştırmak için:"
echo "    ./run_data_tool.sh        (Veri Çıkartma — ana sayfa)"
echo "    ./run_optimizer.sh        (Toplanma alanı optimizasyonu)"
echo "================================================================"
