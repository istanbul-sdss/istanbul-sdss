@echo off
REM Veri Cikartma araci - Streamlit ana sayfa.
REM Otomatik olarak tarayicida acilir (varsayilan: http://localhost:8501).

if not exist "venv\Scripts\activate.bat" (
    echo [HATA] venv yok. Once setup.bat calistirin.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
streamlit run Spatial_Data_Collection_Tool.py
