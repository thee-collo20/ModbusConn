@echo off
setlocal

pip install pymodbus pyinstaller
if errorlevel 1 (
    echo Dependency installation failed.
    exit /b 1
)

pyinstaller --onefile --noconsole main.py
if errorlevel 1 (
    echo PyInstaller build failed.
    exit /b 1
)

echo Build complete: dist\main.exe
endlocal
