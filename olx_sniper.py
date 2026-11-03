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
import random
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
MAX_AGE_HOURS = 24        # старее этого = «поднятое», а не новое
SEND_BUMPED = True        # True — поднятые тоже слать с пометкой ♻️, False — пропускать
KEYWORDS_EXCLUDE = ["офис", "ofis", "нежил", "noturar"]  # отсекать мусор по заголовку

INTERVAL = 4              # базовая пауза, сек (+ случайно 0–2 с). Меньше 3 не ставить
PAGES = 1                 # 1 страница (40 свежих) — хватает при частых проверках
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


SESSION = requests.Session()   # одно keep-alive соединение вместо нового на каждый запрос
SESSION.headers.update(HEADERS)


class RateLimited(Exception):
    pass


def fetch_ads():
    ads = []
    for page in range(PAGES):
        r = SESSION.get(API, timeout=20, params={
            "offset": page * 40, "limit": 40,
            "category_id": CATEGORY_ID, "region_id": REGION_ID,
            "city_id": CITY_ID, "district_id": DISTRICT_ID,
            "sort_by": "created_at:desc",
        })
        if r.status_code in (403, 429):
            raise RateLimited(r.status_code)
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


def is_bumped(ad) -> bool:
    return MAX_AGE_HOURS is not None and age_hours(ad) > MAX_AGE_HOURS


def skip_reason(ad):
    """None = подходит, иначе причина пропуска."""
    if not SEND_BUMPED and is_bumped(ad):
        return f"старое ({ad.get('created_time','')[:10]}, поднято)"
    title = ad.get("title", "").lower()
    for k in KEYWORDS_EXCLUDE:
        if k in title:
            return f"стоп-слово «{k}»"
    price = param(ad, "price").get("value")
    if PRICE_MIN is not None and (price is None or price < PRICE_MIN):
        return f"цена {price} < {PRICE_MIN}"
    if PRICE_MAX is not None and (price is None or price > PRICE_MAX):
        return f"цена {price} > {PRICE_MAX}"
    if ROOMS:
        try:
            rooms = int(param(ad, "number_of_rooms").get("key", 0))
        except (TypeError, ValueError):
            rooms = 0
        if rooms not in ROOMS:
            return f"комнат {rooms}"
    return None


def passes(ad) -> bool:
    return skip_reason(ad) is None


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
    if is_bumped(ad):
        days = int(age_hours(ad) // 24)
        head = f"♻️ <b>ПОДНЯТОЕ</b> — висит уже {days} дн., не новое\n"
    else:
        head = "🆕 <b>НОВОЕ</b>\n"
    return (
        head
        + f"🏠 <b>{ad.get('title','')}</b>\n"
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
    backoff = 0
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
                if first_run:
                    continue
                why = skip_reason(ad)
                if why:
                    log(f"[skip] {why}: {ad.get('title','')[:60]}")
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
            elif new:
                log(f"[check] новых: {new}, всего видел: {len(seen)}")
            checks = STATS.get("checks", 0) + 1
            STATS["checks"] = checks
            if checks % 50 == 0:
                log(f"[alive] проверок: {checks}, всего видел: {len(seen)}")
            backoff = 0
        except RateLimited as e:
            backoff = min(backoff * 2 or 60, 900)
            log(f"[ratelimit] OLX ответил {e}, пауза {backoff} с")
            time.sleep(backoff)
            continue
        except Exception as e:
            log("[err]", e)
        time.sleep(INTERVAL + random.uniform(0, 2))


if __name__ == "__main__":
    main()
