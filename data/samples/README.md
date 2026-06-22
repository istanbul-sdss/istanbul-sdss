# Sample Veri — Hızlı Demo

Bu klasördeki dosyalar, Veri Çıkartma aracını çalıştırmadan
**Optimization_Tool**'u doğrudan denemek için pre-bundled örneklerdir.

## Kadıköy_OSM_sample.xlsx

İstanbul Kadıköy ilçesi için OSM'den çekilmiş veri (~Nisan 2026):

| Sayfa | Kayıt | İçerik |
|---|---|---|
| `Konut - Genel` | 6,665 bina | Konut yapıları (residential), ana optimizasyon girdisi |
| `Toplanma Alanı` | 154 alan | OSM `emergency=assembly_point` + benzer etiketli alanlar |

Beklenen sonuç (default ayarlarla):
- Toplam tahmini nüfus: ~244,000 kişi
- Toplam toplanma kapasitesi: ~656,000 kişi (AFAD 1.5 m²/kişi)
- ILP ile çözülebilir (≤ 5,000 bina değil ama Heuristic fallback ile pratik)

## Kullanım

1. **Optimization_Tool'u başlat**: `run_optimizer.bat` veya `run_optimizer.sh`
2. **Step 1 — Load data** sekmesinde:
   - Data source: `Excel (from Data Extraction tool)` seç
   - Yüklenecek dosya: `data/samples/Kadıköy_OSM_sample.xlsx`
   - Buildings sheet: **Konut - Genel**
   - Assembly areas sheet: **Toplanma Alanı**
   - **✅ Load** tuşuna bas
3. **Step 2 — OD matrix**: District = `Kadıköy`, Maximum walking time = 30 dk
   - 🚀 Compute OD matrix (~1-2 dakika; ilk çalıştırmada Overpass'tan
     Kadıköy yürüme ağı çekilir, sonraki çalıştırmalarda cache'tendir)
4. **Step 3 — Optimize**: p = 5-10, Objective = "Robust fairness (p95)"
   - 🚀 Run optimization
5. **Step 4 — Results**: KPI'lar, harita, atama tablosu, Excel export

## Notlar

- Bu örnek **hocaya/danışmana arayüzü göstermek** için hızlı yol; gerçek
  karar destek için Veri Çıkartma aracını çalıştırıp güncel veri çekmek
  önerilir (OSM her gün güncellenir).
- Excel'in iç şeması Veri Çıkartma aracının çıktısı ile birebir uyumludur.
  Kullanıcı kendi Excel'ini de aynı yapıyla üretip yükleyebilir.
- Sample dosya boyutu ~620 KB; ilk açılışta Toplanma Alanı sayfasının
  m² kolonu eksik olduğu için sistem **1000 m² varsayımı + AFAD standardı**
  uygulayacak (UI'da uyarı banner'ı görünür) — gerçek polygon alanları
  için Veri Çıkartma aracında ilgili kategoriler birlikte çekilmelidir.
