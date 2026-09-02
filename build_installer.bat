@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Building Tik-Nick installer (Setup.exe)
echo ============================================
echo.

rem [1/2] Ensure the portable EXE exists (build it if missing)
if not exist "dist\TikNick.exe" (
    echo dist\TikNick.exe not found - running build.bat first...
    call build.bat
)
if not exist "dist\TikNick.exe" (
    echo BUILD FAILED - dist\TikNick.exe is missing. Aborting.
    pause
    exit /b 1
)

rem [2/2] Compile the installer with Inno Setup
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo Inno Setup 6 not found. Install it from https://jrsoftware.org/isdl.php
    echo Then re-run this script.
    pause
    exit /b 1
)

"%ISCC%" installer.iss
echo.
if exist "dist\TikNick-Setup.exe" (
    echo ============================================
    echo   SUCCESS!  ^>^>  dist\TikNick-Setup.exe
    echo ============================================
) else (
    echo INSTALLER BUILD FAILED - check the messages above.
)
echo.
pause
