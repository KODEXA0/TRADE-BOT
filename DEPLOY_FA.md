# 🚀 راه‌اندازی روی هاست پایتونی با ترمینال Bash (بدون خرید دامنه/سرور)

خبر خوب: کد پروژه از قبل دقیقاً همین‌طور طراحی شده — در `main.py`، ربات تلگرام و پنل ادمین تحت وب (FastAPI/uvicorn)
و Worker هشدارها هر سه **در یک پروسه پایتون** با هم اجرا می‌شوند. پس نیازی به سرویس جدا، دامنه، یا سرور اضافه نیست؛
فقط کافیست همین فایل‌ها را روی هاستی که ترمینال اوبونتو/bash دارد اجرا کنید.

## ۱) آپلود فایل‌ها

فایل‌های داخل پوشه `tradebot/` را روی هاست آپلود کنید (از طریق SFTP، File Manager هاست، یا `git clone` اگر ریپو دارید).
فرض می‌کنیم مسیر نهایی چیزی شبیه `/home/user/tradebot` است.

```bash
cd ~/tradebot
```

## ۲) ساخت محیط مجازی و نصب پکیج‌ها

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

> اگر هاست چند نسخه پایتون دارد و `python3` کار نکرد، `python3.11` یا نسخه‌ای که هاست پیشنهاد می‌دهد را امتحان کنید.

## ۳) تنظیم فایل `.env`

```bash
cp .env.example .env
nano .env   # یا vi .env
```

حداقل این مقادیر را پر کنید:

| متغیر | توضیح |
|---|---|
| `BOT_TOKEN` | از @BotFather در تلگرام بگیرید |
| `ADMIN_IDS` | آیدی عددی تلگرام خودتان (از @userinfobot بگیرید) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | یوزر/پسورد ورود به پنل وب — حتماً از مقدار پیش‌فرض تغییرش بدهید |
| `SESSION_SECRET` | یک رشته تصادفی طولانی؛ می‌توانید با دستور زیر بسازید: |

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

مقدار خروجی را داخل `SESSION_SECRET` بگذارید.

`ADMIN_PANEL_HOST` و `ADMIN_PANEL_PORT` را دست نخورده (`0.0.0.0` و `8000`) رها کنید مگر هاست پورت دیگری بدهد.

## ۴) اجرای آزمایشی (Foreground)

```bash
python main.py
```

اگر همه‌چیز درست باشد دو خط لاگ می‌بینید: یکی برای Bot Polling و یکی برای Admin Panel روی پورت 8000.
با `Ctrl+C` متوقف کنید و برو سراغ اجرای دائمی.

## ۵) اجرای دائمی در پس‌زمینه (بدون قطع شدن با بستن SSH)

چون روی هاستی هستید که فقط ترمینال Bash دارید (نه پنل مدیریت پروسه)، از `tmux` یا `nohup` استفاده کنید:

### روش پیشنهادی: tmux
```bash
tmux new -s tradebot
source venv/bin/activate
python main.py
# سپس Ctrl+B و بعد D بزنید تا از session خارج شوید بدون کشتن پروسه
```
برای برگشت به لاگ‌ها بعداً: `tmux attach -t tradebot`

### روش جایگزین: nohup
```bash
source venv/bin/activate
nohup python main.py > bot.log 2>&1 &
```
لاگ زنده: `tail -f bot.log`

> اگر هاست از شما می‌خواهد پروسه بعد از ری‌استارت سرور هم بالا بیاید و به `systemd`/`crontab -e` با
> خط `@reboot` دسترسی دارید، می‌توانید همان دستور `nohup ... &` را در crontab هم اضافه کنید.

## ۶) دسترسی به پنل ادمین بدون خرید دامنه

دو حالت داریم:

### الف) هاست شما IP عمومی و پورت باز می‌دهد
مستقیم بروید به: `http://IP-هاست-شما:8000` و با `ADMIN_USERNAME`/`ADMIN_PASSWORD` وارد شوید.

### ب) هاست پورت عمومی نمی‌دهد (رایج در هاست‌های پایتونی اشتراکی)
از یک تونل رایگان استفاده کنید که بدون دامنه/سرور یک آدرس HTTPS موقت به شما می‌دهد.
ساده‌ترین گزینه **Cloudflare Tunnel** است (نیازی به ثبت‌نام هم ندارد):

```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
chmod +x cloudflared
./cloudflared tunnel --url http://localhost:8000
```

در خروجی یک آدرس شبیه `https://random-name.trycloudflare.com` می‌دهد — همان لینک پنل ادمین شماست.
این را هم بهتر است داخل `tmux` جدا اجرا کنید تا با بستن ترمینال قطع نشود:

```bash
tmux new -s tunnel
./cloudflared tunnel --url http://localhost:8000
# Ctrl+B سپس D
```

جایگزین: `ngrok` (`ngrok http 8000`) هم همین کار را می‌کند ولی نیاز به ساخت اکانت رایگان دارد.

## ۷) اولین ورود و تنظیمات کسب‌وکار

1. در تلگرام به ربات `/start` بزنید — چون آیدی شما در `ADMIN_IDS` است، به‌عنوان ادمین شناخته می‌شوید.
2. آدرس پنل (IP:8000 یا لینک cloudflared) را باز کنید و با `ADMIN_USERNAME`/`ADMIN_PASSWORD` وارد شوید.
3. از تب‌های Plans / Features / Payment Methods / Symbols قیمت‌ها، شماره کارت، ولت TON و محدودیت‌های رایگان را تنظیم کنید.

## ⚠️ نکات امنیتی مهم

- حتماً `ADMIN_PASSWORD` و `SESSION_SECRET` پیش‌فرض را عوض کنید — چون پنل روی اینترنت باز خواهد شد.
- لینک Cloudflare Quick Tunnel هر بار که دوباره اجرا کنید عوض می‌شود؛ اگر لینک ثابت می‌خواهید باید یک
  اکانت رایگان Cloudflare بسازید و Named Tunnel تعریف کنید (باز هم نیازی به خرید دامنه یا سرور نیست، فقط
  می‌توانید ساب‌دامنه رایگان از خود Cloudflare بگیرید، یا همان لینک موقت را هر بار استفاده کنید).
- دیتابیس SQLite به‌صورت پیش‌فرض در `data/tradebot.db` ذخیره می‌شود — این پوشه را حتماً Backup بگیرید،
  چون روی خیلی از هاست‌های رایگان با هر Deploy جدید فایل‌ها پاک می‌شوند.

## خلاصه دستورات (Copy/Paste)

```bash
cd ~/tradebot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env      # BOT_TOKEN, ADMIN_IDS, ADMIN_USERNAME/PASSWORD, SESSION_SECRET را پر کنید

tmux new -s tradebot
source venv/bin/activate
python main.py
# Ctrl+B سپس D

tmux new -s tunnel
./cloudflared tunnel --url http://localhost:8000
# Ctrl+B سپس D
```
