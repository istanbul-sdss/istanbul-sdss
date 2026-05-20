"""
Density (m²/person) parametre regresyonu.

Hocaların geri bildirimi: AFAD pratik 1.5 m²/kişi default; ama uzun-süreli
barınma 2.5 m², acil yüksek yoğunluk 1.0 m². Kullanıcı UI'dan değiştirir
ve kapasiteyi yeniden hesaplar.

Bu test alt-katman fonksiyonu doğruluyor — UI tarafı Streamlit ile
manuel test edilir, ama core math her density değerinde tutarlı çalışmalı.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.config.settings import AFAD_M2_PER_PERSON
from src.optimizer.population_estimator import estimate_capacity_afad


def test_default_density_matches_settings():
    """Parametresiz çağrı AFAD_M2_PER_PERSON (=1.5) kullanmalı — geriye uyumlu."""
    cap = estimate_capacity_afad(1500.0)
    expected = round(1500.0 / AFAD_M2_PER_PERSON)
    assert cap == expected


def test_higher_density_reduces_capacity():
    """
    Aynı alan, daha yüksek m²/kişi → daha az kişi.
    1500 m² salon: 1.0'da 1500 kişi, 1.5'te 1000, 2.5'te 600.
    """
    area = 1500.0
    cap_emergency = estimate_capacity_afad(area, m2_per_person=1.0)
    cap_afad      = estimate_capacity_afad(area, m2_per_person=1.5)
    cap_shelter   = estimate_capacity_afad(area, m2_per_person=2.5)

    assert cap_emergency == 1500
    assert cap_afad == 1000
    assert cap_shelter == 600
    # Monotonik azalan
    assert cap_emergency > cap_afad > cap_shelter


def test_series_input_vectorized_density():
    """pd.Series girdisi her satıra aynı density uygulamalı."""
    areas = pd.Series([1000.0, 2000.0, 500.0])
    caps_15 = estimate_capacity_afad(areas, m2_per_person=1.5)
    caps_25 = estimate_capacity_afad(areas, m2_per_person=2.5)

    # 1.5 m²/kişi
    assert caps_15.iloc[0] == 667   # 1000/1.5
    assert caps_15.iloc[1] == 1333  # 2000/1.5
    # 2.5 m²/kişi
    assert caps_25.iloc[0] == 400   # 1000/2.5
    assert caps_25.iloc[1] == 800   # 2000/2.5
    # Her hücrede 1.5 → 2.5 değişimi azalış
    assert (caps_15 > caps_25).all()


def test_min_capacity_floor_honored_at_any_density():
    """
    Küçük alan + yüksek density → matematiksel kapasite 50 altına düşse bile
    min_capacity=50 tabanı uygulanır.
    """
    # 100 m² × 2.5 m²/kişi = 40 kişi, ama floor 50
    cap = estimate_capacity_afad(100.0, m2_per_person=2.5)
    assert cap == 50


def test_numpy_array_input():
    """np.ndarray girdisi de desteklenmeli."""
    areas = np.array([1000.0, 2000.0, 500.0])
    caps = estimate_capacity_afad(areas, m2_per_person=1.5)
    assert caps[0] == 667
    assert caps[1] == 1333


def test_three_preset_densities_produce_distinct_capacities():
    """UI presets 1.0 / 1.5 / 2.5 — hepsi farklı kapasite üretmeli."""
    area = 3000.0
    cap_1 = estimate_capacity_afad(area, m2_per_person=1.0)
    cap_15 = estimate_capacity_afad(area, m2_per_person=1.5)
    cap_25 = estimate_capacity_afad(area, m2_per_person=2.5)
    assert len({cap_1, cap_15, cap_25}) == 3, (
        f"3 preset distinct olmalı: 1.0→{cap_1}, 1.5→{cap_15}, 2.5→{cap_25}"
    )
