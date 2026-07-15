@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo    Tik-Nick  --  GitHub Upload
echo ============================================
echo.
rem --- Git identity (one-time) ---
git config --global user.email "b0554003794@gmail.com"
git config --global user.name "BeniaBot"
echo Identity set.
echo.
rem --- remove any old git ---
if exist .git rmdir /s /q .git
rem --- init and add ONLY the right files (.gitignore protects the rest) ---
git init
git add .
git commit -m "Tik-Nick v0.1 initial release"
git branch -M main
git remote add origin https://github.com/b0554003794-alt/tiknick.git
echo.
echo ============================================
echo   Pushing to GitHub...
echo   (A browser/login window may appear -- sign in)
echo ============================================
git push -u origin main
echo.
echo ============================================
echo   Done! Check: github.com/b0554003794-alt/tiknick
echo ============================================
pause
