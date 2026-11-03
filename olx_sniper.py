#!/usr/bin/env python3
"""
OLX.uz sniper: новые объявления аренды квартир в Юнусабадском районе -> Telegram.

pip install -r requirements.txt
Токен и chat_id кладутся в файл .env (см. .env.example).
"""
import json
import sys
import os
import time
from pathlib import Path

import requests

# подхватываем .env рядом со скриптом (без внешних зависимостей)
_env = Path(__file__).with_name(".env")
if _env.exists():
    for _line in _env.read_text().splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

CATEGORY_ID = 2155        # аренда квартир (долгосрочно). 2156 — второй подтип аренды (вероятно посуточно)
CITY_ID = 4               # Ташкент
REGION_ID = 5
DISTRICT_ID = 25          # Юнусабадский район

PRICE_MIN = None          # например 300  (в валюте объявления)
PRICE_MAX = None          # например 700
ROOMS = None              # например {1, 2} или None = любые
KEYWORDS_EXCLUDE = ["офис", "ofis", "нежил", "noturar"]  # отсекать мусор по заголовку

INTERVAL = 20             # сек между проверками (меньше 10 — риск бана от OLX)
PAGES = 2                 # сколько страниц по 40 смотреть за проход
SEEN_FILE = Path(__file__).with_name("olx_seen.json")
# ===============================================

sys.stdout.reconfigure(line_buffering=True)  # лог сразу, даже при выводе в файл


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)

API = "https://www.olx.uz/api/v1/offers/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "ru",
}


def load_seen() -> set:
    try:
        return set(json.loads(SEEN_FILE.read_text()))
    except Exception:
        return set()


def save_seen(seen: set):
    SEEN_FILE.write_text(json.dumps(list(seen)[-5000:]))


def param(ad, key):
    for p in ad.get("params", []):
        if p.get("key") == key:
            return p.get("value") or {}
    return {}


def fetch_ads():
    ads = []
    for page in range(PAGES):
        r = requests.get(API, headers=HEADERS, timeout=20, params={
            "offset": page * 40, "limit": 40,
            "category_id": CATEGORY_ID, "region_id": REGION_ID,
            "city_id": CITY_ID, "district_id": DISTRICT_ID,
            "sort_by": "created_at:desc",
        })
        if r.status_code != 200:
            raise RuntimeError(f"OLX ответил {r.status_code} (возможно бан за частые запросы)")
        ads += r.json().get("data", [])
    return ads


def passes(ad) -> bool:
    title = ad.get("title", "").lower()
    if any(k in title for k in KEYWORDS_EXCLUDE):
        return False
    price = param(ad, "price").get("value")
    if PRICE_MIN is not None and (price is None or price < PRICE_MIN):
        return False
    if PRICE_MAX is not None and (price is None or price > PRICE_MAX):
        return False
    if ROOMS:
        try:
            rooms = int(param(ad, "number_of_rooms").get("key", 0))
        except (TypeError, ValueError):
            rooms = 0
        if rooms not in ROOMS:
            return False
    return True


def fmt(ad) -> str:
    price = param(ad, "price").get("label", "—")
    rooms = param(ad, "number_of_rooms").get("label", "?")
    area = param(ad, "total_area").get("label", "?")
    floor = param(ad, "floor").get("label", "?")
    floors = param(ad, "total_floors").get("label", "?")
    furn = param(ad, "furnished").get("label", "")
    com = param(ad, "comission").get("label", "")
    return (
        f"🏠 <b>{ad.get('title','')}</b>\n"
        f"💰 {price}\n"
        f"🚪 {rooms} | 📐 {area} | 🏢 {floor}/{floors}\n"
        + (f"🛋 {furn}\n" if furn else "")
        + (f"🤝 Комиссия: {com}\n" if com else "")
        + f"🕒 {ad.get('created_time','')[:16].replace('T',' ')}\n"
        f"{ad.get('url','')}"
    )


def send(text):
    if not BOT_TOKEN or not CHAT_ID:
        print(text, "\n")
        return
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": False},
        timeout=20,
    )
    if not r.ok:
        log("[tg err]", r.status_code, r.text[:200])


def main():
    seen = load_seen()
    first_run = not seen
    log(f"[start] seen={len(seen)} first_run={first_run}")
    while True:
        try:
            new = 0
            for ad in reversed(fetch_ads()):
                aid = ad["id"]
                if aid in seen:
                    continue
                seen.add(aid)
                if first_run or not passes(ad):
                    continue
                send(fmt(ad))
                new += 1
                time.sleep(1)
            save_seen(seen)
            if first_run:
                log(f"[init] запомнил {len(seen)} текущих объявлений, жду новые")
                first_run = False
            else:
                log(f"[check] новых: {new}, всего видел: {len(seen)}")
        except Exception as e:
            log("[err]", e)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
