# Istanbul Spatial Decision Support System

Streamlit + GeoPandas + OSMnx tabanlı, İstanbul ilçeleri için OSM verisi
çeken, sınıflandıran ve AFAD toplanma alanı planlaması için **kapasite-farkında
P-Median optimizasyonu** çalıştıran karar destek aracı.

## Bileşenler

| Streamlit sayfası | Amaç |
|---|---|
| `Spatial_Data_Collection_Tool.py` | Veri toplama uygulamasının ana sayfası |
| `pages/1_Data_Extraction.py` | İlçe + kategori seçimi → OSM extraction → Excel/CSV/GeoJSON export |
| `pages/2_Map_Visualization.py` | Sonuçların interaktif haritada gösterimi |
| `pages/3_Analytics_Dashboard.py` | KPI, mahalle dağılımı, güven dağılımı |
| `Optimization_Tool.py` | Deprem toplanma alanı atama + P-Median |

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
| `src/optimizer/p_median.py` | ILP (PuLP) ve K-Medoids çözücüler |
| `src/config/settings.py` | Tüm sabitler tek noktadan (WALK_SPEED_KPH, AFAD_M2_PER_PERSON, vs.) |

## Hızlı Başlangıç (5 dakika)

**Gereksinim:** Python 3.10+ ve internet bağlantısı (OSM verisi için).

### Windows

```cmd
git clone https://github.com/<kullanıcı>/istanbul-sdss.git
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
git clone https://github.com/<kullanıcı>/istanbul-sdss.git
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

Lock dosyaları `pip-tools` (`pip install pip-tools` veya
`requirements-dev.txt`'ten gelir) ile yenilenir:

```bash
python -m piptools compile --strip-extras \
    --output-file=requirements.lock requirements.txt
python -m piptools compile --strip-extras \
    --output-file=requirements-dev.lock requirements.txt requirements-dev.txt
```

Bir bağımlılığı bilinçli güncellemek için: önce `requirements.txt` veya
`requirements-dev.txt` üst sınırını oynat, sonra yukarıdaki iki komutu
tekrar çalıştır, sonuçtaki `.lock` farklarını review et, commit at.

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
   artar; sabit bir sayı vermek yerine "fail/error olmaması" baseline'dır.
   Güncel sayım için: `python -m pytest tests/ --collect-only -q | tail -1`.)

2. **UI açılıyor mu?** `run_data_tool.bat`/`.sh` çalıştırın → tarayıcıda
   `http://localhost:8501` otomatik açılmalı, "Istanbul Spatial Decision
   Support System" başlığı görünmeli.

3. **Sample veri yükleniyor mu?** Ayrı pencerede `run_optimizer.bat`/`.sh`
   → "Excel" seçeneği → `data/samples/Kadıköy_OSM_sample.xlsx` →
   sayfaları seç (`Konut - Genel` + `Toplanma Alanı`) → ✅ Load.
   Beklenen: ~6,665 bina + 154 toplanma alanı, ~244,000 kişi tahmini.

Üçü de geçiyorsa kurulum sağlamdır. Aksi halde aşağıdaki sorun giderme.

## Sorun Giderme

### Windows: "Microsoft Visual C++ 14.0 or greater is required"
GeoPandas/Shapely binary paketleri çoğu durumda hazır wheel ile gelir; bu
hata genelde Python 3.13+ veya çok eski pip versiyonlarında çıkar.
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
(`data/samples/Kadıköy_OSM_sample.xlsx`) çevrimdışı çalışılabilir;
Veri Çıkartma için bağlantı şart. Birkaç dakika sonra tekrar deneyin
ya da https://overpass-api.de/api/status durumunu kontrol edin.

### Streamlit sayfası tarayıcıda açılmıyor
- Komut satırında verilen URL'yi (`http://localhost:8501`) elle açın.
- Antivirüs / firewall localhost portunu engelleyebilir; istisna ekleyin.
- Aynı port zaten kullanımda olabilir (başka Streamlit oturumu);
  `--server.port 8503` gibi farklı port deneyin.

### Türkçe karakter sorunu (Windows console)
Logger UTF-8 wrapper kullanır; cp1254 console'da emoji'ler `?` olarak
görünebilir ama hata vermez. UI'da problem yok.

## Test

```bash
python -m pytest tests/
# Hızlı: belirli bir test dosyası
python -m pytest tests/test_category_leakage_audit.py -v
```

Kapsamlı bir regresyon test paketi mevcut (güncel sayım için
`pytest --collect-only -q | tail -1`); push/PR'da
`.github/workflows/ci.yml` Python 3.10, 3.11 ve 3.12 matrisinde
otomatik koşturur.

## Geliştirici Araçları

Repo'ya dahil ek araçlar (üretim akışına girmez):

- `analyze_outputs.py` — `output/` klasöründeki Excel çıktılarını gezerek
  ilçe başına son dosya için satır sayısı / boş kolon oranı denetimi yapar.
  Toplu regresyon (örn. yeni TAG_RULES değişikliklerinin tüm ilçelerde
  beklenen kayıt sayılarını koruyup korumadığı) için hızlı bir göz atma.
  Çalıştır: `python analyze_outputs.py`

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

- **OpenStreetMap (Overpass API)** — bina/POI verileri (lisans: ODbL).
  3 mirror denemesi: `overpass-api.de` → `lz4.overpass-api.de` → `overpass.kumi.systems`.
- **Nominatim** — ilçe sınırı geocoding.
- **TÜİK** — nüfus tahmini için kişi başına alan varsayımı (6.25 m²/kişi).
- **AFAD** — toplanma alanı kapasite standardı (1.5 m²/kişi).

## Önemli Varsayımlar

| Varsayım | Değer | Yer |
|---|---|---|
| Yetişkin yürüyüş hızı | 4.8 km/h | `src/optimizer/od_matrix.py::WALK_SPEED_KPH` |
| AFAD m²/kişi | 1.5 m² | `src/services/spatial_service.py::AFAD_M2_PER_PERSON` |
| Bina kişi başı alan (TÜİK) | 6.25 m² | `src/optimizer/population_estimator.py` |
| ILP/K-Medoids eşik | 5000 bina | `src/optimizer/p_median.py::ILP_THRESHOLD` |
| Toplanma alanı varsayılan | 1000 m² (kolon yoksa, Point geometry) | `data_loader.py::DEFAULT_AREA_FALLBACK_M2` |
| Walk graph cache versiyonu | v2 | `od_matrix.py::GRAPH_CACHE_VERSION` |

## Bilinen Kısıtlar

- OSM verisi gönüllü katkıyla oluşur — bazı binalarda `building:levels`, `name`,
  veya footprint poligonu eksik olabilir. `Data Quality` sayfası doluluk
  yüzdelerini gösterir.
- Overpass mirror'ları zaman zaman 504 dönebiliyor; tüm endpoint'ler düşerse
  `OverpassNetworkError` raise edilir (sessiz "veri yok"a dönüşmez).
- K-Medoids büyük veri setlerinde (>5000 bina) ILP yerine kullanılır;
  optimallik garantisi yoktur ama lokal optima yakındır.
- Yürüyüş süresi tahminleri yatay; eğim/merdiven dikkate alınmaz.
- Mahalle atama: ilçe sınırına yakın ama dışındaki Point'lere `nearest`
  fallback ile en yakın mahalle atanır + log uyarısı verilir.

## Son Düzeltmelerin Özeti (kritik karar kalitesi)

- **P1.1 (cache v2):** Yürüyüş grafına araç hızı imputasyonu yerine sabit
  4.8 km/h. Eski cache (`*_walk.graphml`) artık otomatik bypass.
- **P1.2:** GeoJSON polygon yüklenirken centroid'e çevrilmeden önce gerçek
  alan UTM'de hesaplanır (eskiden 0/1000 m² varsayımına düşüyordu).
- **P2.1:** K-Medoids `min_max` (fairness) hedefini doğru optimize eder;
  metadata'ya `amac` doğru aktarılır.
- **P2.2:** `OverpassNetworkError` exception sınıfı + partial_failure flag
  ile network outage "veri yok"tan ayrılır.
- **P2.3:** Logger UTF-8 stream wrapper — Windows cp1254 console'da
  emoji/özel karakter mesajları artık `UnicodeEncodeError` üretmez.
- **P3.3:** `df_latlon_to_geodataframe` eksik kolonda açık `ValueError`,
  geçersiz koordinatlar (0,0) Atlantic Ocean fallback'i yerine düşürülür.

## Sertleştirme & Konsolidasyon (Faz 1-2)

- **Stack trace sızıntısı kapatıldı:** `pages/1_Data_Extraction.py` ve
  `pages/4_Name_Lookup.py` `st.exception()` kaldırıldı; tam traceback yalnızca
  log dosyasına yazılır, kullanıcıya kısa mesaj gösterilir.
- **Session ID UUID:** `Optimization_Tool.py`'da Streamlit private API
  (`st.runtime.scriptrunner`) bağımlılığı kaldırıldı; upload temp dosyaları
  artık `uuid.uuid4()` ile session başına benzersizleştirilir.
- **Folium popup escape merkezi helper:** `components/map_builder.safe_field`
  ve `safe_hex_color` üç dosyadan (map_builder, map_renderer, Optimization_Tool)
  ortak çağrılır — XSS/CSS injection tek noktadan korunur.
- **Polygon overlay determinizmi:** `spatial_service.py` aynı alana sahip
  birden fazla kapsayıcı polygon varsa stabil `__poly_id__` ile sıralanır;
  Excel çıktısı sjoin batch sırasından bağımsız.
- **Excel builder konsolidasyonu:** Üç sayfanın aynı stil pattern'i
  `src/services/excel_utils.py`'a çekildi (`build_styled_workbook`,
  `style_workbook`); ~150 satır kopya kod elendi.
- **Sabit konsolidasyonu:** `AFAD_M2_PER_PERSON`, `DEFAULT_AREA_FALLBACK_M2`
  artık yalnızca `src/config/settings.py`'da; modüller alias ile import eder.
- **Test kapsamı:** 207 → 220 → **294** test (13 `test_excel_styling.py` +
  12 `test_df_content_hash.py` + 3 `test_streamlit_smoke.py` + diğer
  birim eklemeleri).
- **Dağıtım altyapısı:** `.streamlit/config.toml` (theme + upload limit + telemetry off)
  ve `.github/workflows/ci.yml` (Python 3.10/3.11/3.12 matrisinde pytest + smoke import).

## Sertleştirme & Tooling (Faz A — bitti)

Son bir tur sertleştirme + güvenlik ağı yatırımı:

- **Bug fix paketi:**
  - **H1** Plotly `ImportError` fallback'inde tanımsız değişken (`NameError`)
    riski — `thresholds`/`values` `try` öncesi tanımlandı.
  - **H2** Kapasite OFF iken reachability ön-uyarısı atlanıyordu;
    `_check_capacity_feasibility` iki kontrolü ayırdı.
  - **H3** Excel/CSV bytes cache `id(df)` yerine `pd.util.hash_pandas_object`
    içerik tabanlı hash; GC reuse riski elendi. `src/utils.py` altında
    `df_content_hash` / `nonempty_signature` ortaklaştı.
  - **H4** `_generate_building_labels` aşırı defansif `get_loc` kaldırıldı.
  - **H5** Eski sürüm graf cache (`*_walk_v<N<güncel>.graphml`, 50-300 MB)
    `_prune_stale_graph_caches` ile otomatik temizleniyor.
  - **H6** pyproj 3.7 + numpy 2 + geopandas 1.1 `DeprecationWarning`
    (tek-noktalı `to_crs`) üç katmanda bastırıldı (runtime: `src/logger.py`;
    test: `pytest.ini`). 38 test uyarısı → 0.
  - **Q4** `src/analysis/__init__.py` `risk_score` modülünü import etmeye
    çalışıyordu ama dosya yoktu — kırık paket tamamen silindi.
- **Yan kazançlar:** `chosen_tier` dead code (name_lookup_service.py),
  `test_neighbourhood_population_override.py` case-insensitive senaryosunda
  eksik assertion, iki dosyada docstring/import sırası karışıklığı.
- **Lint baseline:** `ruff` (E, W, F, I, B, UP, C4, SIM) — pyproject.toml'da
  gerekçeli ignore listesi ile **0 aktif hata**; CI'da ayrı `lint` job.
  `.pre-commit-config.yaml` ile commit öncesi otomatik.
- **AppTest smoke:** `tests/test_streamlit_smoke.py` ile Home + Optimization
  sayfaları her CI koşusunda baştan-sona render kontrolü (sample veri
  yüklü versiyon dahil).

## Lisans

Geliştirme aşamasındaki proje. Kullanılan veri kaynaklarının lisanslarına
(ODbL, vb.) uyulması gerekir.
