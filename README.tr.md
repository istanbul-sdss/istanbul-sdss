# İstanbul Mekânsal Karar Destek Sistemi

*[🇬🇧 English](README.md) · 🇹🇷 Türkçe*

**Streamlit + GeoPandas + OSMnx** tabanlı, İstanbul ilçeleri için OpenStreetMap
verisi çeken ve sınıflandıran, AFAD deprem toplanma alanı planlaması için
**kapasite-farkında p-median optimizasyonu** çalıştıran bir karar destek
sistemi. İki tamamlayıcı araç olarak gelir: bir ilçeyi temiz, haritalanmış,
kalite-kontrollü mekânsal veriye dönüştüren **Veri Toplama Aracı** ve bu verinin
üzerinde toplanma alanlarını optimal yerleştiren **Optimizasyon Aracı**.

## Canlı demolar

Her iki araç da Streamlit Community Cloud'da yayında — hiçbir şey kurmadan
tarayıcınızda tüm sistemi deneyebilirsiniz:

- **Veri Toplama Aracı** — <https://istanbul-sdss-data.streamlit.app/>
- **Optimizasyon Aracı** — <https://istanbul-sdss-optimization.streamlit.app/>

> Uygulamalar bir süre kullanılmazsa uyku moduna geçer; ilk ziyaret ~30 saniye
> sürebilir. Hızlı bir tur için Veri Toplama Aracı ile başlayın (ilçe seç →
> çek → haritayı incele), ardından Optimizasyon Aracı'nı açıp paketlenmiş
> örneklerden birini ya da kendi verinizi yükleyin.

## Bileşenler

| Streamlit sayfası | Amaç |
|---|---|
| `Spatial_Data_Collection_Tool.py` | Veri toplama uygulamasının ana sayfası |
| `pages/1_Data_Extraction.py` | İlçe + kategori seçimi → OSM extraction → Excel/CSV/GeoJSON export |
| `pages/2_Map_Visualization.py` | Sonuçların interaktif haritada gösterimi |
| `pages/3_Analytics_Dashboard.py` | KPI, mahalle dağılımı, güven dağılımı |
| `Optimization_Tool.py` | Deprem toplanma alanı atama + p-median |

| Backend modül | İçerik |
|---|---|
| `src/pipelines/pipeline.py` | OSM çekim + filtre + spatial enrich + classification akışı |
| `src/services/osm_service.py` | Overpass/Nominatim/OSMnx çağrıları, hata sınıfları |
| `src/services/spatial_service.py` | CRS, geometri temizleme, alan hesaplama, mahalle atama |
| `src/services/rule_engine.py` | Kural tabanlı sınıflandırma (strict/support/name/query_tag) |
| `src/services/post_filter.py` | Strict tag post-filter (Overpass union sızıntısı temizliği) |
| `src/services/excel_exporter.py` | Çok sayfalı stilize Excel raporu |
| `src/services/excel_utils.py` | Workbook stil katmanı (`build_styled_workbook`, `style_workbook`) |
| `src/optimizer/data_loader.py` | Excel/GeoJSON → bina + toplanma GDF |
| `src/optimizer/od_matrix.py` | OSMnx yürüyüş grafı + OD matrisi |
| `src/optimizer/p_median.py` | ILP (PuLP) ve Heuristic çözücüler |
| `src/config/settings.py` | Tüm sabitler tek noktadan (WALK_SPEED_KPH, AFAD_M2_PER_PERSON, vs.) |

## Hızlı Başlangıç (5 dakika)

**Gereksinim:** Python 3.10+ ve internet bağlantısı (OSM verisi için).

### Windows

```cmd
git clone https://github.com/istanbul-sdss/istanbul-sdss.git
cd istanbul-sdss
setup.bat
run_data_tool.bat
```

İkinci uygulama (atama optimizasyonu) için ayrı pencerede:

```cmd
run_optimizer.bat
```

### macOS / Linux

```bash
git clone https://github.com/istanbul-sdss/istanbul-sdss.git
cd istanbul-sdss
./setup.sh
./run_data_tool.sh
```

İkinci uygulama (atama optimizasyonu) için ayrı terminalde:

```bash
./run_optimizer.sh
```

> **İpucu:** İlk extraction Overpass API'den veri çekeceği için 1-3 dakika
> sürer. Hızlı denemek için **Kadıköy** ilçesi önerilir; alternatif olarak
> önceden hazırlanmış örnek veriler `data/samples/` klasöründedir —
> Optimization_Tool'a doğrudan yükleyebilirsiniz (extraction beklemeden
> harita + KPI + Excel rapor).

## Manuel Kurulum (script kullanmadan)

```bash
# Python 3.10+ gerekli
python -m venv venv
venv\Scripts\activate         # Windows
# source venv/bin/activate    # Linux/macOS

pip install -r requirements.txt
pip install -r requirements-dev.txt   # test/lint için (opsiyonel)

streamlit run Spatial_Data_Collection_Tool.py
# Optimizasyon için ayrı entry:
streamlit run Optimization_Tool.py --server.port 8502
```

### Reprodüksiyon (lock file ile birebir aynı sürümler)

`requirements.txt` aralıklı (`>=lower,<upper`) tutulduğu için iki kurulum
arasında alt paketler farklı patch/minor sürümlere düşebilir. Tezde aynı
sayıların üretilmesi, hocaların aynı çıktıyı görmesi ya da CI'da deterministik
build için **lock file** kullanın:

```bash
# Aralıklı yerine pinned kurulum (her paket tam sürüm)
pip install -r requirements.lock              # sadece runtime
pip install -r requirements-dev.lock          # runtime + test/lint
```

Lock dosyaları `pip-tools` (`pip install pip-tools` veya `requirements-dev.txt`
ile gelir) ile yenilenir:

```bash
python -m piptools compile --strip-extras \
    --output-file=requirements.lock requirements.txt
python -m piptools compile --strip-extras \
    --output-file=requirements-dev.lock requirements.txt requirements-dev.txt
```

Bir bağımlılığı bilinçli güncellemek için: önce `requirements.txt` veya
`requirements-dev.txt` üst sınırını oynat, sonra yukarıdaki iki komutu tekrar
çalıştır, sonuçtaki `.lock` farklarını review et, commit at.

## Kurulumun Doğrulanması

Kurulumdan sonra **iki dakikalık** bir doğrulama akışı:

1. **Test paketi geçiyor mu?** (Önce `requirements-dev.txt` kurulu olmalı —
   `pytest` runtime'da değil, dev bağımlılıklarında.)
   ```bash
   venv\Scripts\activate                       # Windows
   # source venv/bin/activate                  # Linux/macOS
   pip install -r requirements-dev.txt         # pytest + ruff + pre-commit
   python -m pytest tests/ -q
   ```
   Beklenen: **tüm testler geçer, 1 skip.** (Test sayısı geliştirme sürdükçe
   artar; sabit bir sayı yerine "fail/error olmaması" baseline'dır. Güncel sayım
   için: `python -m pytest tests/ --collect-only -q | tail -1`.)

2. **UI açılıyor mu?** `run_data_tool.bat`/`.sh` çalıştırın → tarayıcıda
   `http://localhost:8501` otomatik açılmalı, "Istanbul Spatial Decision
   Support System" başlığı görünmeli.

3. **Sample veri yükleniyor mu?** Ayrı pencerede `run_optimizer.bat`/`.sh` →
   "Excel" seçeneği → `data/samples/Kadıköy_OSM_sample.xlsx` → sayfaları seç
   (`Konut - Genel` + `Toplanma Alanı`) → ✅ Load. Beklenen: ~6,665 bina + 154
   toplanma alanı, ~244,000 kişi tahmini.

Üçü de geçiyorsa kurulum sağlamdır. Aksi halde aşağıdaki sorun giderme.

## Girdi Şablonları

Veri toplama aracının çıktısını kullanmıyorsanız kendi verinizi sağlayabilirsiniz.
Optimizasyon Aracı, *Adım 1 · Load data* altında ("📥 Need a template? Download
blank Excel") iki boş Excel şablonu sunar; aynı dosyalar [`templates/`](templates/)
klasöründe de commit'lidir, böylece doğrudan repodan indirebilirsiniz:

- `templates/Buildings_Assembly_template.xlsx` — binalar (talep noktaları) ve
  aday toplanma alanları.
- `templates/TUIK_Population_template.xlsx` — *Uniform per-building* yöntemi için
  mahalle nüfusu.

Her workbook'ta, tüm sütunları açıklayan bir `README` sayfası vardır. Başlıklar
İngilizce (`Latitude`, `Longitude`, `Neighbourhood`, `Area (m²)`, `Floors`, …) ve
yükleyici iki-dilli olduğu için doldurulmuş şablonlar yeniden adlandırmadan
yüklenir.

## Sorun Giderme

### Windows: "Microsoft Visual C++ 14.0 or greater is required"
GeoPandas/Shapely binary paketleri çoğu durumda hazır wheel ile gelir; bu hata
genelde Python 3.13+ veya çok eski pip versiyonlarında çıkar.
- **Çözüm 1:** `python -m pip install --upgrade pip wheel` sonra
  `pip install -r requirements.txt` tekrar.
- **Çözüm 2:** Python 3.11 veya 3.12 kullanın (3.10/3.11/3.12 CI'da
  doğrulanmıştır; 3.13 henüz değil).

### "ImportError: GDAL not found" / Fiona hatası
Windows'ta nadir; GeoPandas wheel'i bağımlılıkları kendisi taşır.
- `pip install --force-reinstall geopandas shapely fiona` deneyin.
- Hâlâ olmuyorsa Anaconda dağıtımı kullanın:
  `conda install -c conda-forge geopandas shapely`.

### "OverpassNetworkError: Tüm endpoint'ler başarısız"
İnternet yok ya da Overpass API geçici düşmüş. Sample veriyle
(`data/samples/Kadıköy_OSM_sample.xlsx`) çevrimdışı çalışılabilir; Veri Çıkartma
için bağlantı şart. Birkaç dakika sonra tekrar deneyin ya da
<https://overpass-api.de/api/status> durumunu kontrol edin.

### Streamlit sayfası tarayıcıda açılmıyor
- Komut satırında verilen URL'yi (`http://localhost:8501`) elle açın.
- Antivirüs / firewall localhost portunu engelleyebilir; istisna ekleyin.
- Aynı port zaten kullanımda olabilir (başka Streamlit oturumu);
  `--server.port 8503` gibi farklı port deneyin.

### Türkçe karakter sorunu (Windows console)
Logger UTF-8 wrapper kullanır; cp1254 console'da emoji'ler `?` olarak görünebilir
ama hata vermez. UI'da problem yok.

## Test

```bash
python -m pytest tests/
# Hızlı: belirli bir test dosyası
python -m pytest tests/test_category_leakage_audit.py -v
```

Kapsamlı bir regresyon test paketi mevcut (500+ test; güncel sayım için
`pytest --collect-only -q | tail -1`); push/PR'da `.github/workflows/ci.yml`
Python 3.10, 3.11 ve 3.12 matrisinde otomatik koşturur.

## Geliştirici Araçları

Repo'ya dahil ek araçlar (üretim akışına girmez):

- `analyze_outputs.py` — `output/` klasöründeki Excel çıktılarını gezerek ilçe
  başına son dosya için satır sayısı / boş kolon oranı denetimi yapar. Toplu
  regresyon (örn. yeni TAG_RULES değişikliklerinin tüm ilçelerde beklenen kayıt
  sayılarını koruyup korumadığı) için hızlı bir göz atma. Çalıştır:
  `python analyze_outputs.py`

## Üçüncü Şahsa Dağıtım (Geliştirici İçin)

Hocaya/danışmana göndermek için temiz ZIP üretmek:

```bash
python build_release.py --verify
# → dist/istanbul_sdss_<YYYYMMDD>.zip
```

Bu ZIP `venv/`, `cache/`, `output/`, `logs/`, `__pycache__/` gibi
yerel/üretilmiş klasörleri DAHİL ETMEZ. Alıcı taraf ZIP'i açıp
`setup.bat`/`setup.sh` çalıştırarak temiz ortamda kurabilir.

## Veri Kaynakları

- **OpenStreetMap (Overpass API)** — bina/POI verileri (lisans: ODbL). 3 mirror
  denemesi: `overpass-api.de` → `lz4.overpass-api.de` → `overpass.kumi.systems`.
- **Nominatim** — ilçe sınırı geocoding.
- **TÜİK** — nüfus tahmini için kişi başına alan varsayımı (6.25 m²/kişi).
- **AFAD** — toplanma alanı kapasite standardı (1.5 m²/kişi).

## Önemli Varsayımlar

| Varsayım | Değer | Yer |
|---|---|---|
| Yetişkin yürüyüş hızı | 4.8 km/h | `src/optimizer/od_matrix.py::WALK_SPEED_KPH` |
| AFAD m²/kişi | 1.5 m² | `src/services/spatial_service.py::AFAD_M2_PER_PERSON` |
| Bina kişi başı alan (TÜİK) | 6.25 m² | `src/optimizer/population_estimator.py` |
| ILP/Heuristic eşik | 5000 bina | `src/optimizer/p_median.py::ILP_THRESHOLD` |
| Toplanma alanı varsayılan | 1000 m² (kolon yoksa, Point geometry) | `data_loader.py::DEFAULT_AREA_FALLBACK_M2` |
| Walk graph cache versiyonu | v2 | `od_matrix.py::GRAPH_CACHE_VERSION` |

## Bilinen Kısıtlar

- OSM verisi gönüllü katkıyla oluşur — bazı binalarda `building:levels`, `name`,
  veya footprint poligonu eksik olabilir. `Data Quality` sayfası doluluk
  yüzdelerini gösterir.
- Overpass mirror'ları zaman zaman 504 dönebiliyor; tüm endpoint'ler düşerse
  `OverpassNetworkError` raise edilir (sessiz "veri yok"a dönüşmez).
- Heuristic büyük veri setlerinde (>5000 bina) ILP yerine kullanılır; optimallik
  garantisi yoktur ama lokal optima yakındır.
- Yürüyüş süresi tahminleri yatay; eğim/merdiven dikkate alınmaz.
- Mahalle atama: ilçe sınırına yakın ama dışındaki Point'lere `nearest` fallback
  ile en yakın mahalle atanır + log uyarısı verilir.

## Mühendislik Notları

Kod tabanı birkaç fazda sertleştirildi: geniş bir regresyon test paketi (500+
test, Python 3.10–3.12 CI matrisi + Streamlit smoke testi), `src/config/
settings.py`'da merkezîleştirilmiş sabitler, iki-dilli veri yükleyici, içerik
tabanlı cache, deterministik spatial join'ler, sertleştirilmiş hata yönetimi
(UI'a stack-trace sızıntısı yok), konsolide edilmiş Excel-stil katmanı ve
pre-commit + CI ile zorunlu kılınan `ruff` lint baseline'ı. Ayrıntılı değişiklik
kaydı için git geçmişine bakın.

## Lisans

**Kod: Apache License 2.0.** Bu projenin kaynak kodu Apache-2.0 altında
lisanslanmıştır (bkz. `LICENSE`). Serbestçe kullanılabilir, değiştirilebilir ve
dağıtılabilir; tek koşul telif/lisans bildirimlerinin korunması ve değiştirilen
dosyaların işaretlenmesidir. Apache-2.0 ayrıca katkıda bulunanlardan açık bir
patent lisansı içerir.

**Veri: kendi lisansları geçerli (Apache-2.0 kapsamı DIŞINDA).**
`data/mahalleleri/*.geojson` ve uygulamanın Overpass üzerinden çektiği tüm
OpenStreetMap verisi **© OpenStreetMap katkıcıları, ODbL v1.0** altındadır. Bu
veriden türetilen veritabanlarının dağıtımı koddan bağımsız olarak ODbL'e uymak
zorundadır. Ayrıntılar ve üçüncü-şahıs kütüphane atıfları için `NOTICE` dosyasına
bakın.
