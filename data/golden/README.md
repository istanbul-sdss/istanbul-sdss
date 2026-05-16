# Golden Datasets — Name Lookup Quality Measurement

Bu klasör, Name Lookup modülünün **gerçek doğruluğunu** ölçmek için elle
doğrulanmış referans listelerini içerir. "Sistem ne kadar iyi?" sorusuna
sayısal bir cevap verebilmenin tek yolu budur.

## Kullanım

```bash
# Tek ilçe için ölçüm (Overpass çağrısı gerektirir, ~30-60 sn)
python -m tests.golden_runner --district Kadıköy

# Hızlı: cache'lenmiş pool varsa diskten okur
python -m tests.golden_runner --district Kadıköy --use-cache

# pytest entegrasyonu (eşik altında düşerse fail)
pytest tests/test_golden_kadikoy.py
```

## Dosya formatı

CSV, UTF-8, header zorunlu.

| Kolon | Zorunlu | Açıklama |
|---|---|---|
| `input_name` | ✅ | Kullanıcı listesinde olduğu gibi ham isim. Türkçe karakter, kısaltma, gürültü serbest. |
| `input_neighborhood` | — | Mahalle hint'i (varsa). Boş bırakıldığında filtre uygulanmaz. |
| `expected_status` | ✅ | `Matched` / `Possible match` / `Ambiguous` / `Not found`. Sistem bu kategoride dönmeli. |
| `expected_osm_id` | — | Beklenen OSM kayıt ID'si. `expected_status=Matched` ise zorunlu. Birden fazla kabul edilebilir aday varsa pipe ile ayrı: `123|456`. |
| `expected_category` | — | Beklenen `amenity=*` / `leisure=*` / `shop=*` etiketi (audit için bilgi amaçlı). |
| `notes` | — | Test yazarın notu — neden bu satır kritik, hangi senaryoyu yakalıyor. |

## Satır eklerken

1. Kayıt **OSM'de gerçekten var olmalı**. ([overpass-turbo.eu](https://overpass-turbo.eu) ile doğrula.)
2. `input_name` sütununa kullanıcının tipik yazdığı şekli yaz — kısaltmalar, eksik suffix'ler, yazım varyantları **iyi**.
3. **Boundary case'leri ekle**: aynı isimde farklı mahallede 2 yer, jenerik isim ("Park", "Cami"), hatalı tag'li POI, mistag potansiyeli.
4. `expected_status=Not found` satırları da değerli — sistemin yanlış yere "buldum" demediğini ölçüyoruz.

## Metrikler

`tests/test_golden_kadikoy.py` şu raporu üretir:

```
Kategori           | Top-1 | Top-3 | Not Found Doğruluğu
─────────────────────────────────────────────────────
eczane             |  92%  |  97%  |   95%
ilkokul            |  88%  |  95%  |   93%
park               |  76%  |  88%  |   80%
─────────────────────────────────────────────────────
TOPLAM             |  82%  |  91%  |   88%
```

- **Top-1**: `expected_osm_id` `best_match`'in OSM ID'sine eşit mi?
- **Top-3**: `expected_osm_id` top-3 aday içinde mi?
- **Not Found Doğruluğu**: `expected_status="Not found"` satırlarında sistem
  gerçekten "Not found" döndü mü? (False positive ölçümü.)

## Mevcut Setler

| Dosya | İlçe | Satır | Hazırlayan | Tarih |
|---|---|---|---|---|
| `name_lookup_kadikoy.csv` | Kadıköy | 25 (template; 200'e çıkarılacak) | Faz N2 başlangıç | 2026-05 |
