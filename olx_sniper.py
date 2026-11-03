#!/usr/bin/env python3
"""
OLX.uz sniper: новые объявления аренды квартир в Юнусабадском районе -> Telegram.

pip install -r requirements.txt
Токен и chat_id кладутся в файл .env (см. .env.example).
"""
import json
import re
import sys
import os
import threading
import time
from datetime import datetime, timedelta, timezone
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
MAX_AGE_HOURS = 24        # старее — не слать (отсекает старые поднятые объявления). None = выкл
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


def age_hours(ad):
    try:
        t = datetime.fromisoformat(ad.get("created_time", ""))
        return (datetime.now(timezone.utc) - t).total_seconds() / 3600
    except Exception:
        return 0


def passes(ad) -> bool:
    if MAX_AGE_HOURS is not None and age_hours(ad) > MAX_AGE_HOURS:
        return False
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


PHONE_RE = re.compile(r"(?:\+?998[\s\-]?)?\(?\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}")


def find_phones(text: str):
    """Номера из текста объявления -> ['+998901234567', ...]"""
    out = []
    for m in PHONE_RE.findall(text or ""):
        d = re.sub(r"\D", "", m)
        if len(d) == 9:
            d = "998" + d
        if len(d) == 12 and d.startswith("998") and d not in out:
            out.append(d)
    return ["+" + d for d in out]


def fmt(ad) -> str:
    price = param(ad, "price").get("label", "—")
    rooms = param(ad, "number_of_rooms").get("label", "?")
    area = param(ad, "total_area").get("label", "?")
    floor = param(ad, "floor").get("label", "?")
    floors = param(ad, "total_floors").get("label", "?")
    furn = param(ad, "furnished").get("label", "")
    com = param(ad, "comission").get("label", "")
    seller = (ad.get("contact") or {}).get("name") or (ad.get("user") or {}).get("name") or ""
    phones = find_phones(" ".join([ad.get("title", ""), ad.get("description", ""), seller]))
    contact = ("📞 " + ", ".join(phones)) if phones else "📞 номер скрыт — кнопка «Показать телефон» на OLX"
    return (
        f"🏠 <b>{ad.get('title','')}</b>\n"
        f"💰 {price}\n"
        f"🚪 {rooms} | 📐 {area} | 🏢 {floor}/{floors}\n"
        + (f"🛋 {furn}\n" if furn else "")
        + (f"🤝 Комиссия: {com}\n" if com else "")
        + (f"👤 {seller}\n" if seller else "")
        + f"{contact}\n"
        + f"🕒 создано: {ad.get('created_time','')[:16].replace('T',' ')}"
        + (f" | поднято: {ad['last_refresh_time'][:16].replace('T',' ')}"
           if ad.get("last_refresh_time", "")[:16] not in ("", ad.get("created_time", "")[:16]) else "")
        + "\n"
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


STATS = {"seen": 0, "sent": 0, "last_check": "—", "started": time.strftime("%d.%m %H:%M")}


def commands_loop():
    """Отвечает на /start и /status в Telegram (long polling)."""
    offset = None
    while True:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"timeout": 30, "offset": offset}, timeout=40,
            ).json()
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                if str(msg.get("chat", {}).get("id")) != str(CHAT_ID):
                    continue
                if (msg.get("text") or "").split()[0:1] in (["/start"], ["/status"]):
                    send(
                        "✅ Снайпер работает\n"
                        f"Запущен: {STATS['started']}\n"
                        f"Последняя проверка: {STATS['last_check']}\n"
                        f"Объявлений в базе: {STATS['seen']}\n"
                        f"Отправлено новых: {STATS['sent']}\n"
                        f"Интервал: {INTERVAL} с"
                    )
        except Exception as e:
            log("[cmd err]", e)
            time.sleep(5)


def main():
    seen = load_seen()
    first_run = not seen
    log(f"[start] seen={len(seen)} first_run={first_run}")
    if not BOT_TOKEN or not CHAT_ID:
        log("[warn] BOT_TOKEN/CHAT_ID пустые — нет файла .env, объявления будут только в консоли")
    else:
        send(f"✅ OLX снайпер запущен, слежу за Юнусабадом (интервал {INTERVAL} с)\n/status — состояние")
        threading.Thread(target=commands_loop, daemon=True).start()
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
                STATS["sent"] += 1
                time.sleep(1)
            save_seen(seen)
            STATS["seen"] = len(seen)
            STATS["last_check"] = time.strftime("%H:%M:%S")
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
