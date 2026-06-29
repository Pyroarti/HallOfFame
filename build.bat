@echo off

echo.
echo [1/3] Kontrollerar PyInstaller...
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo PyInstaller saknas — installerar...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo.
        echo FEL: kunde inte installera PyInstaller.
        pause
        exit /b 1
    )
)

echo.
echo [2/3] Rensar gamla byggen...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo [3/3] Bygger...
python -m PyInstaller hall_of_fame.spec
if errorlevel 1 (
    echo.
    echo FEL: bygget misslyckades — se output ovan.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  KLART! Exe:n ligger i:  dist\hall_of_fame\hall_of_fame.exe
echo ============================================================
echo.
pause
