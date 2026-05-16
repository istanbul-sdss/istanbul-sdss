#!/usr/bin/env bash
# Toplanma alanı optimizasyonu — ayrı Streamlit uygulaması.
# Veri Çıkartma aracının aynı anda çalışması için farklı port (8502) kullanır.

set -e

if [ ! -f "venv/bin/activate" ]; then
    echo "[HATA] venv yok. Önce ./setup.sh çalıştırın."
    exit 1
fi

# shellcheck disable=SC1091
source venv/bin/activate
streamlit run Optimization_Tool.py --server.port 8502
