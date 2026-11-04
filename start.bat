@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
    py -3 -m venv .venv || python -m venv .venv
    .venv\Scripts\python -m pip install -U pip
    .venv\Scripts\python -m pip install -r requirements.txt
)
if not exist .env (
    echo [!] Нет файла .env — скопируй .env.example в .env и впиши BOT_TOKEN/CHAT_ID
    pause
    exit /b 1
)
.venv\Scripts\python olx_sniper.py
pause
