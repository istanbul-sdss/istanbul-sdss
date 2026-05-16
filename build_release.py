#!/usr/bin/env python3
"""
build_release.py — Üçüncü-şahsa dağıtım için temiz ZIP üreticisi.

Kullanıcı (proje sahibi) çalıştırır → `dist/istanbul_sdss_<tarih>.zip`
oluşur. Bu ZIP'i hocaya/danışmana e-posta, USB, vb. yollarla gönderir;
alıcı taraf:
    1. ZIP'i istediği yere açar
    2. Klasöre girer
    3. setup.bat veya ./setup.sh çalıştırır
    4. run_data_tool / run_optimizer scriptleri ile başlatır

Bu script paylaşılmaması gereken klasörleri (venv, cache, output, logs,
__pycache__, .pytest_cache, vs.) bilinçli olarak haricleştirir.

Kullanım:
    python build_release.py             # varsayılan: dist/istanbul_sdss_<YYYYMMDD>.zip
    python build_release.py --name foo  # dist/foo.zip
    python build_release.py --verify    # üretim sonrası içerik denetimi
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import os
import sys
import zipfile
from pathlib import Path

# ── Ne dahil edilir / dışlanır ───────────────────────────────────────────────
# Klasörler — relative path eşleşmesi (tam dizin adı olarak)
EXCLUDE_DIRS = {
    "venv", ".venv", "env", "ENV",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".git", ".github" if False else None,   # .github (CI) DAHİL — bilinçli
    "cache",                # OSM cache — yeniden indirilebilir, çok büyük
    "output",               # kullanıcı çıktıları — gizli/spesifik olabilir
    "logs",                 # debug logları
    ".vscode", ".idea",
    "data/graphs",          # ilçe yürüme grafları (her biri 50-300 MB)
    "dist",                 # önceki release ZIP'leri
    ".claude",              # editör state'i (privé)
}
# None varsa filtrele
EXCLUDE_DIRS = {d for d in EXCLUDE_DIRS if d is not None}

# Dosya patternleri (suffix / glob)
EXCLUDE_FILE_SUFFIXES = (
    ".pyc", ".pyo", ".so", ".pyd",
    ".log", ".tmp", ".swp", ".swo",
    ".bak",                          # *.bak
)

EXCLUDE_FILE_NAMES = {
    ".DS_Store", "Thumbs.db",
    "secrets.toml",                  # .streamlit/secrets.toml
}

# *.geojson.bak.<ts> gibi neighborhood-sync yedekleri
EXCLUDE_FILE_CONTAINS = (
    ".geojson.bak.",
)


def _should_exclude(rel_path: Path) -> tuple[bool, str]:
    """rel_path proje köküne göredir (POSIX-style)."""
    parts = rel_path.parts
    posix = rel_path.as_posix()

    # Klasör eşleşmesi (yol içinde herhangi bir parça)
    for part in parts[:-1]:   # son parça dosya adı
        if part in EXCLUDE_DIRS:
            return True, f"dir excluded: {part}"
    # 2-parçalı klasör (ör. data/graphs)
    for ex in EXCLUDE_DIRS:
        if "/" in ex and posix.startswith(ex + "/"):
            return True, f"dir excluded: {ex}"

    # Dosya adı / suffix
    name = rel_path.name
    if name in EXCLUDE_FILE_NAMES:
        return True, f"file excluded: {name}"
    if name.endswith(EXCLUDE_FILE_SUFFIXES):
        return True, f"suffix excluded: {name}"
    for sub in EXCLUDE_FILE_CONTAINS:
        if sub in name:
            return True, f"contains excluded: {name}"

    return False, ""


def collect_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dpath = Path(dirpath)
        rel_dir = dpath.relative_to(root)
        # In-place klasör filtrelemesi (os.walk'a alt klasöre inme)
        # Direct match için dirnames'i mutate et
        keep_dirs = []
        for d in dirnames:
            sub_rel = (rel_dir / d).as_posix() if rel_dir != Path(".") else d
            excl = (
                d in EXCLUDE_DIRS
                or sub_rel in EXCLUDE_DIRS
            )
            if not excl:
                keep_dirs.append(d)
        dirnames[:] = keep_dirs

        for fn in filenames:
            full = dpath / fn
            rel = full.relative_to(root)
            excluded, _ = _should_exclude(rel)
            if not excluded:
                files.append(rel)
    return sorted(files)


def build_zip(root: Path, out: Path, archive_root_name: str) -> None:
    files = collect_files(root)
    out.parent.mkdir(parents=True, exist_ok=True)

    total_bytes = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for rel in files:
            full = root / rel
            arcname = (Path(archive_root_name) / rel).as_posix()
            zf.write(full, arcname)
            with contextlib.suppress(OSError):
                total_bytes += full.stat().st_size

    out_kb = out.stat().st_size / 1024
    print(f"\n[OK] Yazildi: {out}")
    print(f"   {len(files)} dosya · {total_bytes/1024/1024:.1f} MB ham · "
          f"{out_kb/1024:.1f} MB sıkıştırılmış")


def verify_zip(zip_path: Path) -> None:
    """Üretim sonrası sanity check: kritik dosyalar var mı, gizli olanlar yok mu?"""
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()

    n = len(names)
    # Kritik beklenenler
    must_exist = [
        "Spatial_Data_Collection_Tool.py",
        "Optimization_Tool.py",
        "requirements.txt",
        "setup.bat", "setup.sh",
        "run_data_tool.bat", "run_data_tool.sh",
        "run_optimizer.bat", "run_optimizer.sh",
        "README.md",
        "data/samples/Kadıköy_OSM_sample.xlsx",
        "data/mahalleleri/kadikoy.geojson",
    ]
    # Olmaması gerekenler
    must_not_exist_substrings = [
        "venv/", "/__pycache__/", "/.pytest_cache/",
        "/cache/", "/output/", "/logs/",
        ".pyc",
    ]

    missing: list[str] = []
    leaked: list[str] = []
    archive_root = names[0].split("/", 1)[0] if names else ""
    for must in must_exist:
        full = f"{archive_root}/{must}"
        if not any(full == n or n.endswith("/" + must) for n in names):
            missing.append(must)
    for n_ in names:
        for s in must_not_exist_substrings:
            if s in n_:
                leaked.append(n_)
                break

    print("\n-- Dogrulama --")
    print(f"   Toplam: {n} dosya")
    if missing:
        print(f"   [HATA] EKSIK ({len(missing)}):")
        for m in missing:
            print(f"      - {m}")
    else:
        print("   [OK] Tum kritik dosyalar mevcut")
    if leaked:
        print(f"   [UYARI] SIZINTI ({len(leaked)}, ilk 5):")
        for m in leaked[:5]:
            print(f"      - {m}")
    else:
        print("   [OK] Hicbir haric-tutulan klasorden dosya sizmamis")
    if missing or leaked:
        print("   -> Sorun var; build_release.py EXCLUDE_* listelerini gozden gecirin.")
        sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--name", default=None,
        help="ZIP base adı (uzantısız). Varsayılan: istanbul_sdss_<YYYYMMDD>",
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Üretim sonrası içerik denetimi yap",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    today = dt.datetime.now().strftime("%Y%m%d")
    name = args.name or f"istanbul_sdss_{today}"
    archive_root = name
    out = root / "dist" / f"{name}.zip"

    print(f"Proje kökü: {root}")
    print(f"Çıktı     : {out}")
    print(f"Arşiv kök : {archive_root}/")
    print(f"Hariç     : {len(EXCLUDE_DIRS)} klasör · "
          f"{len(EXCLUDE_FILE_SUFFIXES)} suffix")

    build_zip(root, out, archive_root)

    if args.verify:
        verify_zip(out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
