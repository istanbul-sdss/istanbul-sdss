"""
Regresyon: pipeline sonuçları `rule_code` ile anahtarlanmalı.

Bulgu #1 — `results[label_tr]` kullanımı, aynı `label_tr`'yi paylaşan kurallar
arasında (ör. `building_police` + `infrastructure_police` → "Karakol") sessiz
çarpışmaya yol açıyordu.
"""
from __future__ import annotations

from src.config.tag_rules import TAG_RULES


def test_rule_codes_are_unique():
    """Her kural benzersiz bir rule_code taşımalı (dict anahtarı zaten benzersiz)."""
    assert len(TAG_RULES) == len(set(TAG_RULES.keys()))


def test_label_tr_collisions_are_real():
    """
    Birden fazla kural aynı label_tr'yi paylaşıyor olabilir (registry UX
    kararı). Bu test o çakışmayı **belgeliyor** — pipeline artık anahtar
    olarak rule_code kullandığı için sessiz veri kaybı olmamalı.
    """
    seen: dict[str, list[str]] = {}
    for rule_code, rule in TAG_RULES.items():
        label = rule.get("label_tr")
        if not label:
            continue
        seen.setdefault(label, []).append(rule_code)

    duplicates = {lbl: codes for lbl, codes in seen.items() if len(codes) > 1}

    # En az bir çakışma bekliyoruz ("Karakol" gibi); yoksa bu test
    # güncelliğini yitirmiş demektir.
    assert "Karakol" in duplicates, (
        "TAG_RULES güncellendi; Karakol çakışması kalktıysa bu regresyon "
        "testi sadeleşmeli. Çakışma sayısı: " + str(len(duplicates))
    )
    # building_police + infrastructure_police ikisi de listede olmalı
    police_codes = set(duplicates.get("Karakol", []))
    assert {"building_police", "infrastructure_police"}.issubset(police_codes)


def test_pipeline_keys_by_rule_code():
    """
    pipeline.run_pipeline içindeki `results[rule_code] = result` satırı,
    çakışan label_tr'lerde her kuralın ayrı bir result üretmesini garanti
    ediyor. Bu testi statik olarak (network'e çıkmadan) kaynak dosyadan
    okuyarak doğruluyoruz.
    """
    import re
    from pathlib import Path

    src = Path("src/pipelines/pipeline.py").read_text(encoding="utf-8")
    # results[label] ESKİ hali, results[rule_code] YENİ hali
    # (Python'da hizalama için fazla boşluk olabilir; regex ile toleranslı tarıyoruz.)
    assert re.search(r"results\[rule_code\]\s*=\s*result", src), (
        "Pipeline hâlâ results'ı label_tr ile anahtarlıyor olabilir — "
        "regresyon riski"
    )
    # ESKİ hatalı pattern geri gelmesin
    assert not re.search(r"results\[label\]\s*=\s*result\b", src), (
        "REGRESYON: `results[label] = result` eski hali geri gelmiş"
    )
    # result içinde hem label_tr hem category_group olmalı (consumer için)
    assert 'result["label_tr"]' in src
    assert 'result["category_group"]' in src


# ── P2.5: iki yönlü registry ↔ rule audit ─────────────────────────────────────
# Mevcut audit'ler "registry'deki kod TAG_RULES'da var mı" yönünü kontrol
# ediyordu. Ters yön ("rule var ama UI'da yok") sessizce atlandığı için
# `cemevi` gibi kurallar arayüzden erişilemez halde kalmıştı (P2.5).


# Bilinçli olarak UI dışı tutulmak istenen rule'lar (varsa) buraya eklenebilir;
# her giriş `cemevi` gibi açıkça gerekçelendirilmelidir.
INTERNAL_ONLY_RULES: set[str] = set()


def test_every_rule_is_reachable_from_registry_or_internal_allowlist():
    """
    REGRESYON (P2.5): TAG_RULES içindeki her kural ya CATEGORY_REGISTRY'de
    bir alt-kategori olarak yer almalı ya da INTERNAL_ONLY_RULES allowlist'inde
    olmalı. Aksi halde kural bakımı yapılmış ama kullanıcı arayüzünden hiç
    çalıştırılamaz halde kalır.
    """
    from src.config.category_registry import CATEGORY_REGISTRY
    from src.config.tag_rules import TAG_RULES

    registry_codes = {
        sub["code"]
        for cat in CATEGORY_REGISTRY.values()
        for sub in cat["subcategories"]
    }
    rule_codes = set(TAG_RULES.keys())

    orphans = rule_codes - registry_codes - INTERNAL_ONLY_RULES
    assert not orphans, (
        "REGRESYON (P2.5): aşağıdaki rule(lar) CATEGORY_REGISTRY'de yok ve "
        "INTERNAL_ONLY_RULES allowlist'inde de yer almıyor — kullanıcı bunları "
        "UI'dan çalıştıramaz:\n  " + ", ".join(sorted(orphans)) +
        "\nÇözüm: ya registry'ye uygun bir kategori altına ekleyin, ya da "
        "açık bir gerekçe ile INTERNAL_ONLY_RULES'a alın."
    )


def test_registry_codes_all_have_rules():
    """
    Diğer yön: CATEGORY_REGISTRY'deki her code, TAG_RULES içinde tanımlı
    olmalı. Aksi halde UI'da seçilebilir ama backend boş döner.
    """
    from src.config.category_registry import CATEGORY_REGISTRY
    from src.config.tag_rules import TAG_RULES

    # admin_* rule'ları admin_levels.py üzerinden çalışıyor — TAG_RULES'da yok.
    skip_prefixes = ("admin_",)

    registry_codes = {
        sub["code"]
        for cat in CATEGORY_REGISTRY.values()
        for sub in cat["subcategories"]
        if not sub["code"].startswith(skip_prefixes)
    }
    missing = registry_codes - set(TAG_RULES.keys())
    assert not missing, (
        "REGRESYON: registry'de seçilebilir alt-kategori var ama TAG_RULES'da "
        "tanımlı değil; kullanıcı seçince boş sonuç alır:\n  "
        + ", ".join(sorted(missing))
    )
