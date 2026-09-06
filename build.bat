@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Building Tik-Nick.exe
echo ============================================
echo.
echo [1/3] Installing build tools (one-time)...
pip install pyinstaller pywebview pillow --quiet
echo.
rem Version flows one way: main.py APP_VERSION -> version_info.txt + installer.iss
python tools\sync_version.py
echo.
echo [2/3] Cleaning old builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo.
echo [3/3] Building single-file EXE (with icon)...
pyinstaller --noconfirm --clean TikNick.spec
echo.
if exist "dist\TikNick.exe" (
    echo ============================================
    echo   SUCCESS!  ^>^>  dist\TikNick.exe
    echo ============================================
    echo   Copy that single file anywhere and run it.
) else (
    echo BUILD FAILED - check the messages above.
)
echo.
pause
