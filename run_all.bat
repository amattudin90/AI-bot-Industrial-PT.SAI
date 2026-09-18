@echo off
title Factory AI - Dual Runner

echo ===================================================
echo   Memulai Factory AI Operations System...
echo ===================================================
echo.

:: Menjalankan Streamlit di jendela terminal terpisah
start "Factory AI - Streamlit Dashboard" cmd /k ".\.venv\Scripts\activate && streamlit run app.py"

:: Menjalankan Bot Telegram di jendela terminal aktif saat ini
echo Menjalankan Telegram Bot Agent...
echo.
.\.venv\Scripts\activate && python bot.py

pause
