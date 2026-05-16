"""
src/optimizer/population_estimator.py

Bina bazlı nüfus tahmini — TÜİK 2023 istatistiklerine dayalı.

Neden ayrı modül?
-----------------
Optimizasyon motoru "kaç kişi bu binada yaşıyor?" sorusuna cevap ister, çünkü
p-median hedef fonksiyonu kişi başına yürüme süresini minimize eder, bina başına
değil. Ayrıca raporda varsayımların izlenebilir/savunulabilir olması gerekir.

Varsayımlar (kaynaklar raporda bölüm 3.2):
  • İstanbul ortalama hanehalkı büyüklüğü : 3.24 kişi
      (TÜİK, Adrese Dayalı Nüfus Kayıt Sistemi 2023)
  • Ortalama daire brüt alanı             : 120 m²
      (TÜİK, Konut Satış İstatistikleri 2023)
  • Net kullanım oranı                    : 0.85
      (Brüt → net alan; duvarlar, ortak alan, şaft vb. düşüldükten sonra)
  • Sonuç katsayısı                        : 0.025 kişi/m² (brüt, kat başına)

Formül:
    nüfus ≈ footprint_m² × levels × POP_PER_M2

Notlar:
  • Bu tahmin **konut** binaları içindir. Ticari/ofis/endüstriyel binalar için
    fazla tahmin edilir — afet toplanma alanı bağlamında aşırı temkinli bir
    sınır sayılır (worst-case).
  • `levels` yoksa ilçe medyanı yerine şimdilik 4 (İstanbul genel medyanı)
    kullanılıyor. Daha sofistike bir yaklaşım için ilçe-bazlı medyan geçilebilir.
  • Minimum nüfus 1 kişi; çok küçük binalarda (garaj, depo) 0 tahmini üretilmez
    çünkü optimizasyon 0 ağırlıklı noktalarda dejenere olur.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.config.settings import (
    AFAD_M2_PER_PERSON as _SETTINGS_AFAD_M2_PER_PERSON,
)
from src.config.settings import (
    AVG_DWELLING_M2_GROSS as _SETTINGS_AVG_DWELLING_M2_GROSS,
)
from src.config.settings import (
    DEFAULT_BUILDING_LEVELS as _SETTINGS_DEFAULT_LEVELS,
)
from src.config.settings import (
    HOUSEHOLD_SIZE_IST as _SETTINGS_HOUSEHOLD_SIZE_IST,
)
from src.config.settings import (
    NET_USAGE_RATIO as _SETTINGS_NET_USAGE_RATIO,
)
from src.config.settings import (
    POP_PER_M2_CONSERVATIVE as _SETTINGS_POP_PER_M2_CONSERVATIVE,
)

# ── Varsayım sabitleri (merkez: src/config/settings.py) ─────────────────────
HOUSEHOLD_SIZE_IST    = _SETTINGS_HOUSEHOLD_SIZE_IST
AVG_DWELLING_M2_GROSS = _SETTINGS_AVG_DWELLING_M2_GROSS
NET_USAGE_RATIO       = _SETTINGS_NET_USAGE_RATIO

# Net alan başına kişi: 3.24 / (120 × 0.85) ≈ 0.0318
# Brüt alan başına kişi (koridorlar, ortak alan düşülmeden): 0.025
# Bina footprint'i zaten brüt alandır → 0.025 doğru katsayı
# (Tarihsel referans: HOUSEHOLD_SIZE_IST / AVG_DWELLING_M2_GROSS ≈ 0.027 —
#  net alan formülü; production kodu net→brüt dönüşüm sonrası
#  POP_PER_M2_CONSERVATIVE = 0.025 kullanır.)
POP_PER_M2_CONSERVATIVE = _SETTINGS_POP_PER_M2_CONSERVATIVE

DEFAULT_LEVELS = _SETTINGS_DEFAULT_LEVELS

# AFAD toplanma alanı standardı — kişi başına düşen m²
AFAD_M2_PER_PERSON = _SETTINGS_AFAD_M2_PER_PERSON


def estimate_population(
    alan_m2: float | pd.Series | np.ndarray,
    levels: float | pd.Series | np.ndarray | None = None,
    pop_per_m2: float = POP_PER_M2_CONSERVATIVE,
    min_population: float = 1.0,
) -> float | pd.Series | np.ndarray:
    """
    Bina footprint'i ve kat sayısından nüfus tahmini üretir.

    Parametreler:
        alan_m2        : Bina footprint alanı (m²).
        levels         : Kat sayısı. None → DEFAULT_LEVELS kullanılır.
        pop_per_m2     : Brüt m² başına kişi katsayısı.
        min_population : Minimum tahmin (küçük binalarda bile 0 olmasın).

    Dönüş:
        Skaler girdilerde skaler, Series/array girdilerde aynı tipte.
    """
    if levels is None:
        levels = DEFAULT_LEVELS

    # numpy/pandas operasyonları birlikte çalışsın diye dikkatli
    alan  = pd.to_numeric(alan_m2, errors="coerce") if not np.isscalar(alan_m2) else alan_m2
    lev   = pd.to_numeric(levels,  errors="coerce") if not np.isscalar(levels)  else levels

    # NaN güvenliği
    if isinstance(alan, pd.Series):
        alan = alan.fillna(0)
    if isinstance(lev, pd.Series):
        lev = lev.fillna(DEFAULT_LEVELS).clip(lower=1)
    elif isinstance(lev, float) and lev != lev:
        # Scalar NaN check — `lev is None` was unreachable here because the
        # isinstance(int, float) branch already excludes None.
        lev = DEFAULT_LEVELS

    pop = alan * lev * pop_per_m2

    if isinstance(pop, pd.Series):
        return pop.clip(lower=min_population)
    if isinstance(pop, np.ndarray):
        return np.maximum(pop, min_population)
    return max(float(pop), min_population)


def estimate_capacity_afad(
    area_m2: float | pd.Series | np.ndarray,
    m2_per_person: float = AFAD_M2_PER_PERSON,
    min_capacity: int = 50,
) -> int | pd.Series | np.ndarray:
    """
    Toplanma alanı kapasitesini AFAD standardına göre hesaplar.
    Kişi başına 1.5 m² (acil toplanma — barınma değil).

    Küçük alanlar için min_capacity tabanı uygulanır (komşuluk parkları bile
    en az bir sokaklık nüfusu kabul edebilmeli).
    """
    area = pd.to_numeric(area_m2, errors="coerce") if not np.isscalar(area_m2) else area_m2

    if isinstance(area, pd.Series):
        area = area.fillna(0)
        cap = (area / m2_per_person).clip(lower=min_capacity).round().astype(int)
        return cap
    if isinstance(area, np.ndarray):
        cap = np.maximum(area / m2_per_person, min_capacity)
        return np.round(cap).astype(int)
    return max(int(round(float(area) / m2_per_person)), min_capacity)


# Common column-name aliases for auto-detection (case/space/_-tolerant).
# Used by detect_population_columns() — UI calls this to surface what was
# matched and let the user override.
_NAME_COL_ALIASES = (
    "mahalle_adi", "mahalle", "mahalleadi", "mh", "mah",
    "neighbourhood", "neighborhood", "neighbourhood_name",
    "nbhd", "name", "ad", "adi",
)
_POP_COL_ALIASES = (
    "nufus", "nüfus", "nufus_sayisi", "population", "pop",
    "total_population", "kisi", "kişi", "count",
)


def _norm_col_name(s: str) -> str:
    """Kolon adı eşleştirmesi için: lowercase + alfanumerik dışı strip."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def detect_population_columns(df: pd.DataFrame) -> tuple[str | None, str | None]:
    """
    Otomatik kolon tespit: TÜİK nüfus dosyasında 'mahalle adı' ve 'nüfus'
    kolonlarının hangileri olduğunu tahmin eder.

    Returns: (name_col, pop_col) — tespit edilemeyenler None döner.
    Çağıran UI bunu default olarak gösterir, kullanıcı manuel override ederse
    seçimi tutulur.
    """
    if df is None or df.empty:
        return None, None

    name_col: str | None = None
    pop_col: str | None = None

    # Pas 1 — birebir alias eşleşmesi (normalize edilmiş)
    cols_norm = {c: _norm_col_name(c) for c in df.columns}
    name_aliases_norm = {_norm_col_name(a) for a in _NAME_COL_ALIASES}
    pop_aliases_norm = {_norm_col_name(a) for a in _POP_COL_ALIASES}

    for col, norm in cols_norm.items():
        if name_col is None and norm in name_aliases_norm:
            name_col = col
        elif pop_col is None and norm in pop_aliases_norm:
            pop_col = col

    # Pas 2 — substring eşleşmesi (ör. "mahalle_adi_2023" → name_col)
    if name_col is None:
        for col, norm in cols_norm.items():
            if any(a in norm for a in ("mahalle", "mah", "neighbo", "nbhd")):
                name_col = col
                break
    if pop_col is None:
        for col, norm in cols_norm.items():
            if any(a in norm for a in ("nufus", "populat", "kisi", "kişi")):
                pop_col = col
                break

    # Pas 3 — heuristik: nüfus için ilk numeric kolon
    if pop_col is None:
        for col in df.columns:
            if col == name_col:
                continue
            try:
                num = pd.to_numeric(df[col], errors="coerce")
                if num.notna().mean() >= 0.7:
                    pop_col = col
                    break
            except Exception:
                continue

    return name_col, pop_col


# Türkçe karakter normalizasyonu — fuzzy fallback için.
# casefold() Türkçe ı/İ ikilisini tam tutarlı işlemediği için biz manuel.
_TR_LOWER = str.maketrans({
    "İ": "i", "I": "ı",   # Türkçe-aware lowercase
})
# Aksanları kaldır (zühtüpaşa → zuhtupasa) — fuzzy match için ek tolerans.
_TR_FOLD = str.maketrans({
    "ç": "c", "Ç": "c",
    "ğ": "g", "Ğ": "g",
    "ı": "i", "I": "i", "İ": "i", "i": "i",
    "ö": "o", "Ö": "o",
    "ş": "s", "Ş": "s",
    "ü": "u", "Ü": "u",
    "â": "a", "Â": "a",
    "î": "i", "Î": "i",
    "û": "u", "Û": "u",
})


def _normalize_mahalle_name(s: str) -> str:
    """
    Mahalle adı normalizasyonu — fuzzy match için.
    1. lowercase (Türkçe-aware)
    2. aksan/diakritik kaldır
    3. "Mahallesi"/"Mah." son ekini at
    4. fazla boşlukları temizle
    """
    if not s:
        return ""
    norm = str(s).strip().translate(_TR_LOWER).lower()
    norm = norm.translate(_TR_FOLD)
    # Universal "Mahallesi" suffix'i kaldır
    for suffix in (" mahallesi", " mahalle", " mh.", " mah.", " mh", " mah"):
        if norm.endswith(suffix):
            norm = norm[: -len(suffix)].strip()
            break
    return " ".join(norm.split())


def estimate_population_uniform_per_building(
    binalar_gdf,
    mahalle_pop: pd.DataFrame,
    mahalle_col: str = "mahalle",
    name_col: str = "mahalle_adi",
    pop_col: str = "nufus",
    fuzzy_threshold: float = 85.0,
) -> tuple[pd.Series, pd.DataFrame]:
    """
    Bina başına nüfus = mahalle nüfusu / mahalledeki bina sayısı.

    Footprint kolonu olmayan dış veri dosyaları için alternatif tahmin
    yöntemi. Yöntem klasik bir disaggregation yaklaşımıdır — Lwin &
    Murayama (2009)'un "uniform per-building distribution" varyantı:

        wᵢ = TÜİK_mahalle_nüfus(mahalle(i)) / bina_sayısı(mahalle(i))

    Karşılaştırma:
      • Footprint-based (`estimate_population`): footprint × kat ×
        0.025 — mekânsal heterojenliği yakalar (büyük apartman çok kişi,
        küçük ev az kişi). Bina başı tahminler farklıdır.
      • Uniform (bu fonksiyon): mahalle içi tüm binalar EŞİT ağırlığa
        sahip. Footprint/kat verisi gerekmez; tek girdi mahalle adı.

    Eşleştirme: `apply_neighbourhood_population_override` ile aynı
    3-katmanlı cascade (exact → normalized → fuzzy). Mahallesi TÜİK'te
    bulunamayan binalar `weight = NaN` döner — `nufus_kaynak` "estimated"
    yerine "missing_neighbourhood" ile işaretlenir (caller karar verir).

    Dönüş:
        (weights, audit_df)
        weights      : binalar_gdf.index ile aynı uzunlukta Series
        audit_df     : her mahalle için bir satır (mahalle, bina_sayısı,
                       tuik_nufus, bina_basi, eslesme, durum)
    """
    if mahalle_col not in binalar_gdf.columns:
        raise ValueError(
            f"binalar_gdf '{mahalle_col}' kolonunu içermeli; uniform "
            f"per-building tahmini uygulanamaz."
        )
    if name_col not in mahalle_pop.columns or pop_col not in mahalle_pop.columns:
        raise ValueError(
            f"mahalle_pop DataFrame {name_col!r} ve {pop_col!r} kolonlarını "
            f"içermeli; geldi: {list(mahalle_pop.columns)}"
        )

    # 3-katmanlı eşleştirme tabloları (override fonksiyonu ile birebir
    # aynı mantık — kod tekrar değil; iki fonksiyon farklı amaca hizmet
    # ediyor ve eşleştirme kuralı paylaşılan bir alt-katman).
    raw_names = mahalle_pop[name_col].astype(str).str.strip()
    raw_pops = pd.to_numeric(mahalle_pop[pop_col], errors="coerce").fillna(0)

    pop_lookup_exact = dict(zip(raw_names.str.casefold(), raw_pops))
    pop_lookup_norm = dict(zip(
        [_normalize_mahalle_name(n) for n in raw_names], raw_pops
    ))
    norm_to_raw = dict(zip(
        [_normalize_mahalle_name(n) for n in raw_names], raw_names
    ))

    try:
        from rapidfuzz import fuzz as _rf_fuzz
        from rapidfuzz import process as _rf_process
        _fuzzy_ok = True
    except ImportError:   # pragma: no cover
        _fuzzy_ok = False

    audit_rows = []
    weights = pd.Series(np.nan, index=binalar_gdf.index, dtype=float)
    fuzzy_keys = list(norm_to_raw.keys())

    for mah in binalar_gdf[mahalle_col].dropna().unique():
        mask = binalar_gdf[mahalle_col] == mah
        n_buildings = int(mask.sum())
        if n_buildings == 0:
            continue

        # Tier 1 — exact
        key_exact = str(mah).strip().casefold()
        tuik_pop = pop_lookup_exact.get(key_exact)
        match_method = "exact" if tuik_pop and tuik_pop > 0 else None

        # Tier 2 — normalized
        if match_method is None:
            key_norm = _normalize_mahalle_name(str(mah))
            tuik_pop = pop_lookup_norm.get(key_norm)
            if tuik_pop and tuik_pop > 0:
                match_method = "normalized"

        # Tier 3 — fuzzy
        fuzzy_match_name = None
        if match_method is None and _fuzzy_ok and fuzzy_keys:
            key_norm = _normalize_mahalle_name(str(mah))
            best = _rf_process.extractOne(
                key_norm, fuzzy_keys, scorer=_rf_fuzz.token_set_ratio,
            )
            if best is not None and best[1] >= fuzzy_threshold:
                fuzzy_match_name = norm_to_raw[best[0]]
                tuik_pop = pop_lookup_norm.get(best[0])
                if tuik_pop and tuik_pop > 0:
                    match_method = f"fuzzy:{int(best[1])}"

        if match_method is None or tuik_pop is None or tuik_pop <= 0:
            # Mahalle TÜİK'te yok → NaN bırak, caller karar versin
            audit_rows.append({
                "mahalle":      mah,
                "bina_sayisi":  n_buildings,
                "tuik_nufus":   None,
                "bina_basi":    None,
                "eslesme":      "—",
                "durum":        "TÜİK kayıtsız (nüfus atanamadı)",
            })
            continue

        # Normal: TÜİK nüfusunu eşit dağıt
        bina_basi = float(tuik_pop) / n_buildings
        weights.loc[mask] = bina_basi

        durum_txt = "Uniform dağıtım uygulandı"
        if match_method.startswith("fuzzy:") and fuzzy_match_name:
            durum_txt = f"Uniform dağıtım uygulandı (fuzzy: '{fuzzy_match_name}')"

        audit_rows.append({
            "mahalle":      mah,
            "bina_sayisi":  n_buildings,
            "tuik_nufus":   float(tuik_pop),
            "bina_basi":    round(bina_basi, 2),
            "eslesme":      match_method,
            "durum":        durum_txt,
        })

    audit_df = pd.DataFrame(audit_rows)
    return weights, audit_df


def apply_neighbourhood_population_override(
    binalar_gdf,
    mahalle_pop: pd.DataFrame,
    mahalle_col: str = "mahalle",
    weight_col: str = "weight",
    pop_col: str = "nufus",
    name_col: str = "mahalle_adi",
    fuzzy_threshold: float = 85.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Bina-bazlı nüfus tahminini mahalle TÜİK toplamına kalibre eder.

    Yaklaşım: Mevcut footprint × kat tahmini *dağıtım anahtarı* olarak
    kalır — yani mahalle içinde 1 büyük apartman vs. 50 küçük bina ayrımı
    korunur. Ama mahalle TOPLAMI TÜİK nüfusuna ölçeklenir:

        wᵢ_yeni = wᵢ_eski × (TÜİK_mahalle_nüfus / Σ_j wⱼ_eski)
                  ───────────────────────────────────────────
                  j ∈ aynı mahalle

    Bu yöntem:
      ✓ Toplam nüfusu TÜİK ile tutarlı yapar (savunulabilir).
      ✓ Mekânsal dağılımı korur (footprint büyüklüğü hala ağırlık taşır).
      ✗ Tek bir veri kaynağına bağlı kalmaz; varsayım listesinde "TÜİK
        kalibrasyonu uygulandı" notu vardır.

    Eşleştirme stratejisi (gerçek dünya verisinde tipografik fark olur:
    "Zühütpaşa" vs "Zühtüpaşa", "Caferağa" vs "CAFERAGA MAH." vb.):
      1. **Birebir** (casefold + strip)
      2. **Normalize edilmiş** (Türkçe karakter fold + "Mahallesi" suffix kaldırılmış)
      3. **Fuzzy** (rapidfuzz, default eşik 85) — son çare

    Audit DataFrame'i hangi yolla eşleşildiğini `eslesme` kolonunda gösterir
    ('exact', 'normalized', 'fuzzy:NN', '—') — kullanıcı transparency için.

    Parametreler:
        binalar_gdf      : weight + mahalle kolonları olan bina GDF'i
        mahalle_pop      : DataFrame; kolonlar `name_col` ve `pop_col`
        fuzzy_threshold  : 0-100 arası; bu değerin altındaki fuzzy skor
                           reddedilir, mahalle "kayıtsız" kalır

    Dönüş:
        (binalar_gdf_calibrated, audit_df)
    """
    if mahalle_col not in binalar_gdf.columns:
        raise ValueError(
            f"binalar_gdf '{mahalle_col}' kolonunu içermeli; mahalle "
            f"override uygulanamaz."
        )
    if name_col not in mahalle_pop.columns or pop_col not in mahalle_pop.columns:
        raise ValueError(
            f"mahalle_pop DataFrame {name_col!r} ve {pop_col!r} kolonlarını "
            f"içermeli; geldi: {list(mahalle_pop.columns)}"
        )

    binalar = binalar_gdf.copy()

    # Üç ayrı lookup: birebir, normalize, fuzzy hazırlık
    raw_names = mahalle_pop[name_col].astype(str).str.strip()
    raw_pops = pd.to_numeric(mahalle_pop[pop_col], errors="coerce").fillna(0)

    # 1) birebir (casefold + strip)
    pop_lookup_exact = dict(zip(raw_names.str.casefold(), raw_pops))
    # 2) normalize (Türkçe fold + suffix strip)
    pop_lookup_norm = dict(zip(
        [_normalize_mahalle_name(n) for n in raw_names], raw_pops
    ))
    # 3) fuzzy için raw isimlerin normalize listesi (orijinali eşleştirmek için
    #    ham → normalize çift haritası tutuyoruz)
    norm_to_raw = dict(zip(
        [_normalize_mahalle_name(n) for n in raw_names], raw_names
    ))

    # rapidfuzz lazy import — opsiyonel paket olduğunu garanti etmek için
    try:
        from rapidfuzz import fuzz as _rf_fuzz
        from rapidfuzz import process as _rf_process
        _fuzzy_ok = True
    except ImportError:   # pragma: no cover — runtime fallback
        _fuzzy_ok = False

    audit_rows = []
    new_weights = binalar[weight_col].astype(float).copy()
    nufus_kaynak = pd.Series(["estimated"] * len(binalar), index=binalar.index)

    fuzzy_keys = list(norm_to_raw.keys())   # normalized name list

    for mah in binalar[mahalle_col].dropna().unique():
        mask = binalar[mahalle_col] == mah
        n_buildings = int(mask.sum())
        toplam_eski = float(binalar.loc[mask, weight_col].sum())

        # Tier 1 — birebir
        key_exact = str(mah).strip().casefold()
        tuik_pop = pop_lookup_exact.get(key_exact)
        match_method = "exact" if tuik_pop and tuik_pop > 0 else None

        # Tier 2 — normalize edilmiş (Zühütpaşa Mh. → zuhutpasa)
        if match_method is None:
            key_norm = _normalize_mahalle_name(str(mah))
            tuik_pop = pop_lookup_norm.get(key_norm)
            if tuik_pop and tuik_pop > 0:
                match_method = "normalized"

        # Tier 3 — fuzzy fallback (rapidfuzz)
        fuzzy_score = None
        fuzzy_match_name = None
        if match_method is None and _fuzzy_ok and fuzzy_keys:
            key_norm = _normalize_mahalle_name(str(mah))
            best = _rf_process.extractOne(
                key_norm, fuzzy_keys, scorer=_rf_fuzz.token_set_ratio,
            )
            if best is not None and best[1] >= fuzzy_threshold:
                fuzzy_match_name = norm_to_raw[best[0]]
                fuzzy_score = best[1]
                tuik_pop = pop_lookup_norm.get(best[0])
                if tuik_pop and tuik_pop > 0:
                    match_method = f"fuzzy:{int(fuzzy_score)}"

        if match_method is None or tuik_pop is None or tuik_pop <= 0:
            audit_rows.append({
                "mahalle": mah,
                "bina_sayisi": n_buildings,
                "toplam_tahmin": round(toplam_eski, 1),
                "tuik_nufus": None,
                "olcek": None,
                "eslesme": "—",
                "durum": "TÜİK kayıtsız (tahmin korundu)",
            })
            continue

        if toplam_eski <= 0:
            audit_rows.append({
                "mahalle": mah,
                "bina_sayisi": n_buildings,
                "toplam_tahmin": 0.0,
                "tuik_nufus": float(tuik_pop),
                "olcek": None,
                "eslesme": match_method,
                "durum": "Tahmin sıfır → ölçeklenemez (TÜİK uygulanmadı)",
            })
            continue

        olcek = float(tuik_pop) / toplam_eski
        new_weights.loc[mask] = binalar.loc[mask, weight_col] * olcek
        nufus_kaynak.loc[mask] = "neighbourhood_calibrated"

        # Fuzzy eşleşmelerde hangi TÜİK adıyla eşleştiğini de ekle
        durum_txt = "Kalibre edildi"
        if match_method.startswith("fuzzy:") and fuzzy_match_name:
            durum_txt = f"Kalibre edildi (fuzzy: '{fuzzy_match_name}' eşleştirildi)"

        audit_rows.append({
            "mahalle": mah,
            "bina_sayisi": n_buildings,
            "toplam_tahmin": round(toplam_eski, 1),
            "tuik_nufus": float(tuik_pop),
            "olcek": round(olcek, 3),
            "eslesme": match_method,
            "durum": durum_txt,
        })

    binalar[weight_col] = new_weights
    binalar["nufus_kaynak"] = nufus_kaynak.values
    audit_df = pd.DataFrame(audit_rows)
    return binalar, audit_df


def assumptions_table() -> pd.DataFrame:
    """
    Raporlar için varsayım tablosu — Excel "Methodology" sayfasında kullanılır.
    Her satır bir varsayım, kaynağı ve değeri.
    """
    return pd.DataFrame([
        {"Parameter": "Household size (Istanbul)",
         "Value": HOUSEHOLD_SIZE_IST, "Unit": "persons/household",
         "Source": "TÜİK ADNKS 2023"},
        {"Parameter": "Average dwelling area (gross)",
         "Value": AVG_DWELLING_M2_GROSS, "Unit": "m²",
         "Source": "TÜİK Housing Sales Statistics 2023"},
        {"Parameter": "Net usage ratio",
         "Value": NET_USAGE_RATIO, "Unit": "dimensionless",
         "Source": "Construction industry convention"},
        {"Parameter": "Population per gross m² (per floor)",
         "Value": POP_PER_M2_CONSERVATIVE, "Unit": "persons/m²",
         "Source": "Derived"},
        {"Parameter": "Default building levels (fallback)",
         "Value": DEFAULT_LEVELS, "Unit": "floors",
         "Source": "Istanbul building stock median"},
        {"Parameter": "Assembly area capacity standard",
         "Value": AFAD_M2_PER_PERSON, "Unit": "m²/person",
         "Source": "AFAD — Emergency gathering area minimum"},
    ])
