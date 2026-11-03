# OLXsniper

Следит за новыми объявлениями аренды квартир на OLX.uz (Ташкент, Юнусабадский район) и присылает их в Telegram.

## Установка
```bash
git clone https://github.com/Garricho/olx.git
cd olx
pip install -r requirements.txt
cp .env.example .env   # вписать BOT_TOKEN и CHAT_ID
```

## Запуск
```bash
screen -dmS olxsniper python3 olx_sniper.py
```

Первый проход только запоминает текущие объявления, дальше приходят только новые.

## Настройки (в начале olx_sniper.py)
- `CATEGORY_ID` — 2155 аренда квартир (долгосрочно)
- `CITY_ID=4` Ташкент, `DISTRICT_ID=25` Юнусабадский район
- `PRICE_MIN` / `PRICE_MAX`, `ROOMS`, `KEYWORDS_EXCLUDE`
- `INTERVAL` — пауза между проверками, сек
