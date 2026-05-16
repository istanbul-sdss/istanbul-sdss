"""
Çıktı kalite analizi — output/ klasöründeki Excel dosyalarını denetler.
Çalıştır: python analyze_outputs.py
"""
from pathlib import Path

import pandas as pd

output_dir = Path("output")

# İlçe başına en son dosyayı al
latest = {}
for f in sorted(output_dir.glob("*.xlsx")):
    ilce = f.name.split("_OSM_")[0]
    latest[ilce] = f   # sıralı olduğu için son dosya kalır

print(f"\nAnaliz edilecek dosyalar: {len(latest)}")
for ilce, fpath in latest.items():
    print(f"  {ilce}: {fpath.name}")

SKIP_SHEETS = {"Özet", "Mahalle Özeti", "Veri Kalitesi"}

grand_total = 0
issues = []

for ilce, fpath in latest.items():
    xl = pd.ExcelFile(fpath)
    sheets = [s for s in xl.sheet_names
              if not any(skip in s for skip in SKIP_SHEETS)]

    print(f"\n{'='*65}")
    print(f"  {ilce}  |  {len(sheets)} kategori  |  {fpath.name}")
    print(f"{'='*65}")

    ilce_total = 0
    for sheet in sheets:
        try:
            df = pd.read_excel(fpath, sheet_name=sheet, header=1)
        except Exception as e:
            print(f"  HATA  {sheet}: {e}")
            continue
        if df.empty or len(df) < 2:
            continue

        ilce_total += len(df)
        cols = df.columns.tolist()

        # Default-arg capture (B023): `cols` ve `df` loop değişkenleri olduğu
        # için closure ile sonradan kullansak yanlış iterasyona bağlanırdı —
        # senkron çağrı ama best-practice gereği bind ediyoruz.
        def find_col(*keywords, _cols=cols):
            for c in _cols:
                if all(k.lower() in str(c).lower() for k in keywords):
                    return c
            return None

        def fill_pct(col, _df=df):
            if col is None: return 0
            return round(_df[col].notna().mean() * 100)

        mah_col  = find_col("ahalle")
        lat_col  = find_col("nlem")
        lon_col  = find_col("oylam")
        alan_col = find_col("lan")
        kat_col  = find_col("at s")
        guv_col  = find_col("ven")

        mah_pct  = fill_pct(mah_col)
        lat_pct  = fill_pct(lat_col)
        alan_pct = fill_pct(alan_col)
        kat_pct  = fill_pct(kat_col)

        # Koordinat anomalisi (Istanbul dışı)
        anomali = 0
        if lat_col and lon_col:
            valid = (
                df[lat_col].between(40.5, 42.0) &
                df[lon_col].between(28.0, 30.5)
            )
            anomali = int((~valid & df[lat_col].notna()).sum())

        # Güven dağılımı
        guven_str = ""
        if guv_col:
            gd = df[guv_col].value_counts().to_dict()
            guven_str = " | ".join(
                f"{k}:{v}" for k, v in sorted(gd.items(), key=lambda x: -x[1])
            )

        name = sheet.replace("📍 ", "").strip()
        f_m = "WARN" if mah_pct  < 80 else "  OK"
        f_l = "WARN" if lat_pct  < 80 else "  OK"
        f_a = "WARN" if alan_pct < 20 else "  OK"

        print(f"\n  [{len(df):>5} kayit]  {name}")
        print(f"    Mah:{f_m} %{mah_pct:<3}  Koor:{f_l} %{lat_pct:<3}  Alan:{f_a} %{alan_pct:<3}  Kat:%{kat_pct}")
        if guven_str:
            print(f"    Guven -> {guven_str}")
        if anomali > 0:
            print(f"    !!! KOORDINAT ANOMALiSi: {anomali} kayit Istanbul disinda")
            issues.append(f"{ilce}/{name}: {anomali} anomali koordinat")

        # Düşük mahalle oranı kaydet
        if mah_pct < 80:
            issues.append(f"{ilce}/{name}: mahalle %{mah_pct} (dusuk)")
        if lat_pct < 80:
            issues.append(f"{ilce}/{name}: koordinat %{lat_pct} (dusuk)")

    print(f"\n  TOPLAM: {ilce_total:,} kayit")
    grand_total += ilce_total

print(f"\n{'='*65}")
print(f"GENEL TOPLAM: {grand_total:,} kayit, {len(latest)} ilce")
print(f"{'='*65}")

if issues:
    print(f"\n*** {len(issues)} SORUN TESPIT EDILDI ***")
    for iss in issues:
        print(f"  - {iss}")
else:
    print("\nSorun tespit edilmedi.")
