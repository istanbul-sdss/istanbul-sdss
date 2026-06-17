@echo off
REM Istanbul SDSS — Windows kurulum scripti.
REM Tek seferlik: virtualenv kurar, bagimliliklari yukler.

echo ================================================================
echo  Istanbul SDSS - Windows Setup
echo ================================================================
echo.

REM Python yorumlayicisini bul: once "python", olmazsa "py" launcher.
REM Windows'ta Python cogu zaman "py" ile gelir ama "python" PATH'te olmayabilir.
REM Parantez bloklarinda errorlevel donabildigi icin duz akis + goto kullaniyoruz.
set "PYCMD="
python --version >nul 2>&1
if not errorlevel 1 (set "PYCMD=python" & goto :pyfound)
py -3 --version >nul 2>&1
if not errorlevel 1 (set "PYCMD=py -3" & goto :pyfound)
py --version >nul 2>&1
if not errorlevel 1 (set "PYCMD=py" & goto :pyfound)

if not defined PYCMD (
    echo [HATA] Python bulunamadi.
    echo.
    echo  Python kurulu olabilir ama PATH'te olmayabilir. Lutfen kontrol edin:
    echo     py --version
    echo     python --version
    echo.
    echo  Python yuklu degilse 3.11 veya 3.12 yukleyin ^(3.13 ONERILMEZ^):
    echo     https://www.python.org/downloads/
    echo  Kurulumda "Add Python to PATH" secenegini MUTLAKA isaretleyin.
    pause
    exit /b 1
)

:pyfound

echo  Python komutu: %PYCMD%

REM Sys.version_info ile minimum 3.10 dogrula
%PYCMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
    for /f "tokens=2" %%v in ('%PYCMD% --version 2^>^&1') do set "PYV=%%v"
    echo [HATA] Python surumu yetersiz: %PYV%
    echo        En az Python 3.10 gereklidir ^(3.11 veya 3.12 onerilir^).
    echo        https://www.python.org/downloads/
    pause
    exit /b 1
)

REM venv yoksa olustur
if not exist "venv\" (
    echo [1/2] Sanal ortam olusturuluyor...
    %PYCMD% -m venv venv
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
