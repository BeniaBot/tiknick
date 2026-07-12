@echo off
chcp 65001 >nul
cd /d "%~dp0"
pip install pywebview --quiet 2>nul
python main.py
