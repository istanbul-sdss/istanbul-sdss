"""
Streamlit pages/ klasörü için AppTest smoke testleri (B2).

test_streamlit_smoke.py top-level entry'leri (Optimization_Tool,
Spatial_Data_Collection_Tool) kapsıyor; bu modül 5 alt sayfayı (Data
Extraction, Map Visualization, Analytics Dashboard, Name Lookup,
Neighborhood Sync) kapsar.

Felsefe: derinlikten ziyade GENİŞLİK. Her sayfa boş/varsayılan state'te
istisna fırlatmadan render olmalı, en az bir markdown bloğu çıkarmalı.
Tablo/harita render etmeyen sayfalar (henüz veri yok) "empty-state"
mesajı bastırır; smoke testleri bunu yakalar. Detay etkileşim testleri
ileride (Faz 3) eklenecek.

Pages için tipik regresyonlar bu testlerin yakalayacağı şeyler:
- Import zincirinde kırık modül (örn. translations.py'den kaldırılmış
  bir sembolü hâlâ kullanan sayfa)
- session_state KeyError (init_state çağrılmamış / yanlış key)
- empty-state branch'inde NaN / boş DataFrame üzerinde patlayan
  pandas op
- Deprecated st.* API (st.experimental_*) sürüm yükseldiğinde
"""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

# 5 sayfa render'ı CI'da süresiz takılmasın. Pages tipik olarak <5s;
# 30s rahat tampon.
SMOKE_TIMEOUT_S = 30

PAGES_DIR = Path(__file__).resolve().parent.parent / "pages"

PAGES = [
    "1_Data_Extraction.py",
    "2_Map_Visualization.py",
    "3_Analytics_Dashboard.py",
    "4_Name_Lookup.py",
    "5_Neighborhood_Sync.py",
]


@pytest.mark.parametrize("page_filename", PAGES)
def test_page_renders_without_exception_in_empty_state(page_filename: str):
    """
    Her sayfa varsayılan/boş session_state ile import + render olmalı,
    hiç istisna fırlatmamalı.
    """
    page_path = PAGES_DIR / page_filename
    assert page_path.exists(), f"Sayfa dosyası bulunamadı: {page_path}"

    app = AppTest.from_file(str(page_path), default_timeout=SMOKE_TIMEOUT_S)
    app.run()

    assert not app.exception, (
        f"{page_filename} boş state'te istisna fırlattı: "
        f"{[(e.value, e.message) for e in app.exception]}"
    )


@pytest.mark.parametrize("page_filename", PAGES)
def test_page_emits_some_markdown(page_filename: str):
    """
    Her sayfa en az bir markdown öğesi (başlık, info banner, empty-state
    metni vb.) bastırmalı — sessiz/boş bir sayfa muhtemelen import zinciri
    kırılmış demektir.
    """
    page_path = PAGES_DIR / page_filename
    app = AppTest.from_file(str(page_path), default_timeout=SMOKE_TIMEOUT_S)
    app.run()

    # exception olmadığından emin ol (yukarıdaki test zaten kontrol ediyor ama
    # parametrize'da bağımsız çalıştırılırsa burada da yakalanır)
    assert not app.exception
    assert len(app.markdown) > 0, (
        f"{page_filename} hiç markdown üretmedi — büyük olasılıkla import "
        f"zinciri erken bir hata ile döndü."
    )
