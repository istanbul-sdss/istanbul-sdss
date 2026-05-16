"""
Regresyon: pipeline `resolved` DataFrame'i export etmeli, `classified`
değil (bulgu #2).

`leisure=park` gibi geniş bir union query assembly_point fetch'inde binlerce
parkı getirir; strict_tags/support_tags/name_fallback hiçbirine uymayanlar
`matched==False` ile işaretlenip `unresolved`'a düşer. Pipeline'ın bu
satırları KPI/export'a sızdırmadığını doğrularız.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from src.services.classification_service import (
    run_classification_pipeline,
    split_resolved_unresolved,
)


def _assembly_point_test_frame() -> gpd.GeoDataFrame:
    """
    4 satır, üç gerçek OSM etiketleme biçimini ve AFAD park fallback'ini
    temsil ediyor:

      (1) emergency=assembly_point           → strict (AFAD geleneksel)
      (2) amenity=assembly_point + isim      → strict (Türkçe haritalarda yaygın)
      (3) amenity=assembly_point, isim YOK   → strict (Kadıköy reality — 154 kayıt)
      (4) leisure=park tek başına            → resolved AMA düşük güven
                                               (AFAD park fallback; Türkiye
                                               OSM'inde explicit assembly tag
                                               nadir, pratikte parklar kullanılır)

    NOT: assembly_point rule'ı artık `strict_tags`'ı list-of-dict
    (OR-of-AND) semantiğiyle destekliyor. Parklar `accept_query_tag_match=True`
    sayesinde rule'un kendi query_tags'inden (`leisure=park`) geliyor —
    bu yüzden confidence="low" ve reason="query_tag_match". Downstream
    consumer'lar doğrulanmışı fallback'ten bu alanlarla ayırabilir.
    """
    rows = [
        # (1) emergency=assembly_point (strict #1)
        {
            "emergency": "assembly_point", "amenity": None, "leisure": None,
            "name": "Beşiktaş Toplanma Noktası",
            "latitude": 41.04, "longitude": 29.00, "osm_id": "1",
        },
        # (2) amenity=assembly_point + name (strict #2, ayrıca name ile teyitli)
        {
            "emergency": None, "amenity": "assembly_point", "leisure": None,
            "name": "Kadıköy Toplanma Alanı",
            "latitude": 40.99, "longitude": 29.03, "osm_id": "2",
        },
        # (3) amenity=assembly_point, name yok — eski kod bunu unresolved'a
        # atıyordu; Kadıköy'ün 154 kaydı çoğunlukla bu profilde.
        {
            "emergency": None, "amenity": "assembly_point", "leisure": None,
            "name": None,
            "latitude": 40.98, "longitude": 29.04, "osm_id": "3",
        },
        # (4) sadece leisure=park (reviewer'ın false-positive reprodüksiyonu)
        {
            "emergency": None, "amenity": None, "leisure": "park",
            "name": "Moda Parkı",
            "latitude": 40.98, "longitude": 29.02, "osm_id": "4",
        },
    ]
    df = pd.DataFrame(rows)
    return gpd.GeoDataFrame(
        df, geometry=[Point(r["longitude"], r["latitude"]) for r in rows],
        crs="EPSG:4326",
    )


def test_assembly_point_resolves_real_forms_and_park_fallback_with_low_confidence():
    """
    Üç uçlu regresyon:
      - Üç ayrı OSM etiket biçimindeki gerçek assembly_point'ler resolved
        olmalı VE strict_match/yüksek güven göstermeli (Kadıköy regresyonu).
      - Sıradan `leisure=park` kaydı da AFAD park fallback'i olarak
        resolved sayılmalı AMA reason="query_tag_match" ve confidence="low"
        taşımalı. Böylece consumer'lar etiketliyi fallback'ten ayırt edebilir.
      - Bu invariant, reviewer'ın bulgu #2 "parklar SESSİZCE yüksek güvenli
        assembly_point olarak sızmamalı" endişesini karşılıyor: parklar
        resolved'a düşüyor ama düşük güvenle ve açık reason etiketiyle.
    """
    gdf = _assembly_point_test_frame()

    clf = run_classification_pipeline(gdf, rule_codes=["assembly_point"])

    assert len(clf["classified"]) == 4
    classified = clf["classified"].set_index("osm_id")
    resolved_ids = set(clf["resolved"]["osm_id"].astype(str).tolist())

    # (1)-(3) gerçek assembly_point formları → strict match, resolved
    for rid in ("1", "2", "3"):
        assert rid in resolved_ids, (
            f"REGRESYON: strict-eşleşen assembly_point (id={rid}) resolved "
            f"değil — Kadıköy 154 → 0 bug'ı geri gelmiş olabilir."
        )
        row = classified.loc[rid]
        assert row["reason"] == "strict_match", (
            f"id={rid} strict_match yerine {row['reason']}"
        )

    # (4) leisure=park → resolved ama DÜŞÜK GÜVEN + query_tag_match reason
    assert "4" in resolved_ids, (
        "AFAD fallback: park kaydı resolved olmalı (aksi halde 'herhangi bir "
        "ilçe için assembly çekilemez' regresyonu geri döner)"
    )
    park_row = classified.loc["4"]
    assert park_row["reason"] == "query_tag_match", (
        f"Park fallback reason='query_tag_match' olmalı, {park_row['reason']} bulundu"
    )
    assert park_row["confidence"] == "low", (
        f"Park fallback confidence='low' olmalı (sessiz yüksek güvenli export "
        f"reviewer bulgu #2), {park_row['confidence']} bulundu"
    )


def test_query_tag_match_resolves_for_umbrella_rules():
    """
    Üsküdar 'Konut - Genel' regresyonu: `building_residential` union sorgusu
    5 tag formunu çekiyor ama strict yalnızca `building=residential`.
    Fetch'in getirdiği `building=apartments/house/detached/terrace` kayıtları
    da resolved'a düşmeli (query_tag_match mekanizması). Aksi halde
    3762 → 1464 resolved gibi büyük veri kaybı yaşanır.
    """
    import pandas as pd

    from src.services.rule_engine import evaluate_rule

    # building_residential query_tags içindeki 4 "genişletilmiş" form:
    extended_forms = [
        {"building": "apartments"},
        {"building": "house"},
        {"building": "detached"},
        {"building": "terrace"},
    ]
    for tags in extended_forms:
        row = pd.Series(tags)
        result = evaluate_rule(row, "building_residential")
        assert result["matched"] is True, (
            f"REGRESYON: {tags} building_residential fetch'iyle geldi ama "
            f"resolved'a düşmüyor. Üsküdar/Kadıköy gibi ilçelerde binlerce "
            f"kayıt unresolved'a iter."
        )

    # Strict form hâlâ `strict_match` reason'ı taşımalı; query_tag_match'e
    # düşmemeli — strict önceliği muhafaza edilmeli.
    strict_row = pd.Series({"building": "residential"})
    strict_result = evaluate_rule(strict_row, "building_residential")
    assert strict_result["reason"] == "strict_match"
    assert strict_result["used_strict"] is True


def test_umbrella_rules_query_tag_match_is_medium_confidence_not_low():
    """
    Analytics Dashboard regresyonu: kullanıcı şikâyeti — son güncellemelerden
    sonra "confidence breakdown" yüzdeleri dibe düştü. Nedeni query_tag_match
    yolunun score=1 (low) vermesiydi. Ama çoğu umbrella rule'da query_tags
    kanonik alternatif formlardır (ör. building_residential için
    building=apartments) — strict kadar güvenilirler.

    Default `query_tag_match_score=3` (medium), sadece assembly_point
    gibi filter-tipi rule'lar düşük değer override eder.
    """
    import pandas as pd

    from src.services.rule_engine import evaluate_rule

    # Kanonik alternatif formlar medium confidence taşımalı
    canonical_rows = [
        ("building_residential", {"building": "apartments"}),
        ("building_residential", {"building": "house"}),
        ("building_apartments",  {"building": "residential"}),
        ("building_hospital",    {"amenity":  "hospital"}),
        ("building_school",      {"amenity":  "school"}),
        ("hospital",             {"healthcare": "hospital"}),
        ("clinic",               {"healthcare": "clinic"}),
    ]
    for rule_code, tags in canonical_rows:
        result = evaluate_rule(pd.Series(tags), rule_code)
        assert result["matched"] is True, f"{rule_code}/{tags} matched olmalı"
        assert result["confidence"] in ("medium", "high"), (
            f"REGRESYON: {rule_code}/{tags} query_tag_match düşük güven veriyor "
            f"(confidence={result['confidence']}) — umbrella rule'larda kanonik "
            f"alternatifler medium+ olmalı, aksi halde Analytics güven dağılımı çöker."
        )


def test_tag_only_rule_strict_match_is_high_confidence():
    """
    Kullanıcı geri bildirimi: "Kadıköy'de residential seçtim, çekilen
    kayıtların subcategory'si residential — confidence medium geliyor,
    high olması gerekmez mi?" — haklı.

    `building_residential` gibi umbrella rule'larda support_tags ve
    name_patterns boş → rule yazarı "kanonik tag yeterli sinyal" demiş.
    Dolayısıyla strict match (building=residential) FULL confidence
    taşımalı (high), yarım sinyal (medium) değil.

    Bu bump sadece tag-only rule'lar için geçerli; support_tags tanımlıysa
    strict alone medium kalır (cross-validation beklenir).
    """
    import pandas as pd

    from src.services.rule_engine import evaluate_rule

    # Gerçek tag-only rule'lar (support_tags boş VE name_patterns boş):
    # strict match → high beklenir. Kullanıcının Kadıköy "residential seçtim"
    # senaryosu building_residential ile birebir bu case.
    canonical_tag_only_rows = [
        ("building_residential", {"building": "residential"}),
        ("building_apartments",  {"building": "apartments"}),
        ("building_house",       {"building": "house"}),
        ("building_detached",    {"building": "detached"}),
        ("building_industrial",  {"building": "industrial"}),
        ("building_warehouse",   {"building": "warehouse"}),
    ]
    for rule_code, tags in canonical_tag_only_rows:
        result = evaluate_rule(pd.Series(tags), rule_code)
        assert result["matched"] is True, f"{rule_code}/{tags} matched olmalı"
        assert result["reason"] == "strict_match", (
            f"{rule_code}/{tags} strict_match beklenirken {result['reason']}"
        )
        assert result["confidence"] == "high", (
            f"REGRESYON: {rule_code}/{tags} tag-only rule strict match medium "
            f"('{result['confidence']}') veriyor. Rule'da support/name yok — "
            f"kanonik tag match tam güven (high) olmalı."
        )

    # Karşı-örnek: support_tags veya name_patterns tanımlıysa tag-only DEĞİL,
    # strict alone medium kalmalı (cross-validation beklenir). Bu, user feedback
    # mantığının aşırı genelleştirilmemesini kilitler.
    from src.config.tag_rules import TAG_RULES
    for non_tag_only in ("building_school", "building_hospital", "park"):
        rule = TAG_RULES[non_tag_only]
        assert rule.get("support_tags") or rule.get("name_patterns"), (
            f"{non_tag_only} tag-only OLMAMALI — test varsayımı bozulmuş"
        )


def test_assembly_point_query_tag_match_override_stays_low():
    """
    assembly_point istisnai rule: leisure=park kanonik bir alternatif değil,
    hint. query_tag_match_score=1 override'ı low confidence'ı korumalı
    (reviewer bulgu #2).
    """
    import pandas as pd

    from src.config.tag_rules import TAG_RULES
    from src.services.rule_engine import evaluate_rule

    assert TAG_RULES["assembly_point"].get("query_tag_match_score") == 1, (
        "assembly_point filter-tipi rule; query_tag_match_score=1 override "
        "olmalı. Yoksa parklar yüksek güvenli assembly olarak export edilir."
    )

    park_row = pd.Series({"leisure": "park"})
    result = evaluate_rule(park_row, "assembly_point")
    assert result["confidence"] == "low", (
        f"assembly_point park fallback low olmalı, {result['confidence']}"
    )
    assert result["reason"] == "query_tag_match"


def test_assembly_point_park_fallback_is_labeled_low_confidence():
    """
    Ürün kararı: Türkiye OSM'inde explicit assembly_point etiketi nadir,
    AFAD pratiğinde parklar toplanma alanıdır. Bu yüzden `leisure=park`
    query_tag_match üzerinden resolved'a düşer — AMA düşük güvenle.

    Reviewer bulgu #2'nin özü ("sessiz yüksek-güvenli park export'u")
    hâlâ korunuyor: parklar görünür şekilde düşük güven taşıyor.
    """
    import pandas as pd

    from src.config.tag_rules import TAG_RULES
    from src.services.rule_engine import evaluate_rule

    assert TAG_RULES["assembly_point"].get("accept_query_tag_match") is True, (
        "assembly_point artık query_tag fallback kabul ediyor (park fallback "
        "AFAD pratiğiyle hizalı). Opt-out'a dönüş için açık ürün kararı lazım."
    )

    park_row = pd.Series({"leisure": "park", "name": "Moda Parkı",
                          "emergency": None, "amenity": None})
    result = evaluate_rule(park_row, "assembly_point")
    assert result["matched"] is True, (
        "REGRESYON: park fallback kapalı — 'herhangi bir ilçe için assembly "
        "çekilemez' bug'ı geri gelebilir."
    )
    assert result["reason"] == "query_tag_match"
    assert result["confidence"] == "low", (
        f"Park fallback düşük güvenli olmalı (reviewer #2), {result['confidence']}"
    )
    assert result["used_strict"] is False


def test_assembly_point_all_three_osm_forms_resolve_strict():
    """
    Üç gerçek OSM etiket biçimi strict eşleşme üretmeli:
      • emergency=assembly_point
      • amenity=assembly_point
      • amenity=emergency_assembly_point

    Bu test Option A fix'inin (strict_tags = list-of-dict) spesifikasyonudur.
    """
    import pandas as pd

    from src.services.rule_engine import evaluate_rule

    forms = [
        {"emergency": "assembly_point", "amenity": None},
        {"emergency": None, "amenity": "assembly_point"},
        {"emergency": None, "amenity": "emergency_assembly_point"},
    ]
    for tags in forms:
        row = pd.Series({**tags, "name": "Bilinmeyen Alan", "leisure": None})
        result = evaluate_rule(row, "assembly_point")
        assert result["matched"] is True, f"{tags} strict eşleşmedi"
        assert result["reason"] == "strict_match", f"{tags} strict yerine {result['reason']}"
        assert result["used_strict"] is True


def test_split_resolved_uses_matched_flag():
    """split_resolved_unresolved matched==False kriterini uyguluyor mu?"""
    df = pd.DataFrame({
        "rule_code":  ["assembly_point", "assembly_point", None],
        "confidence": ["high", "none", None],
        "matched":    [True, False, False],
    })
    resolved, unresolved = split_resolved_unresolved(df)
    assert len(resolved) == 1
    assert len(unresolved) == 2


def test_pipeline_exports_resolved_not_classified():
    """pipeline.py kaynağı clf['resolved'] kullandığını doğrula."""
    from pathlib import Path

    src = Path("src/pipelines/pipeline.py").read_text(encoding="utf-8")
    assert 'clf["resolved"]' in src, (
        "REGRESYON: pipeline resolved yerine classified export ediyor olabilir"
    )
