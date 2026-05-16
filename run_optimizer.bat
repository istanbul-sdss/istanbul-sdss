@echo off
REM Toplanma alani optimizasyonu - ayri Streamlit uygulamasi.
REM Veri Cikartma aracinin ayni anda calismasi icin farkli port (8502) kullanir.

if not exist "venv\Scripts\activate.bat" (
    echo [HATA] venv yok. Once setup.bat calistirin.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
streamlit run Optimization_Tool.py --server.port 8502
