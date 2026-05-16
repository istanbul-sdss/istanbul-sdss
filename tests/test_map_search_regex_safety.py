"""
Regresyon (P2.1): Map sayfasındaki arama kutusunun regex=False kullanması.

Audit bulgusu: pages/2_Map_Visualization.py içindeki search aşaması
str.contains(patt, na=False) ile çağrılıyordu — regex parametresi default
True. Kullanıcı '[' veya '(' yazınca pandas re.error fırlatıp sayfayı
kırıyordu. Data Extraction'da re.escape vardı, harita sayfası unutulmuş.

Test: pandas davranışını doğrudan kullanarak (sayfa import edilmiyor — Streamlit
test edilmesi zor) regex=False ile geçersiz regex karakterinin kabul edildiğini
ve regex=True ile patladığını gösterir; ardından dosyada kullanımın doğru
olduğunu lock'lar.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest


def test_str_contains_with_regex_false_handles_brackets():
    """Bu pandas'ın garantisi — regex=False ile [ güvenli."""
    s = pd.Series(["foo [bar]", "abc"])
    out = s.str.contains("[bar]", na=False, regex=False)
    assert out.tolist() == [True, False]


def test_str_contains_with_regex_true_blows_up_on_brackets():
    """
    Eski davranış — kullanıcının dert ettiği. Geçersiz regex pattern'inde
    bir exception fırlamalı.

    Backend-toleranslı: pandas python regex backend'i `re.error` fırlatırken,
    pyarrow string backend'i `pyarrow.lib.ArrowInvalid` fırlatır. İkisi de
    `Exception`'ın altında; spesifik sınıfa kilitlemek ortam drift'ine karşı
    kırılgan (pandas 2 → 3 geçişinde test bu yüzden kırılmıştı). Burada
    sadece "regex=True ile geçersiz pattern hata fırlatır" davranışını
    lock'luyoruz.
    """
    s = pd.Series(["foo [bar]", "abc"])
    with pytest.raises(Exception) as exc_info:
        s.str.contains("[", na=False, regex=True)
    # Hata mesajı regex/pattern ile ilgili olmalı; başka bir bug'ı yakalamayalım.
    # Python sürümleri arasında farklı kelimeler kullanılıyor (Python 3.10
    # "regex"/"pattern", 3.11+ bazen "character set", "bracket" vb.).
    # Sürüm-toleranslı: bu tokenlerden HERHANGİ BİRİ geçerse regex parse hatası
    # olduğunu kabul ediyoruz.
    msg = str(exc_info.value).lower()
    expected_tokens = (
        "regex", "pattern", "[", "bracket",
        "character set", "character class",   # Python 3.11+ wording
        "unterminated", "missing",             # genel parser hata sözcükleri
    )
    assert any(token in msg for token in expected_tokens), (
        f"Beklenen regex parse hatası değil: {exc_info.value!r}"
    )


def test_map_visualization_uses_regex_false():
    """pages/2_Map_Visualization.py kaynak kodu str.contains'te regex=False kullansın."""
    src = Path("pages/2_Map_Visualization.py").read_text(encoding="utf-8")
    # Aramada str.contains varsa regex=False de geçmeli
    assert "regex=False" in src, (
        "REGRESYON: pages/2_Map_Visualization.py içinde str.contains "
        "regex=False parametresiyle çağrılmıyor — kullanıcı '[' yazarsa "
        "sayfa pandas re.error ile kırılır."
    )
