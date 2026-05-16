"""
Streamlit AppTest smoke testleri.

Compile-level kontrol CI'da zaten yapılıyor (`python -m compileall`); bu
testler bir adım derinde: Streamlit runtime ile sayfa baştan-sona render
ediliyor, hiç istisna fırlatmamalı.

Kapsam:
  1. Home (Spatial_Data_Collection_Tool.py) — boş state'te render.
  2. Optimization_Tool.py — boş state'te render (hiç data yüklü değil).
  3. Optimization_Tool.py — örnek Excel yüklenmiş state'te render
     (data/samples/Kadıköy_OSM_sample.xlsx üzerinden offline).

Test felsefesi: derinlikten ziyade GENİŞLİK — UI/state/import yolu boyunca
kırılan herhangi bir şey CI'da yakalansın. Detay davranış zaten birim
testlerle kapsanmış (~290 test). Bu üç testin maliyeti ~10s, kazancı yüksek:
mega-dosyaları (Optimization_Tool.py 1572 satır, 4_Name_Lookup.py 889) ileride
parçalarken regresyonu burada görürüz.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# AppTest API — Streamlit 1.28+. requirements.txt streamlit>=1.32 garanti.
from streamlit.testing.v1 import AppTest

# Smoke testlerin tek tek baş edemediği durumlarda CI'ı süresiz takılmasın
# diye explicit timeout (saniye). Boş sayfa render < 2s, sample-load yolu
# pandas+openpyxl ile ~5s.
SMOKE_TIMEOUT_S = 30


# ── 1. Home page (boş state) ────────────────────────────────────────────────
def test_home_page_renders_without_exception():
    """Spatial_Data_Collection_Tool.py modülü baştan-sona hiç hata fırlatmamalı.

    Bu test başlangıçta `from src.config.tag_rules import TAG_RULES` import
    zincirini, `category_registry ↔ tag_rules` uyumluluk RuntimeError'unu
    ve tüm sidebar/hero/CTA HTML üretimini kapsar.
    """
    app = AppTest.from_file("Spatial_Data_Collection_Tool.py", default_timeout=SMOKE_TIMEOUT_S)
    app.run()
    # Hiç istisna olmamalı (.exception streamlit'in toplayıcı listesi)
    assert not app.exception, (
        f"Home sayfası render sırasında istisna fırlattı: "
        f"{[(e.value, e.message) for e in app.exception]}"
    )
    # Markdown/title öğeleri üretilmiş olmalı (smoke; tam metni doğrulamıyoruz)
    # Basit bir varlık kontrolü — başlık veya markdown bloğu var mı?
    assert len(app.markdown) > 0, "Home sayfası hiç markdown üretmedi"


# ── 2. Optimization_Tool — boş state ────────────────────────────────────────
def test_optimization_tool_renders_empty_state():
    """Optimization_Tool.py veri yüklü olmadan açıldığında patlamamalı."""
    app = AppTest.from_file("Optimization_Tool.py", default_timeout=SMOKE_TIMEOUT_S)
    app.run()
    assert not app.exception, (
        f"Optimization_Tool boş state'te istisna fırlattı: "
        f"{[(e.value, e.message) for e in app.exception]}"
    )
    # "Waiting for input data" gibi empty-state mesajı bekliyoruz; başlık
    # render edildi mi?
    assert len(app.markdown) > 0


# ── 3. Optimization_Tool — sample data yüklenmiş ────────────────────────────
_SAMPLE_XLSX = Path(__file__).resolve().parent.parent / "data" / "samples" / "Kadıköy_OSM_sample.xlsx"


@pytest.mark.skipif(
    not _SAMPLE_XLSX.exists(),
    reason=f"Sample Excel yok: {_SAMPLE_XLSX}",
)
def test_optimization_tool_renders_with_sample_data_loaded():
    """
    Sample veriyi session_state'e doğrudan enjekte edip sayfanın
    "veri yüklü ama OD matrisi henüz hesaplanmamış" durumunu render
    etmesini test eder.

    Streamlit Excel file_uploader'ı AppTest'te tetiklenemediğinden veriyi
    `load_from_excel` ile yükleyip session_state'e koyuyoruz; uygulama
    aynı state'i Reset düğmesi ile sıfırlanmış başlangıç gibi görür.
    """
    from src.optimizer.data_loader import list_excel_sheets, load_from_excel

    sheets = list_excel_sheets(_SAMPLE_XLSX)
    # Sample workbook: "Konut - Genel" (bina) + "Toplanma Alanı"
    bina_sheet = next((s for s in sheets if "Konut" in s or "Resid" in s), sheets[0])
    top_sheet = next((s for s in sheets if "Toplanma" in s or "Assembly" in s), sheets[-1])

    b, t = load_from_excel(_SAMPLE_XLSX, bina_sheet, top_sheet)
    assert len(b) > 0 and len(t) > 0, "Sample Excel boş çıktı verdi"

    app = AppTest.from_file("Optimization_Tool.py", default_timeout=SMOKE_TIMEOUT_S)
    # Veriyi session_state'e enjekte et — Optimization_Tool.py'nin _DEFAULTS
    # anahtarlarıyla aynı isimlerde olmalı.
    app.session_state["opt_buildings"] = b
    app.session_state["opt_assembly"] = t
    app.session_state["opt_district"] = "Kadıköy"

    app.run()

    assert not app.exception, (
        f"Optimization_Tool veri yüklü iken istisna fırlattı: "
        f"{[(e.value, e.message) for e in app.exception]}"
    )
    # KPI kartları render edildiyse markdown çıktısında "Buildings" veya
    # "Assembly areas" labelları görünmeli (KPI metric kartları markdown ile
    # çiziliyor).
    rendered_text = " ".join(m.value for m in app.markdown if hasattr(m, "value"))
    assert "Buildings" in rendered_text or "Assembly" in rendered_text, (
        "Sample veri yüklü render'da KPI label'ları görünmedi"
    )
