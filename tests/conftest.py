"""
tests/conftest.py — ortak pytest altyapısı.

Proje kökünü sys.path'e ekliyor (src/, components/, vs. doğrudan import
edilebilsin). Streamlit sayfaları import edilmez — onlar app-runtime'da
çalışır; testler mantık modüllerine odaklıdır.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Proje kökü (bu dosya: tests/conftest.py → parent.parent = proje kökü)
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# H6 not: pyproj/numpy/geopandas DeprecationWarning bastırması pytest.ini
# `filterwarnings` üzerinden uygulanır (pytest test koleksiyonu sırasında
# conftest.py'deki `warnings.filterwarnings` çağrılarını override ediyor).
# Production runtime bastırması src/logger.py'dedir.
