#!/usr/bin/env bash
# Veri Çıkartma aracı — Streamlit ana sayfa.
# Otomatik olarak tarayıcıda açılır (varsayılan: http://localhost:8501).

set -e

if [ ! -f "venv/bin/activate" ]; then
    echo "[HATA] venv yok. Önce ./setup.sh çalıştırın."
    exit 1
fi

# shellcheck disable=SC1091
source venv/bin/activate
streamlit run Spatial_Data_Collection_Tool.py
