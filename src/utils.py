from pathlib import Path

import pandas as pd

from src.config.settings import OUTPUT_DIR


def ensure_output_folder(path: Path = OUTPUT_DIR) -> Path:
    """
    Output klasörünü oluşturur (yoksa).
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_ext(ext: str | None) -> str:
    """
    Uzantıyı normalize eder.
    '.csv' -> 'csv'
    """
    if not ext:
        return ""

    return str(ext).replace(".", "").strip()


def get_output_path(filename: str, prefix: str = "", ext: str = "") -> str:
    """
    Output dosya path'ini oluşturur.

    Örnek:
    get_output_path("buildings", "kadikoy", "csv")
    -> outputs/kadikoy_buildings.csv
    """
    ensure_output_folder()

    name = str(filename).strip()
    if not name:
        raise ValueError("filename boş olamaz")

    cleaned_prefix = str(prefix).strip()
    if cleaned_prefix:
        name = f"{cleaned_prefix}_{name}"

    cleaned_ext = normalize_ext(ext)
    if cleaned_ext:
        name = f"{name}.{cleaned_ext}"

    return str(OUTPUT_DIR / name)


# ── Cache key helpers (H3) ────────────────────────────────────────────────
# DataFrame içerik tabanlı stabil hash. Bytes cache (Excel/CSV builder)
# anahtarlarında `id(df)` GC sonrası yeniden kullanım nedeniyle ender ama
# mümkün yanlış-hit oluşturuyordu; hash içerik bazlıdır → güvenli.

def df_content_hash(df: pd.DataFrame | None) -> int:
    """
    DataFrame içeriği için deterministik 64-bit hash.

    Boş DataFrame için sadece kolon imzasını hashler. Hashlenmesi mümkün
    olmayan hücreler (list/dict/geometry vb.) varsa stringe düşürerek
    devam eder — yavaşlar ama crash etmez.

    Performans: pandas `hash_pandas_object` O(n×m) uint64; Kadıköy
    boyutunda ~10-30ms, büyük ilçelerde ~200ms. Excel rebuild süresi
    (1-3s) yanında ihmal edilebilir.
    """
    if df is None:
        return 0
    if df.empty:
        return hash(("__empty__", tuple(df.columns)))
    try:
        return int(pd.util.hash_pandas_object(df, index=False).sum())
    except TypeError:
        return hash(tuple(df.astype(str).itertuples(index=False, name=None)))


def nonempty_signature(nonempty: dict) -> tuple:
    """
    `{kategori: {"df": DataFrame, ...}}` sözlüğü için stabil cache anahtarı.

    Kategoriler sıralı işlenir → anahtar deterministik. Her kategori için
    (key, df içerik hash, len) üçlüsü; tek bir df değişse bile imza değişir.
    """
    return tuple(
        (k, df_content_hash(v["df"]), len(v["df"]))
        for k, v in sorted(nonempty.items())
    )
