"""
Çapraz kategori sızıntı denetimi (cross-category leakage audit).

Sebep: Overpass union sorguları kategori sınırını aşan kayıtlar çekebiliyor —
ör. Beykoz "Cami" sorgusu mezarlık node'larını da getirdi, post_filter
+ rule değerlendirmesi onları matched=False olarak ayıkladı (doğru davranış).
Kullanıcı sorusu: "Bu eleme her kategori için doğru çalışıyor mu?"

Bu test paketi şunları doğrular:
  1. Her rule kendi KANONİK örneğini matched=True olarak işaretliyor.
  2. Her rule, KOMŞU kategorilerden gelen "yanlış" örnekleri matched=False
     olarak ayıklıyor (sızıntı yok).
  3. apply_strict_post_filter, query_tag birincil anahtarı taşımayan kayıtları
     fetch sonrası eliyor.

Yeni rule eklendiğinde MUTLAKA POSITIVE_SAMPLES + NEGATIVE_SAMPLES eklenmeli;
aksi halde sessiz sızıntı / sessiz eleme tehlikesi.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from src.config.tag_rules import TAG_RULES
from src.services.post_filter import apply_religion_filter, apply_strict_post_filter
from src.services.rule_engine import evaluate_rule

# ─────────────────────────────────────────────────────────────────────────────
# Kanonik POZİTİF örnekler — rule mutlaka matched=True olarak işaretlemeli.
# ─────────────────────────────────────────────────────────────────────────────
# (rule_code, etiket dict, açıklama)
POSITIVE_SAMPLES: list[tuple[str, dict, str]] = [
    # Dini yapılar
    ("building_mosque",   {"amenity": "place_of_worship", "religion": "muslim", "building": "mosque", "name": "Sultan Camii"}, "kanonik cami"),
    ("building_mosque",   {"building": "mosque", "name": "Mahalle Camii"}, "sadece building=mosque + isim"),
    ("building_church",   {"amenity": "place_of_worship", "religion": "christian", "building": "church", "name": "St. Antuan Kilisesi"}, "kanonik kilise"),
    ("building_synagogue",{"amenity": "place_of_worship", "religion": "jewish", "building": "synagogue", "name": "Neve Şalom Sinagogu"}, "kanonik sinagog"),
    # Sağlık
    ("hospital",          {"amenity": "hospital", "healthcare": "hospital", "name": "Devlet Hastanesi"}, "kanonik hastane"),
    ("clinic",            {"amenity": "clinic", "healthcare": "clinic"}, "kanonik klinik"),
    ("pharmacy",          {"amenity": "pharmacy", "name": "Eczane"}, "kanonik eczane"),
    # Eğitim
    ("building_school",     {"building": "school", "amenity": "school", "name": "Atatürk İlkokulu"}, "kanonik okul"),
    ("building_university", {"building": "university", "amenity": "university", "name": "Boğaziçi Üniversitesi"}, "kanonik üniversite"),
    # Konut
    ("building_residential",{"building": "residential"}, "kanonik konut"),
    ("building_apartments", {"building": "apartments"}, "kanonik apartman"),
    ("building_house",      {"building": "house"}, "kanonik müstakil"),
    # Yeşil / rekreasyon
    ("park",                {"leisure": "park", "name": "Maçka Parkı"}, "kanonik park"),
    # Toplanma
    ("assembly_point",      {"emergency": "assembly_point"}, "kanonik AFAD toplanma"),
]


# ─────────────────────────────────────────────────────────────────────────────
# NEGATİF örnekler — rule MUTLAKA matched=False döndürmeli.
# Bunlar "komşu kategoriden sızabilecek" gerçek dünya senaryoları.
# ─────────────────────────────────────────────────────────────────────────────
# (rule_code, etiket dict, neden sızıntı riski olduğu)
NEGATIVE_SAMPLES: list[tuple[str, dict, str]] = [
    # Cami sorgusuna sızabilecek tip kayıtlar (Beykoz senaryosu)
    ("building_mosque",   {"amenity": "grave_yard"}, "mezarlık node — cami fetch'inde sızabilir"),
    ("building_mosque",   {"landuse": "cemetery"}, "mezar arazi — cami query'sinde gelmemeli"),
    ("building_mosque",   {"amenity": "place_of_worship", "religion": "christian", "building": "church"}, "kilise → cami olarak işaretlenmemeli"),
    ("building_mosque",   {"historic": "memorial", "name": "Şehit Anıtı"}, "anıt — cami değil"),

    # Kilise sorgusuna cami sızması
    ("building_church",   {"amenity": "place_of_worship", "religion": "muslim", "building": "mosque"}, "cami → kilise olarak işaretlenmemeli"),

    # Hastane sorgusuna sızabilecek ama hastane olmayan tıbbi yerler
    ("hospital",          {"amenity": "clinic", "healthcare": "clinic"}, "klinik hastane DEĞİL"),
    ("hospital",          {"amenity": "doctors", "healthcare": "doctor"}, "doktor muayenehane hastane değil"),
    ("hospital",          {"amenity": "pharmacy", "healthcare": "pharmacy"}, "eczane hastane değil"),

    # Klinik sorgusuna hastane sızması
    ("clinic",            {"amenity": "hospital", "healthcare": "hospital"}, "hastane klinik DEĞİL (büyük tesis)"),

    # Okul sorgusuna sızabilecek
    ("building_school",     {"building": "kindergarten", "amenity": "kindergarten"}, "anaokulu (ayrı kategori)"),
    ("building_school",     {"building": "university", "amenity": "university"}, "üniversite okul değil"),

    # Üniversite sorgusuna lise sızması
    ("building_university", {"building": "school", "amenity": "school", "name": "Galatasaray Lisesi"}, "lise üniversite değil"),

    # Konut sorgusuna sızabilecek
    ("building_residential",{"building": "commercial"}, "ticari bina konut değil"),
    ("building_residential",{"building": "industrial"}, "endüstriyel bina konut değil"),
    ("building_residential",{"building": "garage"},     "garaj konut değil"),

    # Park sorgusuna sızabilecek
    ("park",                {"leisure": "playground"}, "oyun alanı park alt-kategorisi olabilir ama park değil"),
    ("park",                {"landuse": "forest"},     "orman park değil"),
    ("park",                {"amenity": "parking"},    "otopark park değil"),

    # AFAD toplanma noktası sorgusuna sızabilecek
    # NOT: assembly_point UMBRELLA — leisure=park query_tag_match ile resolved'a düşer
    # (low confidence). Bu DOĞRU davranış (AFAD fallback) — bu yüzden burada test etmiyoruz.
    # Ama gerçekten alakasız bir şey AYIKLANMALI:
    ("assembly_point",      {"shop": "supermarket"}, "süpermarket AFAD toplanma değil"),
    ("assembly_point",      {"highway": "primary"},  "yol AFAD toplanma değil"),

    # Eczane sorgusuna sızabilecek
    ("pharmacy",            {"amenity": "doctors"},  "doktor muayenesi eczane değil"),
    ("pharmacy",            {"shop": "convenience"}, "market eczane değil"),
]


# ─────────────────────────────────────────────────────────────────────────────
# TESTLER
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("rule_code,tags,note", POSITIVE_SAMPLES)
def test_positive_samples_match(rule_code, tags, note):
    """Kanonik örnek mutlaka matched=True olmalı."""
    if rule_code not in TAG_RULES:
        pytest.skip(f"{rule_code} TAG_RULES'da tanımlı değil")
    result = evaluate_rule(pd.Series(tags), rule_code)
    assert result["matched"] is True, (
        f"REGRESYON: {rule_code} kanonik örneği eşleştirmedi.\n"
        f"  Tag: {tags}\n"
        f"  Açıklama: {note}\n"
        f"  Reason: {result['reason']}, score: {result['score']}"
    )


@pytest.mark.parametrize("rule_code,tags,note", NEGATIVE_SAMPLES)
def test_negative_samples_rejected(rule_code, tags, note):
    """Komşu kategoriden sızan örnek MUTLAKA matched=False olmalı."""
    if rule_code not in TAG_RULES:
        pytest.skip(f"{rule_code} TAG_RULES'da tanımlı değil")
    result = evaluate_rule(pd.Series(tags), rule_code)
    assert result["matched"] is False, (
        f"SIZINTI: {rule_code} alakasız örneği KABUL ETTİ — bu kategori "
        f"sayfasını kirletir.\n"
        f"  Tag: {tags}\n"
        f"  Sebep: {note}\n"
        f"  Reason: {result['reason']}, score: {result['score']}"
    )


def test_post_filter_drops_off_topic_rows_for_cami():
    """
    Beykoz senaryosunun unit re-creation'ı: Cami fetch'ine karışan mezarlık /
    kilise / oyun alanı kayıtları post_filter + classification sonunda
    rapora KARIŞMAMALI (matched=False).
    """
    rows = [
        {"amenity": "place_of_worship", "religion": "muslim", "building": "mosque", "name": "Cami"},
        {"amenity": "place_of_worship", "religion": "christian", "building": "church", "name": "Kilise"},
        {"amenity": "grave_yard", "name": "Hazire"},
        {"landuse": "cemetery", "name": "Mezarlık"},
        {"leisure": "playground", "name": "Çocuk Parkı"},
    ]
    gdf = gpd.GeoDataFrame(
        rows,
        geometry=[Point(29.0 + i * 0.001, 41.0) for i in range(len(rows))],
        crs="EPSG:4326",
    )
    # 1. post_filter
    filtered = apply_strict_post_filter(gdf, "building_mosque")
    # Sadece cami (place_of_worship) ve kilise (place_of_worship) kalır
    # (her ikisi de strict_tags={amenity:place_of_worship} eşler)
    assert len(filtered) >= 1
    # mezarlık ve oyun alanı bu noktada elenmeli
    assert "grave_yard" not in filtered.get("amenity", pd.Series([])).values
    assert "playground" not in filtered.get("leisure", pd.Series([])).values

    # 2. religion filtresi: kilise düşer
    after_religion = apply_religion_filter(filtered, "muslim")
    religions = set(after_religion.get("religion", pd.Series([])).dropna().unique())
    assert "christian" not in religions, (
        f"SIZINTI: religion=christian post_filter sonrası kaldı: {religions}"
    )

    # 3. classification: ne kalmışsa cami olarak matched=True
    for _, row in after_religion.iterrows():
        result = evaluate_rule(row, "building_mosque")
        assert result["matched"] is True, (
            f"Religion filtresi sonrası kalan kayıt cami olarak matched değil: "
            f"{dict(row)} → {result}"
        )


def test_no_silent_drop_when_strict_and_query_align():
    """
    'strict = query' rule'u için: query'de listelenen TAG KOMBİNASYONU strict
    eşleşme vermeli. Sessiz düşüm olmamalı.

    Önemli: admin_* gibi rule'larda strict AND'li bir dict
    ({boundary:administrative, admin_level:8}) — tek tek tag yetmez. Bu yüzden
    her query_tag ENTRY'si (kendisi bir dict) bir bütün olarak test edilir.
    """
    failed = []
    for code, r in TAG_RULES.items():
        qt = r.get("query_tags") or []
        st = r.get("strict_tags") or {}
        if not isinstance(st, dict) or not st:
            continue  # list-form strict zaten farklı semantik

        st_pairs = {(k, str(v)) for k, v in st.items()}

        for q in qt:
            if not isinstance(q, dict):
                continue
            q_pairs = {(k, str(v)) for k, v in q.items()}
            # Bu query entry strict ile birebir aynı mı?
            if q_pairs == st_pairs:
                row = pd.Series(q)
                result = evaluate_rule(row, code)
                if not result["matched"]:
                    failed.append((code, q, result["reason"]))

    assert not failed, (
        "SIZINTI / SESSİZ DÜŞÜM: aligned (strict=query) rule'larda kanonik "
        "tag KOMBİNASYONU eşleşmedi:\n" + "\n".join(
            f"  {c}: {q} → {r}" for c, q, r in failed
        )
    )
