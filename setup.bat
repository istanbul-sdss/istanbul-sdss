@echo off
REM Istanbul SDSS — Windows kurulum scripti.
REM Tek seferlik: virtualenv kurar, bagimliliklari yukler.

echo ================================================================
echo  Istanbul SDSS - Windows Setup
echo ================================================================
echo.

REM Python 3.10+ kontrolu - gercek surum karsilastirmasi
python --version >nul 2>&1
if errorlevel 1 (
    echo [HATA] Python bulunamadi. Lutfen Python 3.10 veya ustu yukleyin:
    echo        https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Sys.version_info ile minimum 3.10 dogrula
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
    for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYV=%%v"
    echo [HATA] Python surumu yetersiz: %PYV%
    echo        En az Python 3.10 gereklidir. Yeni surum: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM venv yoksa olustur
if not exist "venv\" (
    echo [1/2] Sanal ortam olusturuluyor...
    python -m venv venv
    if errorlevel 1 (
        echo [HATA] venv olusturulamadi.
        pause
        exit /b 1
    )
) else (
    echo [1/2] Sanal ortam zaten mevcut, atlandi.
)

REM Bagimliliklari yukle
echo [2/2] Bagimliliklar yukleniyor (birkac dakika surebilir)...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt
if errorlevel 1 (
    echo [HATA] Bagimlilik yuklemesi basarisiz oldu.
    pause
    exit /b 1
)

echo.
echo ================================================================
echo  Kurulum tamamlandi.
echo  Calistirmak icin:
echo    run_data_tool.bat        (Veri Cikartma araci - ana sayfa)
echo    run_optimizer.bat        (Toplanma alani optimizasyonu)
echo ================================================================
pause
