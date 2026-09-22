# ⚡ Trading Intelligence Platform (Telegram)

پلتفرم حرفه‌ای Trading Intelligence با رابط اصلی Telegram Bot، سیستم Subscription واقعی،
Free-Trial محدود per-feature، Payment Management (کارت‌به‌کارت + TON، Modular برای افزودن روش‌های بعدی)،
Admin Panel کامل تحت وب، Market Scanner چند-ارزی Dynamic، AI Analysis، Risk Management،
Trading Journal و Performance Analytics.

## 📁 ساختار پروژه (عمدا فشرده و ماژولار)

```
tradebot/
├── config.py         # تمام تنظیمات از Environment Variables
├── database.py        # مدل‌های SQLAlchemy (Schema کامل) + init/seed
├── services.py         # منطق تجاری: Subscription/Payment/FeatureGate/MarketData/AI/Risk
├── keyboards.py        # تمام Inline Keyboardهای ربات
├── bot_user.py         # تمام Handlerهای کاربر (منوها و قابلیت‌های Trading)
├── bot_admin.py        # Handlerهای ادمین داخل تلگرام (تأیید/رد پرداخت و ...)
├── admin_panel.py      # پنل مدیریت تحت وب (FastAPI)
├── main.py             # Entry point (اجرای همزمان Bot + Admin Panel + Alert Worker)
├── requirements.txt
├── .env.example
├── Dockerfile
├── docker-compose.yml
└── README.md
```

> چرا اینقدر فایل کم است؟ به‌جای شکستن هر Feature به فایل جدا، منطق‌های هم‌خانواده
> در یک ماژول منسجم قرار گرفته‌اند (مثلا همه Market/AI/Risk Providerها در `services.py`).
> این ساختار برای شروع سریع و نگهداری آسان بهینه شده و در عین حال کاملا Layered است
> (Database ↔ Services ↔ Bot/Admin) تا بعدا با خیال راحت بتوانید هرکدام را به فایل/پکیج
> جداگانه بشکنید.

## 🏗 معماری

- **Database Layer** (`database.py`): SQLAlchemy ORM با پشتیبانی SQLite (پیش‌فرض، برای شروع سریع)
  یا PostgreSQL (برای Production، فقط با تغییر `DATABASE_URL`).
- **Services Layer** (`services.py`):
  - `FeatureGate`: کنترل استفاده رایگان هر Feature (کاملا از DB، صفر Hard-Code).
  - `SubscriptionService` / `PaymentService`: چرخه کامل پرداخت تا فعال‌سازی اشتراک.
  - `MarketDataProvider` (Interface) با دو پیاده‌سازی: `MockMarketDataProvider` (بدون نیاز به API خارجی)
    و `CCXTMarketDataProvider` (بر پایه کتابخانه `ccxt` که به ده‌ها Exchange و هزاران Symbol
    به صورت Dynamic دسترسی دارد؛ افزودن ارز جدید فقط یک ردیف در جدول `symbols` است، نه تغییر کد).
  - `AIAnalysisProvider` (Interface) با `MockAIAnalysisProvider` و `AnthropicAIAnalysisProvider`
    (پشتیبانی از تحلیل متنی و تحلیل تصویر چارت / Vision).
- **Presentation Layer**: `bot_user.py` + `bot_admin.py` (Telegram) و `admin_panel.py` (Web).

### افزودن یک Exchange/Provider جدید
کافیست یک کلاس جدید از `MarketDataProvider` بسازید (در `services.py`) و آن را در
`get_market_provider()` اضافه کنید؛ هیچ بخش دیگری از کد نیاز به تغییر ندارد.

### افزودن یک روش پرداخت جدید (مثلا USDT/TRX/درگاه)
1. یک رکورد جدید در جدول `payment_methods` بسازید (از Admin Panel یا مستقیم DB) با `key` دلخواه.
2. در `bot_user.cb_payment_instructions` یک شاخه‌ی متن راهنما برای `method_key` جدید اضافه کنید
   (منطق فعلی از `config` (JSON) خود روش پرداخت استفاده می‌کند، پس اکثر روش‌ها بدون تغییر کد هم کار می‌کنند).

## 🚀 راه‌اندازی سریع (Local)

```bash
python -m venv venv
source venv/bin/activate   # ویندوز: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# .env را باز کنید و BOT_TOKEN، ADMIN_IDS، ADMIN_USERNAME/PASSWORD و SESSION_SECRET را تنظیم کنید

python main.py
```

- ربات تلگرام شروع به کار می‌کند (Polling).
- پنل ادمین در آدرس `http://localhost:8000` بالا می‌آید (ورود با `ADMIN_USERNAME`/`ADMIN_PASSWORD`).

## 🐳 راه‌اندازی با Docker

```bash
cp .env.example .env
# مقادیر .env را تنظیم کنید
docker compose up -d --build
```

## 🔑 متغیرهای مهم Environment (`.env`)

| متغیر | توضیح |
|---|---|
| `BOT_TOKEN` | توکن ربات از BotFather |
| `ADMIN_IDS` | Telegram ID ادمین‌ها (کاما جدا) |
| `DATABASE_URL` | آدرس اتصال دیتابیس (SQLite یا PostgreSQL) |
| `ANTHROPIC_API_KEY` | برای فعال شدن AI Analysis واقعی (خالی = حالت Mock) |
| `MARKET_DATA_PROVIDER` | `mock` یا `ccxt` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | ورود پنل وب |
| `SESSION_SECRET` | رشته تصادفی طولانی برای امضای Session |

**هیچ Secret ای را داخل کد قرار ندهید.** تمام مقادیر حساس فقط از `.env` خوانده می‌شوند.

## 🗄 Migration

برای شروع سریع، `init_db()` در `database.py` جداول را با `create_all` می‌سازد. برای Production
و تغییرات Schema در آینده، توصیه می‌شود Alembic راه‌اندازی شود:

```bash
pip install alembic
alembic init migrations
# سپس target_metadata را در migrations/env.py به database.Base.metadata ست کنید
alembic revision --autogenerate -m "init"
alembic upgrade head
```

## 🔐 نکات امنیتی پیاده‌سازی‌شده

- Session ادمین با کوکی امضاشده (`itsdangerous`) - نه Plaintext.
- تمام Secretها از Environment Variable.
- Audit Log برای عملیات حساس (`log_audit` در `database.py`).
- ورودی‌های عددی (قیمت، سرمایه و ...) Validate می‌شوند و خطاها Catch می‌شوند تا ربات Crash نکند.
- استفاده از ORM (SQLAlchemy) به‌جای Query خام برای جلوگیری از SQL Injection.
- برای Production حتما: HTTPS جلوی پنل ادمین (Reverse Proxy مثل Nginx/Caddy)، Rate Limiting
  در سطح Nginx یا Middleware، و چرخش دوره‌ای `SESSION_SECRET` و `ADMIN_PASSWORD`.

## 🧩 نقشه توسعه آینده (طراحی از قبل برای این‌ها لحاظ شده)

- Strategy Builder / Backtesting Engine → روی `MarketDataProvider.get_ohlcv` سوار می‌شود.
- Binance/Bybit/TradingView/Forex/Stock Providerها → فقط یک کلاس جدید `MarketDataProvider`.
- Automatic Crypto Payment Verification → یک `PaymentVerifier` جدید که `PaymentService.approve` را
  به‌صورت خودکار صدا بزند (به‌جای تأیید دستی ادمین).
- Queue/Worker واقعی (Celery/RQ) برای Scan/Broadcast/AI در مقیاس بزرگ‌تر — فعلا با
  `asyncio` Background Task (`alert_worker` در `main.py`) پیاده شده که برای چند هزار کاربر کفایت می‌کند.

## ✅ ساخت ادمین اول و تست

1. `.env` را با `ADMIN_IDS` (آیدی عددی تلگرام خودتان) و `ADMIN_USERNAME`/`ADMIN_PASSWORD` پر کنید.
2. `python main.py` را اجرا کنید.
3. در تلگرام به ربات `/start` بزنید — چون آیدی شما در `ADMIN_IDS` است، به‌صورت خودکار Admin محسوب می‌شوید
   و می‌توانید پرداخت‌ها را از داخل چت هم تأیید/رد کنید.
4. وارد `http://localhost:8000` شوید و از تب‌های Plans/Features/Payment Methods/Symbols تنظیمات اولیه
   کسب‌وکار خود (قیمت‌ها، شماره کارت، ولت TON، محدودیت‌های رایگان) را وارد کنید.

## ⚠️ یادآوری مهم

این ربات **مشاور مالی نیست** و هیچ تضمین سود یا پیش‌بینی قطعی بازار ارائه نمی‌دهد؛ خروجی‌های AI
صرفا جنبه آموزشی/تحلیلی دارند (این محدودیت مستقیما در Prompt سیستم AI در `services.py` اعمال شده است).
