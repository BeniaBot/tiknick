@echo off
chcp 65001 >nul
cd /d "%~dp0"
python testsun_all.py
pause
