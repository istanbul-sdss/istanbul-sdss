"""
src/optimizer/p_median.py

P-Median optimizasyonu — kapasite kısıtlı ve kısıtsız versiyonlar.

Formülasyon (klasik p-median ILP):
  minimize  Σᵢ Σⱼ wᵢ · dᵢⱼ · xᵢⱼ            (amac="min_sum")
      veya  z                                (amac="min_max" — fairness)
      veya  nüfus-ağırlıklı p95              (amac="min_p95", yalnızca K-Medoids)
  s.t.
    Σⱼ xᵢⱼ = 1                        ∀i ∈ ulaşılabilir  (her bina tam 1 alana)
    xᵢⱼ ≤ yⱼ                          ∀i,j ∈ R
    Σⱼ yⱼ = p                                 (tam p alan açılır)
    dᵢⱼ · xᵢⱼ ≤ z                     ∀i,j   (min-max modunda)
    Σᵢ wᵢ xᵢⱼ ≤ Cⱼ yⱼ                 ∀j     (kapasite kısıtı — opsiyonel)
    xᵢⱼ, yⱼ ∈ {0,1}

Not — Ulaşılabilirlik (R):
  max_sure_dk verildiyse yalnızca dᵢⱼ ≤ max_sure_dk olan (i,j) çifti için
  xᵢⱼ değişkeni yaratılır. Böylece ulaşılamaz atamalar **tamamen** yasaklanır
  (eski penalty yaklaşımının çözücüde bozulmaya yol açan yan etkisi kaldırıldı).
  Ulaşılamayan binalar ayrı bir listede raporlanır ve atamadan çıkarılır.

Ölçek stratejisi:
  ≤ 5.000 bina  : PuLP ILP (kesin çözüm)
  > 5.000 bina  : K-medoids (hızlı sezgisel, kapasite-farkında)

Çıktı: PMedianResult dataclass
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import geopandas as gpd
import numpy as np
import pandas as pd

from src.config.settings import (
    ILP_THRESHOLD as _SETTINGS_ILP_THRESHOLD,
)
from src.config.settings import (
    ILP_TIME_LIMIT_SN as _SETTINGS_ILP_TIME_LIMIT_SN,
)
from src.config.settings import (
    KMEDOIDS_MAX_ITER as _SETTINGS_KMEDOIDS_MAX_ITER,
)
from src.config.settings import (
    P95_PERCENTILE as _SETTINGS_P95_PERCENTILE,
)
from src.logger import get_logger

log = get_logger(__name__)

# Sabitler src/config/settings.py'a taşındı; alias olarak yeniden ihraç ediliyor.
ILP_THRESHOLD = _SETTINGS_ILP_THRESHOLD
ILP_TIME_LIMIT_SN = _SETTINGS_ILP_TIME_LIMIT_SN
KMEDOIDS_MAX_ITER = _SETTINGS_KMEDOIDS_MAX_ITER

# Hedef fonksiyon modları:
#   • min_sum : Σᵢ wᵢ·dᵢⱼ        — toplam ağırlıklı süre (efficiency)
#   • min_max : max_i dᵢⱼ        — en kötü atama süresi (klasik fairness;
#                                  TEK küçük bina çözümü domine edebilir,
#                                  outlier-hassas)
#   • min_p95 : nüfus-ağırlıklı 95. yüzdelik yürüme süresi.
#                                  Outlier-robust fairness; pratikte AFAD
#                                  karar destek için önerilen mod. Yalnızca
#                                  K-Medoids ile çözülür (ILP'de doğrusal
#                                  olmadığı için).
ObjectiveMode = Literal["min_sum", "min_max", "min_p95"]
P95_PERCENTILE = _SETTINGS_P95_PERCENTILE

# Solver seçim modu:
#   "auto"     → ILP_THRESHOLD'a göre otomatik (geriye uyumlu varsayılan)
#   "ilp"      → Kullanıcı zorla ILP istiyor (büyük problem yavaş olabilir)
#   "kmedoids" → Kullanıcı zorla K-Medoids istiyor (hız, kıyaslama, vb.)
SolverMode = Literal["auto", "ilp", "kmedoids"]


def _weighted_percentile(
    values: np.ndarray,
    weights: np.ndarray,
    percentile: float = 95.0,
) -> float:
    """
    Ağırlıklı yüzdelik (nüfus-ağırlıklı p-th percentile).

    Her bina'nın `weight` kişiyi temsil ettiği varsayımıyla, kümülatif
    nüfusa karşı süre fonksiyonunda istenen yüzdelik değeri döner.
    Bu, "her bireyi tek tek listeleyip percentile alma"nın O(n log n)
    eşdeğeri ama replikasyon yapmaz — büyük ağırlıklarda da hızlı.

    Eşit ağırlıklarda klasik np.percentile ile aynı değeri verir
    (interpolasyon politikası: linear/upper arasında "lower" — afet
    karar destek için temkinli sınır).

    NaN ve inf değerler:
      • inf değerler dahil edilir (yüksek p95'i şişirir, doğru davranış)
      • NaN'ler dışlanır
    """
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    mask = ~np.isnan(values)
    v = values[mask]
    w = weights[mask]
    if v.size == 0 or w.sum() <= 0:
        return float("nan")
    order = np.argsort(v)
    v_sorted = v[order]
    w_sorted = w[order]
    cum = np.cumsum(w_sorted)
    threshold = (percentile / 100.0) * cum[-1]
    idx = int(np.searchsorted(cum, threshold, side="left"))
    idx = min(idx, len(v_sorted) - 1)
    return float(v_sorted[idx])


def _sure_sinifi(sure: float) -> tuple[str, str]:
    """
    Map walking time to a user-friendly access class + time band.
    Returns (quality_label, time_band) pair — both English; downstream
    UI/Excel surfaces both as-is.
    """
    if sure <= 5:
        return "Excellent", "0-5 min"
    if sure <= 10:
        return "Good", "5-10 min"
    if sure <= 15:
        return "Acceptable", "10-15 min"
    if sure <= 30:
        return "Far", "15-30 min"
    return "Very far", "30+ min"


# ── Sonuç veri yapısı ─────────────────────────────────────────────────────────

@dataclass
class PMedianResult:
    """P-Median çözüm sonuçları."""
    # Temel atama
    atamalar: pd.DataFrame          # bina_idx → alan_idx, alan_adi, sure_dk, mahalle
    acik_alanlar: list[int]         # seçilen toplanma alanı indeksleri
    acik_alan_adlari: list[str]

    # Metrikler — bina bazlı
    toplam_agirlikli_sure: float    # minimize edilen hedef fonksiyon
    ort_sure_dk: float              # atanmış binalar üzerinden ortalama
    agirlikli_ort_sure_dk: float    # Σwᵢdᵢ / Σwᵢ (nüfus-ağırlıklı)
    max_sure_dk: float
    # P95 düzeltmesi: `p95_sure_dk` artık **nüfus-ağırlıklı**. Optimizer
    # `min_p95` hedefinin hedef fonksiyonuyla AYNI ağırlık mantığını
    # kullanır → karar destek raporu hedef fonksiyonla tutarlı. Bilgilendirme
    # amaçlı bina-bazlı ağırlıksız değer ayrı bir alanda (`p95_bina_sure_dk`,
    # aşağıda default değerli alanlar bölümünde) taşınır.
    p95_sure_dk: float              # 95. yüzdelik süre (nüfus-ağırlıklı)

    # Kapsama — bina sayısı bazlı (%)
    kapsama_5dk_pct: float
    kapsama_10dk_pct: float
    kapsama_30dk_pct: float

    # Kapsama — nüfus bazlı (%)
    nufus_kapsama_5dk_pct: float
    nufus_kapsama_10dk_pct: float
    nufus_kapsama_30dk_pct: float

    # Ulaşılamayan binalar (max_sure_dk kısıtı nedeniyle dışarıda kalanlar)
    ulasilamaz_sayisi: int = 0
    ulasilamaz_nufus: float = 0.0
    ulasilamaz_binalar: pd.DataFrame = field(default_factory=pd.DataFrame)

    # P95 ikinci metriği (bina-bazlı, ağırlıksız) — informasyonel; birincil
    # `p95_sure_dk` zaten nüfus-ağırlıklı.
    p95_bina_sure_dk: float = 0.0

    # Meta
    yontem: str = ""                # "ILP" veya "K-Medoids"
    amac: str = "min_sum"           # "min_sum" veya "min_max"
    cozum_suresi_sn: float = 0.0
    p: int = 0
    max_sure_dk_kisit: float | None = None
    kapasite_aktif: bool = False

    # Teşhis (UI'da uyarı kutucuğu olarak gösterilir, raporda da yer alır)
    fizibilite_uyarisi: str | None = None   # ön-tarama: kapasite < talep vb.
    fallback_nedeni: str | None = None      # ILP→K-Medoids düşüşünün net sebebi
    ilp_status: str | None = None           # PuLP status string ("Optimal", "Infeasible"...)

    # K-Medoids convergence şeffaflığı.
    #
    # K-Medoids 1-swap local search heuristic'i lokal optimuma yakınsamayı
    # MATEMATİKSEL OLARAK GARANTİ ETMEZ — pratikte yakınsar ama edge case'lerde
    # MAX_ITER limitine takılabilir. Üç durumlu ayrım:
    #
    #   • kmedoids_converged = True
    #         → Local search "no improving swap found" ile durdu;
    #           çözüm certified locally optimal (1-swap mahallesinde).
    #   • kmedoids_converged = False
    #         → MAX_ITER'e takıldı; çözüm best-found heuristic — locally
    #           optimal olduğu garanti edilemez. UI/Excel açıkça uyarır.
    #   • kmedoids_converged = None
    #         → ILP path kullanıldı; PuLP/CBC `prob.status` ayrıca raporlanır
    #           (`ilp_status`). Convergence kavramı K-Medoids'e özgü.
    #
    # `kmedoids_iterations` swap döngüsünün gerçek tur sayısını taşır;
    # MAX_ITER'le karşılaştırılarak takılma teşhis edilebilir.
    kmedoids_converged: bool | None = None
    kmedoids_iterations: int | None = None

    # Alan bazlı özet
    alan_ozeti: pd.DataFrame = field(default_factory=pd.DataFrame)


# ── Çözücüler ─────────────────────────────────────────────────────────────────

def coz(
    od: np.ndarray,
    binalar_gdf: gpd.GeoDataFrame,
    toplanma_gdf: gpd.GeoDataFrame,
    p: int,
    kapasite: bool = False,
    max_sure_dk: float | None = None,
    amac: ObjectiveMode = "min_sum",
    progress_cb: Callable | None = None,
    solver: SolverMode = "auto",
    time_limit_sn: int | None = None,
    allow_fallback: bool = True,
) -> PMedianResult:
    """
    OD matrisi ve p değerine göre p-median çözer.

    Parametreler:
        od           : [N_bina × N_toplanma] süre matrisi (dakika)
        binalar_gdf  : weight, mahalle, bina_etiketi sütunları olan GDF
        toplanma_gdf : ad, kapasite sütunları olan GDF
        p            : açılacak toplanma alanı sayısı
        kapasite     : kapasite kısıtı uygulansın mı
        max_sure_dk  : bu süreyi aşan atamalar TAMAMEN yasaklanır (hard kısıt).
                       Ulaşılamayan binalar ulasilamaz_binalar'da raporlanır.
        amac         : "min_sum" | "min_max" | "min_p95"
                       min_p95 sadece K-Medoids'te uygulanır.
        progress_cb  : ilerleme callback
        solver       : "auto" (varsayılan; ILP_THRESHOLD'a göre) |
                       "ilp" (zorla ILP, büyük problem yavaş) |
                       "kmedoids" (zorla K-Medoids).
                       Solver-amac çakışmaları: solver="ilp" + amac="min_p95"
                       isteği reddedilir (ValueError) — ILP'de p95 doğrusal değil.
        time_limit_sn: ILP zaman limiti (saniye).
                       • None  → settings.ILP_TIME_LIMIT_SN (varsayılan limit)
                       • 0     → SINIRSIZ (CBC, kanıtlı optimum/infeasible'a kadar
                                 çalışır; akademik karşılaştırma / "ne kadar
                                 sürerse sürsün" senaryosu için)
                       • int>0 → o kadar saniye
                       Sadece ILP modu için anlamlı.
        allow_fallback: True (varsayılan) → ILP başarısızsa K-Medoids'e düş.
                       False → ILP başarısızsa RuntimeError fırlat (akademik
                       karşılaştırma, A/B testi için).
    """
    def cb(msg: str):
        log.info(msg)
        if progress_cb: progress_cb(msg)

    n_bina, n_alan = od.shape
    if n_bina == 0:
        raise ValueError("No buildings — optimization cannot run.")
    if n_alan == 0:
        raise ValueError("No assembly areas — optimization cannot run.")
    if p <= 0:
        raise ValueError(f"p={p} is invalid; must be at least 1.")
    if solver not in ("auto", "ilp", "kmedoids"):
        raise ValueError(f"solver={solver!r} is invalid; must be 'auto'|'ilp'|'kmedoids'.")
    if solver == "ilp" and amac == "min_p95":
        raise ValueError(
            "solver='ilp' + amac='min_p95' is not supported — "
            "p95 is not linear in ILP. Use solver='kmedoids' or 'auto', "
            "or change amac to 'min_max'/'min_sum'."
        )
    p = min(p, n_alan)   # p cannot exceed the number of areas

    fizibilite_uyarisi = _check_capacity_feasibility(
        od, binalar_gdf, toplanma_gdf, p, kapasite, max_sure_dk, cb
    )

    # Solver selection logic
    if solver == "ilp":
        use_kmedoids = False
        if n_bina > ILP_THRESHOLD:
            cb(f"⚠ User forced ILP ({n_bina:,} buildings > {ILP_THRESHOLD} "
               f"threshold). Solve may be slow or hit the time limit.")
    elif solver == "kmedoids":
        use_kmedoids = True
    else:  # auto
        # min_p95 only solvable by K-Medoids (p95 is not linear in ILP).
        use_kmedoids = (n_bina > ILP_THRESHOLD) or (amac == "min_p95")

    cb(f"P-Median starting: p={p}, {n_bina:,} buildings, {n_alan} areas, "
       f"solver={solver}, method={'K-Medoids' if use_kmedoids else 'ILP'}, "
       f"objective={amac}, capacity={kapasite}, max_sure={max_sure_dk}, "
       f"allow_fallback={allow_fallback}")

    if not use_kmedoids:
        # time_limit_sn sentinel haritası:
        #   None → default (settings.ILP_TIME_LIMIT_SN)
        #   0    → UNLIMITED (CBC'ye timeLimit=None gönder; kanıtlı bitişe kadar)
        #   int>0 → kullanıcı tarafından verilmiş süre
        # `or` operatörü 0'ı falsy sayıp default'a düşürürdü → değiştirildi.
        if time_limit_sn is None:
            _effective_tl: int | None = ILP_TIME_LIMIT_SN
        elif time_limit_sn <= 0:
            _effective_tl = None   # sınırsız
        else:
            _effective_tl = int(time_limit_sn)

        result = _coz_ilp(
            od, binalar_gdf, toplanma_gdf, p, kapasite, max_sure_dk, amac, cb,
            time_limit_sn=_effective_tl,
            allow_fallback=allow_fallback,
        )
    else:
        # P2.1: amac parametresi de aktarılır. Önceden _coz_kmedoids `amac`
        # almıyordu, kullanıcı `min_max` seçse bile sonuç sessizce `min_sum`
        # döndürüyordu (audit P2.1).
        result = _coz_kmedoids(
            od, binalar_gdf, toplanma_gdf, p, kapasite, max_sure_dk, amac, cb
        )

    result.fizibilite_uyarisi = fizibilite_uyarisi
    return result


def _check_capacity_feasibility(
    od: np.ndarray,
    binalar_gdf: gpd.GeoDataFrame,
    toplanma_gdf: gpd.GeoDataFrame,
    p: int,
    kapasite: bool,
    max_sure_dk: float | None,
    cb: Callable,
) -> str | None:
    """
    Çözümden önce kapasite-fizibilite ön-taraması.

    İki ayrı kontrol:
      A) GLOBAL: Toplam talep (Σwᵢ), seçilebilecek p alanın MAKSİMUM toplam
         kapasitesinden büyük mü? Eğer öyleyse hiçbir p-li seçim talebi
         karşılayamaz — kullanıcı baştan uyarılır.
      B) ULAŞILABİLİRLİK: max_sure_dk altında hiçbir alana ulaşamayan binalar
         var mı? (p_median bunları sonradan da raporlar; burada erken uyarı.)

    Dönüş: uyarı metni (None = sorun yok). UI bu metni `st.warning()` olarak
    gösterebilir.

    H2 düzeltmesi: Reachability ön-uyarısı eskiden sadece kapasite AÇIK iken
    çalışıyordu — kapasite kapalıyken `max_sure_dk` verilirse kullanıcı "neden
    bu kadar ulaşılamaz var?" cevabını ancak çözüm sonunda görüyordu. Artık
    iki kontrol birbirinden bağımsız: kapasite (A) erken çıkış değil; A yoksa
    B yine de çalışır.
    """
    agirliklar = binalar_gdf["weight"].values.astype(float)

    # A) Kapasite ön-taraması — yalnızca kapasite AÇIK ve kapasite kolonu varsa
    if kapasite and "kapasite" in toplanma_gdf.columns:
        kapasiteler = toplanma_gdf["kapasite"].values.astype(float)
        toplam_talep = float(agirliklar.sum())

        # En yüksek p kapasitesi (p alan açma izni varsa en kapasitelileri seçeriz)
        en_yuksek_p_kap = (
            float(np.sort(kapasiteler)[-p:].sum())
            if p <= len(kapasiteler)
            else float(kapasiteler.sum())
        )

        if toplam_talep > en_yuksek_p_kap:
            oran = en_yuksek_p_kap / toplam_talep if toplam_talep > 0 else 0.0
            msg = (
                f"⚠ Insufficient capacity: total demand ≈ {toplam_talep:,.0f} people, "
                f"but the {p} highest-capacity area(s) can hold only "
                f"≈ {en_yuksek_p_kap:,.0f} people ({oran*100:.0f}% of demand). "
                f"Suggestions: increase p, disable the capacity constraint, "
                f"or add new candidate areas."
            )
            cb(msg)
            return msg

    # B) Reachability — kapasite ON/OFF olmasından bağımsız çalışır
    if max_sure_dk is not None:
        od_clean = np.where(np.isfinite(od), od, np.inf)
        ulasilabilir_mask = (od_clean <= max_sure_dk).any(axis=1)
        n_ulasilamaz = int((~ulasilabilir_mask).sum())
        if n_ulasilamaz > 0:
            ulasilamaz_nufus = float(agirliklar[~ulasilabilir_mask].sum())
            pct = n_ulasilamaz / len(agirliklar) * 100
            msg = (
                f"⚠ {n_ulasilamaz:,} buildings ({pct:.1f}%, "
                f"≈{ulasilamaz_nufus:,.0f} people) cannot reach any area within "
                f"max_sure_dk={max_sure_dk} minutes and will be excluded. "
                f"Fix: increase max_sure_dk or add more assembly areas."
            )
            cb(msg)
            return msg

    return None


# ── ILP çözücü (PuLP) ─────────────────────────────────────────────────────────

def _coz_ilp(
    od: np.ndarray,
    binalar_gdf: gpd.GeoDataFrame,
    toplanma_gdf: gpd.GeoDataFrame,
    p: int,
    kapasite: bool,
    max_sure_dk: float | None,
    amac: ObjectiveMode,
    cb: Callable,
    time_limit_sn: int | None = ILP_TIME_LIMIT_SN,
    allow_fallback: bool = True,
) -> PMedianResult:
    """
    time_limit_sn=None → CBC'ye `timeLimit` parametresi None olarak iletilir
    (PuLP convention'ı: limitsiz). Status mesajlarında "unlimited" olarak yazılır.
    """
    try:
        import pulp
    except ImportError as e:
        raise RuntimeError(
            "PuLP kurulu değil. Terminalde çalıştırın: pip install pulp"
        ) from e

    t0 = time.time()
    n_bina, n_alan = od.shape
    agirliklar = binalar_gdf["weight"].values.astype(float)

    # ── Ulaşılabilirlik maskesi ──────────────────────────────────────────────
    # max_sure_dk verildiyse, yalnızca o süre içindeki (i,j) çiftleri modele girer.
    # Ayrıca OD'de inf/NaN varsa (kopuk graf) onlar da ulaşılamaz sayılır.
    od_clean = np.where(np.isfinite(od), od, np.inf)

    if max_sure_dk is not None:
        reachable = od_clean <= max_sure_dk
    else:
        reachable = np.isfinite(od_clean)

    bina_erisilebilir = reachable.any(axis=1)   # en az 1 alana ulaşan binalar
    ulasilamaz_idx = np.where(~bina_erisilebilir)[0].tolist()
    erisilebilir_binalar = np.where(bina_erisilebilir)[0].tolist()

    if ulasilamaz_idx:
        cb(f"[!] {len(ulasilamaz_idx)} buildings cannot reach any area within "
           f"max_sure_dk={max_sure_dk} -> reported separately")

    if not erisilebilir_binalar:
        raise RuntimeError(
            "No building is reachable. Increase max_sure_dk or verify the "
            "OSM walking graph is connected."
        )

    cb("Building ILP model...")

    prob = pulp.LpProblem("p_median", pulp.LpMinimize)

    # Değişkenler — yalnızca ulaşılabilir (i,j) çiftleri için x oluştur
    x: dict[tuple[int, int], pulp.LpVariable] = {}
    for i in erisilebilir_binalar:
        for j in range(n_alan):
            if reachable[i, j]:
                x[(i, j)] = pulp.LpVariable(f"x_{i}_{j}", cat="Binary")

    y = pulp.LpVariable.dicts("y", range(n_alan), cat="Binary")

    # ── Hedef fonksiyon ──────────────────────────────────────────────────────
    if amac == "min_max":
        z = pulp.LpVariable("z", lowBound=0, cat="Continuous")
        prob += z
        # z ≥ dᵢⱼ · xᵢⱼ — en kötü tek atamayı minimize et
        for (i, j), var in x.items():
            prob += od_clean[i, j] * var <= z
    else:  # min_sum (default)
        prob += pulp.lpSum(
            agirliklar[i] * od_clean[i, j] * var
            for (i, j), var in x.items()
        )

    # Kısıt 1: her erişilebilir bina tam 1 alana atanır
    for i in erisilebilir_binalar:
        aday_j = [j for j in range(n_alan) if (i, j) in x]
        prob += pulp.lpSum(x[(i, j)] for j in aday_j) == 1

    # Kısıt 2: atama ancak açık alana
    for (_i, j), var in x.items():
        prob += var <= y[j]

    # Kısıt 3: tam p alan
    prob += pulp.lpSum(y[j] for j in range(n_alan)) == p

    # Kısıt 4 (opsiyonel): kapasite
    # Σᵢ wᵢ xᵢⱼ ≤ Cⱼ · yⱼ — toplam nüfus alanın kapasitesini geçemez
    kapasite_aktif = False
    if kapasite and "kapasite" in toplanma_gdf.columns:
        kapasiteler = toplanma_gdf["kapasite"].values.astype(float)
        for j in range(n_alan):
            j_binalar = [i for i in erisilebilir_binalar if (i, j) in x]
            if not j_binalar:
                continue
            prob += (
                pulp.lpSum(agirliklar[i] * x[(i, j)] for i in j_binalar)
                <= kapasiteler[j] * y[j]
            )
        kapasite_aktif = True
        cb(f"Capacity constraint added (total capacity: {kapasiteler.sum():,.0f} people)")

    _tl_str = "unlimited" if time_limit_sn is None else f"{time_limit_sn}s"
    cb(f"Solving ILP (CBC solver, {len(x):,} x variables, "
       f"timeLimit={_tl_str})...")
    prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=time_limit_sn))

    status = pulp.LpStatus[prob.status]
    cb(f"ILP status: {status} | time: {time.time()-t0:.1f}s")

    # CBC sometimes stops on time limit having found a feasible integer
    # solution but without proving optimality. In that case prob.status is
    # NotSolved (0) but PuLP's sol_status is LpSolutionIntegerFeasible (2).
    # Previously we threw that solution away and fell back to K-Medoids;
    # CBC's best-found integer solution is almost always at least as good
    # as a fresh K-Medoids run on the same problem, so we now keep it.
    # Defensive `getattr` — older PuLP without sol_status falls through to
    # the existing fallback path (same behaviour as before).
    sol_status = getattr(prob, "sol_status", None)
    ilp_feasible_only = prob.status == 0 and sol_status == 2

    if prob.status != 1 and not ilp_feasible_only:
        # PuLP status kodları: 1=Optimal, 0=NotSolved, -1=Infeasible,
        # -2=Unbounded, -3=Undefined. Time-limit aşımında bazen 0 dönebiliyor.
        # Kullanıcının "neden K-Medoids'e düştüm?" sorusuna net cevap üretelim.
        if prob.status == -1:
            sebep = (
                "ILP infeasible — model has no feasible solution. Most likely "
                "cause: capacity constraints + max_sure_dk together are too "
                "tight; some buildings cannot find a reachable area with "
                "available capacity."
            )
        elif prob.status == 0:
            _tl_msg = (
                "the unlimited time budget" if time_limit_sn is None
                else f"the {time_limit_sn}s time limit"
            )
            sebep = (
                f"ILP did not find any feasible solution within {_tl_msg} "
                f"(problem too large or hard). "
                f"K-Medoids will produce a fast approximate solution."
            )
        else:
            sebep = f"ILP unexpected status: {status} (code={prob.status})."

        if not allow_fallback:
            # Academic comparison mode: user opted out of fallback → raise
            # explicitly so the ILP failure is visible upstream.
            raise RuntimeError(
                f"ILP failed and allow_fallback=False. {sebep}"
            )

        cb(f"ILP failed → falling back to K-Medoids. Reason: {sebep}")
        # P2.1: amac fallback'te de korunur (önceden parametre yoktu).
        result = _coz_kmedoids(
            od, binalar_gdf, toplanma_gdf, p, kapasite, max_sure_dk, amac, cb
        )
        result.fallback_nedeni = sebep
        result.ilp_status = status
        return result

    if ilp_feasible_only:
        # Best-found integer solution will be extracted below; mark the
        # status so downstream UI/report can tell it's a feasible-but-not-
        # proven-optimal CBC result (not a K-Medoids fallback).
        # NOTE: with time_limit_sn=None (unlimited) CBC cannot return
        # IntegerFeasible without proving optimality, so this branch
        # effectively only fires under a finite limit. Defensive format.
        _tl_msg = "unlimited" if time_limit_sn is None else f"{time_limit_sn}s"
        cb(
            f"ILP stopped at time limit ({_tl_msg}) with a feasible "
            f"integer solution (sol_status=IntegerFeasible). Keeping CBC's "
            f"best-found solution instead of restarting with K-Medoids."
        )
        status = "Feasible (time limit)"

    # ── Sonuçları çıkar ───────────────────────────────────────────────────────
    acik = [j for j in range(n_alan) if pulp.value(y[j]) > 0.5]

    atama = np.full(n_bina, -1, dtype=int)   # -1 = ulaşılamaz
    for (i, j), var in x.items():
        if pulp.value(var) > 0.5:
            atama[i] = j

    result = _build_result(
        atama, acik, od_clean, binalar_gdf, toplanma_gdf, p,
        yontem="ILP",
        amac=amac,
        sure=time.time() - t0,
        max_sure_dk_kisit=max_sure_dk,
        kapasite_aktif=kapasite_aktif,
    )
    result.ilp_status = status
    return result


# ── K-Medoids sezgiseli (büyük ölçek) ────────────────────────────────────────

def _coz_kmedoids(
    od: np.ndarray,
    binalar_gdf: gpd.GeoDataFrame,
    toplanma_gdf: gpd.GeoDataFrame,
    p: int,
    kapasite: bool,
    max_sure_dk: float | None,
    amac: ObjectiveMode,
    cb: Callable,
) -> PMedianResult:
    """
    Greedy başlangıç + local search ile k-medoids.
    ILP'ye yakın sonuç, çok daha hızlı.

    Kapasite-farkında: `kapasite=True` ise atamalar greedy olarak doldurulur,
    dolmuş alanlar atlanır. Lokal aramada sadece aday set değerlendirilir.

    Hedef (`amac`):
      • "min_sum" → toplam ağırlıklı yürüyüş süresi (efficiency).
      • "min_max" → en kötü atama süresini minimize (fairness). Lokal arama
        cost fonksiyonu max yürüyüş süresini ölçer; greedy init de min_max'a
        göre ayarlanmıştır. Önceden K-Medoids `amac` parametresi taşımıyordu,
        UI'daki fairness seçimi büyük ölçekte sessizce min_sum'a düşüyordu
        (audit P2.1).
      • "min_p95" → nüfus-ağırlıklı 95. yüzdelik süreyi minimize. Her bina'nın
        süresi `weight` kez listeye eklenir (kişi-ağırlıklı), sonra p95 alınır.
        Outlier-robust: tek küçük bina çözümü domine etmez. AFAD karar destek
        bağlamında min_max'tan daha sağlamdır.
    """
    t0 = time.time()
    n_bina, n_alan = od.shape
    agirliklar = binalar_gdf["weight"].values.astype(float)

    # Ulaşılabilirlik — ILP ile aynı mantık
    od_clean = np.where(np.isfinite(od), od, np.inf)
    if max_sure_dk is not None:
        # Ulaşılamaz çiftleri +inf yaparak atamayı yasakla
        od_eff = np.where(od_clean <= max_sure_dk, od_clean, np.inf)
    else:
        od_eff = od_clean

    kapasiteler = None
    if kapasite and "kapasite" in toplanma_gdf.columns:
        kapasiteler = toplanma_gdf["kapasite"].values.astype(float)
        cb(f"K-Medoids in capacity-aware mode (total: {kapasiteler.sum():,.0f})")

    cb("K-Medoids starting (greedy init + local search)...")

    # ── Ceza stratejisi ──────────────────────────────────────────────────────
    # Ulaşılamaz (inf) hücreler için maliyet hesabında sabit, anlamlı bir ceza
    # kullanıyoruz. Çok büyük bir sayı (1e9) kullanmak local search'ü dejenere
    # edip seçim mantığını bozar — bunun yerine "ulaşılamaz ≈ 2×cap" varsayımı.
    ceza_dk = float(max_sure_dk) * 2 if max_sure_dk else 120.0
    od_ceza = np.where(np.isfinite(od_eff), od_eff, ceza_dk)

    # ── Greedy başlangıç ──────────────────────────────────────────────────────
    # Her hedef için en uygun ilk medoid:
    #   min_sum  : toplam ağırlıklı süreyi minimize eden alan
    #   min_max  : en kötü süreyi minimize eden alan
    #   min_p95  : kişi-ağırlıklı p95'i minimize eden alan
    if amac == "min_max":
        ilk_kotu = od_ceza.max(axis=0)
        secili = [int(np.argmin(ilk_kotu))]
    elif amac == "min_p95":
        # Her aday alan tek başına seçilse, p95 ne olur?
        ilk_p95 = np.array([
            _weighted_percentile(od_ceza[:, j], agirliklar, P95_PERCENTILE)
            for j in range(n_alan)
        ])
        secili = [int(np.argmin(ilk_p95))]
    else:
        maliyet = (od_ceza * agirliklar[:, None]).sum(axis=0)
        secili = [int(np.argmin(maliyet))]

    for _ in range(p - 1):
        min_sure = od_ceza[:, secili].min(axis=1)
        kalan = [j for j in range(n_alan) if j not in secili]
        if not kalan:
            break
        if amac == "min_max":
            kazanclar = np.array([
                np.minimum(min_sure, od_ceza[:, j]).max()
                for j in kalan
            ])
        elif amac == "min_p95":
            kazanclar = np.array([
                _weighted_percentile(
                    np.minimum(min_sure, od_ceza[:, j]),
                    agirliklar,
                    P95_PERCENTILE,
                )
                for j in kalan
            ])
        else:
            kazanclar = np.array([
                (np.minimum(min_sure, od_ceza[:, j]) * agirliklar).sum()
                for j in kalan
            ])
        secili.append(kalan[int(np.argmin(kazanclar))])

    cb(f"Greedy init complete: {secili}")

    # ── Local search (swap) ───────────────────────────────────────────────────
    # Cost fonksiyonu `amac`'a göre değişir. min_max için en kötü atama
    # süresini optimize eder; min_sum için toplam ağırlıklı süreyi.
    def toplam_maliyet(secim: list[int]) -> float:
        if kapasiteler is not None:
            _, sureler, _ = _assign_with_capacity(
                od_eff, agirliklar, secim, kapasiteler
            )
            # Ulaşılamayanlar (kapasite yetersiz VEYA ağ kopuk) için ceza uygula
            sureler = np.where(np.isfinite(sureler), sureler, ceza_dk)
        else:
            sureler = od_ceza[:, secim].min(axis=1)

        if amac == "min_max":
            # En kötü atama süresi (worst-case fairness)
            return float(sureler.max())
        if amac == "min_p95":
            # Nüfus-ağırlıklı p95 — outlier'lara dirençli fairness
            return _weighted_percentile(sureler, agirliklar, P95_PERCENTILE)
        return float((sureler * agirliklar).sum())

    mevcut_maliyet = toplam_maliyet(secili)
    gelisim = True
    iterasyon = 0
    # MAX_ITER lokal sigorta. KMEDOIDS_MAX_ITER (settings.py'da 200) çoğu
    # gerçek senaryoda yeterli — pratikte 5-30 iterasyonda yakınsanır.
    # Sigortanın asıl amacı patolojik salınım/plateau senaryolarında
    # sonsuz döngüyü önlemek.
    # Future work (R5): MAX_ITER'e ulaşıldığında multi-start restart
    # (farklı greedy init ile 2-3 deneme, en iyiyi al). Şimdilik yakınsama
    # durumu PMedianResult.kmedoids_converged ile şeffaf raporlanıyor —
    # kullanıcı sonucun kalitesini yorumlayabilir.
    MAX_ITER = KMEDOIDS_MAX_ITER

    while gelisim and iterasyon < MAX_ITER:
        gelisim = False
        iterasyon += 1
        for i_secili, _acik_j in enumerate(secili):
            for kapali_j in range(n_alan):
                if kapali_j in secili:
                    continue
                yeni_secim = secili[:i_secili] + [kapali_j] + secili[i_secili+1:]
                yeni_maliyet = toplam_maliyet(yeni_secim)
                if yeni_maliyet < mevcut_maliyet - 1e-6:
                    secili = yeni_secim
                    mevcut_maliyet = yeni_maliyet
                    gelisim = True
                    break
            if gelisim:
                break

    # Convergence durumu — döngüden çıkış sebebine göre üç durumlu ayrım
    # değil iki durumlu (None ILP'ye saklı):
    #   • gelisim=False ile çıktıysak → "no improving swap found" → CONVERGED
    #   • iterasyon >= MAX_ITER ise → takıldı, certified değil
    # NOT: gelisim=False ANCAK iterasyon=MAX_ITER aynı anda olabilir; bu
    # durumda son tur tek improving swap buldu ve hemen sonra MAX_ITER
    # ile durdu — pratikte "takıldı" sayılır. `iterasyon >= MAX_ITER`
    # önceliklidir.
    if iterasyon >= MAX_ITER:
        kmedoids_converged = False
        cb(f"Local search hit MAX_ITER={MAX_ITER} limit (cost={mevcut_maliyet:.1f}) "
           f"— result is best-found, NOT certified locally optimal")
    else:
        kmedoids_converged = True
        cb(f"Local search converged: {iterasyon} iterations, cost={mevcut_maliyet:.1f}")

    # ── Final assignment ──────────────────────────────────────────────────────
    sebep_kodlari = None
    if kapasiteler is not None:
        atama, _, sebep_kodlari = _assign_with_capacity(
            od_eff, agirliklar, secili, kapasiteler
        )
        n_kapasite_yetersiz = int((sebep_kodlari == 2).sum())
        if n_kapasite_yetersiz > 0:
            cb(
                f"[!] {n_kapasite_yetersiz} buildings could not be placed "
                f"due to insufficient capacity (AFAD 1.5 m²/person standard "
                f"not violated). Suggestion: increase p or disable the "
                f"capacity constraint."
            )
    else:
        # Her bina en yakın açık alana — ulaşılamayanlar -1
        atama = np.full(n_bina, -1, dtype=int)
        for i in range(n_bina):
            j_sureler = od_eff[i, secili]
            if np.isfinite(j_sureler).any():
                atama[i] = secili[int(np.argmin(j_sureler))]

    return _build_result(
        atama, secili, od_clean, binalar_gdf, toplanma_gdf, p,
        yontem="K-Medoids",
        amac=amac,   # P2.1: kullanıcı seçimi metadata'ya doğru aktarılır
        sure=time.time() - t0,
        max_sure_dk_kisit=max_sure_dk,
        kapasite_aktif=(kapasiteler is not None),
        sebep_kodlari=sebep_kodlari,
        kmedoids_converged=kmedoids_converged,
        kmedoids_iterations=iterasyon,
    )


def _assign_with_capacity(
    od_eff: np.ndarray,
    agirliklar: np.ndarray,
    acik: list[int],
    kapasiteler: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Kapasite kısıtlı greedy atama — hard constraint.

    Strateji:
      1. Her bina için açık alanlardaki yakınlıklara göre sıralı liste çıkar.
      2. Binaları 'en yakın alanı en uzak olan' sırasıyla önceliklendir
         (böylece zor binalar önce yerini alır).
      3. Her binayı kapasitesi yeten en yakın açık alana yerleştir.
      4. Kapasitesi yeten alan bulunamazsa atama[i] = -1 kalır (AFAD 1.5 m²/kişi
         standardı ihlal edilmez). Taşma YAPILMAZ.

    Dönüş: (atama_idxleri, süre_vektörü, sebep_kodlari).
      sebep_kodlari[i] ∈ {0, 1, 2}:
         0 = atandı,
         1 = sokak ağında ulaşılamaz (tüm süreler +inf),
         2 = kapasite yetersiz (ulaşılabilir alanlar dolu).
    """
    n_bina = od_eff.shape[0]

    od_acik = od_eff[:, acik]   # n_bina × n_acik

    # Her bina için en yakın mevcut açık alana süre
    en_yakin_sure = np.min(np.where(np.isfinite(od_acik), od_acik, np.inf), axis=1)

    # Zor binaları önce yerleştir (en yakın alanı en uzak olanlar)
    # Sonsuz olanlar en sona gitsin (zaten yerleşemeyecek)
    oncelik = np.argsort(-np.where(np.isfinite(en_yakin_sure), en_yakin_sure, -1))

    kalan_kapasite = kapasiteler[acik].astype(float).copy()
    atama = np.full(n_bina, -1, dtype=int)
    atama_sureleri = np.full(n_bina, np.inf)
    sebep = np.zeros(n_bina, dtype=np.int8)   # 0 default; aşağıda 1/2 set edilir

    for i in oncelik:
        # Ulaşılabilir aday açık alan yok mu? → "ağda ulaşılamaz"
        sureler = od_acik[i].copy()
        if not np.isfinite(sureler).any():
            sebep[i] = 1
            continue

        # Kapasitesi yeten, en yakın alanı bul
        sirali_idxler = np.argsort(sureler)
        yerlesti = False
        for k in sirali_idxler:
            s = sureler[k]
            if not np.isfinite(s):
                break
            if kalan_kapasite[k] >= agirliklar[i]:
                atama[i] = acik[k]
                atama_sureleri[i] = s
                kalan_kapasite[k] -= agirliklar[i]
                yerlesti = True
                break

        # DÜZELTME: Taşma yapma. Ulaşılabilir ama kapasitesi yeten alan yok
        # → bina `ulasilamaz_binalar`'a "kapasite yetersiz" sebebiyle gider.
        # Eski hali kalan_kapasite'yi negatife düşürüp AFAD standardını
        # ihlal ediyordu.
        if not yerlesti:
            sebep[i] = 2

    return atama, atama_sureleri, sebep


# ── Sonuç oluşturma ───────────────────────────────────────────────────────────

def _build_result(
    atama: np.ndarray,         # her bina için atanan alan indeksi; -1 = ulaşılamaz
    acik: list[int],           # açık alan indeksleri
    od: np.ndarray,
    binalar_gdf: gpd.GeoDataFrame,
    toplanma_gdf: gpd.GeoDataFrame,
    p: int,
    yontem: str,
    amac: str,
    sure: float,
    max_sure_dk_kisit: float | None,
    kapasite_aktif: bool,
    sebep_kodlari: np.ndarray | None = None,   # 0=atandı, 1=ağda ulaşılamaz, 2=kapasite yetersiz
    # K-Medoids convergence şeffaflığı — ILP yolundan çağrıldığında None
    # default'ları ile geriye uyumlu kalır; K-Medoids yolundan caller
    # bunları doldurur.
    kmedoids_converged: bool | None = None,
    kmedoids_iterations: int | None = None,
) -> PMedianResult:

    alan_adlari = (
        toplanma_gdf["ad"].tolist()
        if "ad" in toplanma_gdf.columns
        else [f"Alan {i}" for i in range(len(toplanma_gdf))]
    )

    b_wgs = binalar_gdf.to_crs("EPSG:4326")
    t_wgs = toplanma_gdf.to_crs("EPSG:4326")

    agirliklar = binalar_gdf["weight"].values.astype(float)
    mahalle_vals = binalar_gdf["mahalle"].values if "mahalle" in binalar_gdf.columns else [""] * len(atama)
    alan_m2_vals = binalar_gdf["alan_m2"].values if "alan_m2" in binalar_gdf.columns else np.zeros(len(atama))
    kat_vals = binalar_gdf["levels"].values if "levels" in binalar_gdf.columns else np.zeros(len(atama))

    # Bina etiketleri — data_loader tarafından zaten üretilmiş olmalı;
    # yoksa fallback "Bina k"
    if "bina_etiketi" in binalar_gdf.columns:
        bina_etiketleri = binalar_gdf["bina_etiketi"].astype(str).tolist()
    else:
        bina_etiketleri = [f"Bina {i+1}" for i in range(len(atama))]

    # ── Ulaşılabilir / ulaşılamaz ayrımı ──────────────────────────────────────
    ulasilabilir_mask = atama != -1
    ulasilamaz_mask = ~ulasilabilir_mask

    # ── Ulaşılabilir binalar için atamalar DataFrame'i ────────────────────────
    idx_list = np.where(ulasilabilir_mask)[0]
    sureler_tum = np.full(len(atama), np.nan)
    for i in idx_list:
        sureler_tum[i] = float(od[i, atama[i]])

    sureler = sureler_tum[idx_list]
    kalite_pairs = [_sure_sinifi(float(s)) for s in sureler]
    kaliteler = [p[0] for p in kalite_pairs]
    sure_araliklari = [p[1] for p in kalite_pairs]

    atanan_alan_idx = atama[idx_list]
    atanan_alan_adlari = [alan_adlari[j] for j in atanan_alan_idx]
    bina_etiketleri_atanan = [bina_etiketleri[i] for i in idx_list]

    # Alternatif en yakın 3 açık alan — ulaşılabilir olsun ya da olmasın kullanıcı görmek ister
    acik_arr = np.array(acik) if len(acik) > 0 else np.array([], dtype=int)
    alt_cols: dict[str, list] = {
        "alternatif_1": [], "alternatif_1_sure": [],
        "alternatif_2": [], "alternatif_2_sure": [],
        "alternatif_3": [], "alternatif_3_sure": [],
    }
    for i in idx_list:
        if len(acik_arr) == 0:
            for k in range(1, 4):
                alt_cols[f"alternatif_{k}"].append("")
                alt_cols[f"alternatif_{k}_sure"].append(np.nan)
            continue
        sureler_acik = od[i, acik_arr]
        # Atanmış alanı çıkarıp diğerlerini yakınlığa göre sırala
        diger_mask = acik_arr != atama[i]
        diger_idx = acik_arr[diger_mask]
        diger_sure = sureler_acik[diger_mask]
        sirala = np.argsort(diger_sure)
        diger_idx_sirali = diger_idx[sirala]
        diger_sure_sirali = diger_sure[sirala]
        for k in range(3):
            if k < len(diger_idx_sirali) and np.isfinite(diger_sure_sirali[k]):
                alt_cols[f"alternatif_{k+1}"].append(alan_adlari[diger_idx_sirali[k]])
                alt_cols[f"alternatif_{k+1}_sure"].append(round(float(diger_sure_sirali[k]), 2))
            else:
                alt_cols[f"alternatif_{k+1}"].append("")
                alt_cols[f"alternatif_{k+1}_sure"].append(np.nan)

    atamalar = pd.DataFrame({
        "bina_no":         np.arange(1, len(idx_list) + 1),
        "bina_idx":        idx_list,
        "bina_etiketi":    bina_etiketleri_atanan,
        "alan_idx":        atanan_alan_idx,
        "alan_adi":        atanan_alan_adlari,
        "atama_ozeti":     [
            f"{b} → {a}" for b, a in zip(bina_etiketleri_atanan, atanan_alan_adlari)
        ],
        "sure_dk":         np.round(sureler, 2),
        "sure_araligi":    sure_araliklari,
        "erisim_kalitesi": kaliteler,
        "mahalle":         [mahalle_vals[i] for i in idx_list],
        "agirlik":         agirliklar[idx_list],
        "alan_m2":         [alan_m2_vals[i] for i in idx_list],
        "kat_sayisi":      [kat_vals[i] for i in idx_list],
        "bina_enlem":      [b_wgs.geometry.iloc[i].y for i in idx_list],
        "bina_boylam":     [b_wgs.geometry.iloc[i].x for i in idx_list],
        "alan_enlem":      [t_wgs.geometry.iloc[j].y for j in atanan_alan_idx],
        "alan_boylam":     [t_wgs.geometry.iloc[j].x for j in atanan_alan_idx],
        **alt_cols,
    })

    # ── Ulaşılamayan binalar ──────────────────────────────────────────────────
    ulasilamaz_idxler = np.where(ulasilamaz_mask)[0]
    if len(ulasilamaz_idxler) > 0:
        # Reason text: parse sebep_kodlari (0/1/2) from K-Medoids if present;
        # otherwise (ILP path) use the classic message.
        def _sebep_metni(idx: int) -> str:
            if sebep_kodlari is not None:
                kod = int(sebep_kodlari[idx])
                if kod == 2:
                    return "Insufficient capacity (reachable areas full)"
                if kod == 1:
                    return "Unreachable in walking network"
            # ILP path or capacity-less k-medoids
            if max_sure_dk_kisit:
                return f"Nearest area > {max_sure_dk_kisit} min"
            return "Unreachable in walking network"

        ulasilamaz_df = pd.DataFrame({
            "bina_idx":     ulasilamaz_idxler,
            "bina_etiketi": [bina_etiketleri[i] for i in ulasilamaz_idxler],
            "mahalle":      [mahalle_vals[i] for i in ulasilamaz_idxler],
            "agirlik":      agirliklar[ulasilamaz_idxler],
            "alan_m2":      [alan_m2_vals[i] for i in ulasilamaz_idxler],
            "bina_enlem":   [b_wgs.geometry.iloc[i].y for i in ulasilamaz_idxler],
            "bina_boylam":  [b_wgs.geometry.iloc[i].x for i in ulasilamaz_idxler],
            "sebep":        [_sebep_metni(i) for i in ulasilamaz_idxler],
        })
    else:
        ulasilamaz_df = pd.DataFrame()

    # ── Metrikler ─────────────────────────────────────────────────────────────
    ag_atanan = agirliklar[idx_list]
    agirlikli_sure_toplam = float((sureler * ag_atanan).sum()) if len(sureler) else 0.0
    agirlikli_ort_sure = (
        agirlikli_sure_toplam / ag_atanan.sum() if ag_atanan.sum() > 0 else 0.0
    )

    def kapsama_bina(t: float) -> float:
        return float((sureler <= t).mean() * 100) if len(sureler) else 0.0

    def kapsama_nufus(t: float) -> float:
        if ag_atanan.sum() == 0:
            return 0.0
        return float((ag_atanan[sureler <= t]).sum() / ag_atanan.sum() * 100)

    # P95 düzeltmesi (P1 bulgusu): rapor edilen p95, optimizer'ın `min_p95`
    # hedefinde kullandığı `_weighted_percentile` ile AYNI ağırlık mantığını
    # kullanmalı — aksi halde "min_p95 modunda neden raporlanan p95 hedef
    # fonksiyondan farklı?" tutarsızlığı oluşur ve karar verici yanlış
    # yönlendirilir. Ağırlıksız bina-bazlı versiyon yan alan olarak
    # informasyonel kalır.
    if len(sureler):
        p95 = _weighted_percentile(sureler, ag_atanan, P95_PERCENTILE)
        # Edge case: ağırlık toplamı sıfırsa weighted_percentile NaN döndürür;
        # bu durumda ağırlıksıza düş (fallback).
        if np.isnan(p95):
            p95 = float(np.percentile(sureler, 95))
        p95_bina = float(np.percentile(sureler, 95))
    else:
        p95 = 0.0
        p95_bina = 0.0

    # ── Alan bazlı özet ───────────────────────────────────────────────────────
    alan_ozet_rows = []
    for j in acik:
        mask = atanan_alan_idx == j
        if mask.sum() == 0:
            alan_ozet_rows.append({
                "Toplanma Alanı":  alan_adlari[j],
                "Atanan Bina":     0,
                "Toplam Ağırlık":  0.0,
                "Ort. Süre (dk)":  0.0,
                "Max Süre (dk)":   0.0,
                "Kapsama <5dk %":  0.0,
                "Kapsama <10dk %": 0.0,
                "Uzak / Çok Uzak Bina": 0,
            })
            continue
        alan_sureleri = sureler[mask]
        alan_agir = ag_atanan[mask]
        alan_ozet_rows.append({
            "Toplanma Alanı":  alan_adlari[j],
            "Atanan Bina":     int(mask.sum()),
            "Toplam Ağırlık":  round(float(alan_agir.sum()), 1),
            "Ort. Süre (dk)":  round(float(alan_sureleri.mean()), 1),
            "Max Süre (dk)":   round(float(alan_sureleri.max()), 1),
            "Kapsama <5dk %":  round(float((alan_sureleri <= 5).mean() * 100), 1),
            "Kapsama <10dk %": round(float((alan_sureleri <= 10).mean() * 100), 1),
            "Uzak / Çok Uzak Bina": int((alan_sureleri > 15).sum()),
        })
    alan_ozeti = (
        pd.DataFrame(alan_ozet_rows)
        .sort_values("Ort. Süre (dk)", ascending=False)
        .reset_index(drop=True)
        if alan_ozet_rows else pd.DataFrame()
    )

    return PMedianResult(
        atamalar               = atamalar,
        acik_alanlar           = acik,
        acik_alan_adlari       = [alan_adlari[j] for j in acik],
        toplam_agirlikli_sure  = agirlikli_sure_toplam,
        ort_sure_dk            = float(sureler.mean()) if len(sureler) else 0.0,
        agirlikli_ort_sure_dk  = agirlikli_ort_sure,
        max_sure_dk            = float(sureler.max()) if len(sureler) else 0.0,
        p95_bina_sure_dk       = p95_bina,
        p95_sure_dk            = p95,
        kapsama_5dk_pct        = kapsama_bina(5),
        kapsama_10dk_pct       = kapsama_bina(10),
        kapsama_30dk_pct       = kapsama_bina(30),
        nufus_kapsama_5dk_pct  = kapsama_nufus(5),
        nufus_kapsama_10dk_pct = kapsama_nufus(10),
        nufus_kapsama_30dk_pct = kapsama_nufus(30),
        ulasilamaz_sayisi      = int(len(ulasilamaz_idxler)),
        ulasilamaz_nufus       = float(agirliklar[ulasilamaz_idxler].sum()),
        ulasilamaz_binalar     = ulasilamaz_df,
        yontem                 = yontem,
        amac                   = amac,
        cozum_suresi_sn        = sure,
        p                      = p,
        max_sure_dk_kisit      = max_sure_dk_kisit,
        kapasite_aktif         = kapasite_aktif,
        kmedoids_converged     = kmedoids_converged,
        kmedoids_iterations    = kmedoids_iterations,
        alan_ozeti             = alan_ozeti,
    )


# ── Duyarlılık analizi ────────────────────────────────────────────────────────

def duyarlilik_analizi(
    od: np.ndarray,
    binalar_gdf: gpd.GeoDataFrame,
    toplanma_gdf: gpd.GeoDataFrame,
    p_aralik: range | None = None,
    kapasite: bool = False,
    max_sure_dk: float | None = None,
    amac: ObjectiveMode = "min_sum",
    progress_cb: Callable | None = None,
    solver: SolverMode = "auto",
    time_limit_sn: int | None = None,
    allow_fallback: bool = True,
) -> pd.DataFrame:
    """
    Farklı p değerleri için çözüm kalitesini karşılaştırır.
    Kaç toplanma alanının 'yeterli' olduğunu bulmak için kullanılır.

    solver/time_limit_sn/allow_fallback parametreleri her p için coz()'a iletilir.
    """
    if p_aralik is None:
        n_alan = od.shape[1]
        p_aralik = range(1, min(n_alan + 1, 16))

    satirlar = []
    for p in p_aralik:
        sonuc = coz(
            od, binalar_gdf, toplanma_gdf,
            p=p, kapasite=kapasite, max_sure_dk=max_sure_dk,
            amac=amac, progress_cb=progress_cb,
            solver=solver, time_limit_sn=time_limit_sn,
            allow_fallback=allow_fallback,
        )
        satirlar.append({
            "p":                       p,
            "Ort. Süre (dk)":          round(sonuc.ort_sure_dk, 2),
            "Ağ. Ort. Süre (dk)":      round(sonuc.agirlikli_ort_sure_dk, 2),
            "Max Süre (dk)":           round(sonuc.max_sure_dk, 2),
            # P95 düzeltmesi: birincil sütun nüfus-ağırlıklı (hedef fonk. ile
            # tutarlı). Bina-bazlı ağırlıksız değer informasyonel yan sütun.
            "P95 Süre (dk, nüfus-ağırlıklı)": round(sonuc.p95_sure_dk, 2),
            "P95 Süre (dk, bina-bazlı)":     round(sonuc.p95_bina_sure_dk, 2),
            "Kapsama <5dk %":          round(sonuc.kapsama_5dk_pct, 1),
            "Kapsama <10dk %":         round(sonuc.kapsama_10dk_pct, 1),
            "Kapsama <30dk %":         round(sonuc.kapsama_30dk_pct, 1),
            "Nüfus Kapsama <5dk %":    round(sonuc.nufus_kapsama_5dk_pct, 1),
            "Nüfus Kapsama <10dk %":   round(sonuc.nufus_kapsama_10dk_pct, 1),
            "Nüfus Kapsama <30dk %":   round(sonuc.nufus_kapsama_30dk_pct, 1),
            "Ulaşılamaz Bina":         sonuc.ulasilamaz_sayisi,
            "Yöntem":                  sonuc.yontem,
        })
    return pd.DataFrame(satirlar)
