"""
Sprint 2 #12: a11y koruması — `label_visibility="collapsed"` widget'ları
anlamlı label string'i kullanmalı.

Streamlit'in `collapsed` modu görsel olarak label'ı gizler ama label
argümanını aria-label olarak korur (screen-reader bunu duyar). Boş veya
çok kısa label kullanılırsa erişilebilirlik kırılır.

Bu test, repo'daki tüm Streamlit widget çağrılarını tarayıp
`label_visibility="collapsed"` ile birlikte verilen label string'inin
yeterince anlamlı olduğunu (en az 3 karakter, "x" veya " " gibi
plaholder olmaması) doğrular.

Yeni widget eklenirken bu test development sırasında erken uyarı verir.
"""
from __future__ import annotations

import re
from pathlib import Path

# Streamlit widget'ları (label_visibility kabul edenler)
_WIDGET_FUNCS = (
    "text_input", "selectbox", "number_input", "multiselect", "radio",
    "checkbox", "slider", "date_input", "text_area", "file_uploader",
    "toggle", "color_picker",
)

# Repo kökü (testin dizininin üst klasörü)
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Hariç tutulan yollar — başka projelerin/worktrees'lerin kopyaları
_EXCLUDE_PARTS = {".claude", "venv", ".venv", "__pycache__", ".pytest_cache"}


def _python_files() -> list[Path]:
    files = []
    for f in _REPO_ROOT.rglob("*.py"):
        if any(part in _EXCLUDE_PARTS for part in f.parts):
            continue
        files.append(f)
    return files


def _find_collapsed_widgets(src: str) -> list[tuple[str, str]]:
    """
    src içinde `label_visibility="collapsed"` kullanan widget çağrılarını
    bulur, (widget_name, label_string) listesi döner.
    """
    funcs_alt = "|".join(_WIDGET_FUNCS)
    # Çoklu-satırlık çağrıları yakalamak için DOTALL
    pattern = re.compile(
        rf'st\.({funcs_alt})\s*\(\s*'
        rf'(["\'].*?["\'])'             # ilk pozisyonel arg = label
        rf'[^)]*?label_visibility=["\']collapsed["\']',
        re.DOTALL,
    )
    out = []
    for m in pattern.finditer(src):
        widget = m.group(1)
        # Triple-quoted veya tek-tırnak/çift-tırnak normalize et
        label_raw = m.group(2)
        # Outer quotes'u soy
        label = label_raw.strip("'\"")
        out.append((widget, label))
    return out


def test_all_collapsed_widgets_have_meaningful_label():
    """
    Tüm `label_visibility="collapsed"` widget'ları en az 3 karakterlik
    anlamlı bir label string'i kullanmalı. Boş, "x", "  ", "..." vb.
    placeholder'lar reddedilir.
    """
    invalid_labels = {"", "x", "X", "...", "label", "—", "-"}
    issues: list[str] = []
    total_found = 0

    for f in _python_files():
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for widget, label in _find_collapsed_widgets(src):
            total_found += 1
            stripped = label.strip()
            if len(stripped) < 3 or stripped.lower() in invalid_labels:
                issues.append(
                    f"{f.relative_to(_REPO_ROOT)}: st.{widget}(...) "
                    f"with weak label {label!r}"
                )

    assert not issues, (
        f"a11y regresyon: {len(issues)} widget zayıf label kullanıyor "
        f"(toplam {total_found} collapsed widget incelendi):\n"
        + "\n".join(f"  - {i}" for i in issues)
    )


def test_at_least_some_collapsed_widgets_exist():
    """
    Sanity: en az 1 collapsed widget bulunmalı. Eğer regex yanlış
    çalışıyorsa veya tüm collapsed kullanımı kalkmışsa bu fail eder.
    """
    total = 0
    for f in _python_files():
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        total += len(_find_collapsed_widgets(src))
    assert total >= 1, "Hiç collapsed widget bulunamadı — regex hatalı olabilir"
