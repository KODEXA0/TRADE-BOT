"""
Main Entry Point
==================
همزمان اجرا می‌کند:
  1) Telegram Bot (aiogram polling)
  2) Admin Web Panel (FastAPI/uvicorn)
  3) Background Worker ساده برای بررسی Smart Alerts و انقضای اشتراک‌ها

اجرا: python main.py
(یا از طریق Docker - رجوع کنید به README.md و docker-compose.yml)
"""
import asyncio

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import cfg, logger
from database import init_db, get_session, Alert, User
from services import market_provider
import bot_user
import bot_admin
from admin_panel import app as admin_app


async def run_bot():
    if not cfg.BOT_TOKEN:
        logger.error("BOT_TOKEN تنظیم نشده است؛ ربات اجرا نمی‌شود.")
        return
    bot = Bot(token=cfg.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(bot_admin.router)  # ادمین قبل از هندلرهای عمومی چک شود
    dp.include_router(bot_user.router)

    logger.info("🤖 Telegram Bot در حال اجرا (polling)...")
    await dp.start_polling(bot)


async def run_admin_panel():
    config = uvicorn.Config(admin_app, host=cfg.ADMIN_PANEL_HOST, port=cfg.ADMIN_PANEL_PORT, log_level="info")
    server = uvicorn.Server(config)
    logger.info(f"🖥 Admin Panel در حال اجرا روی http://{cfg.ADMIN_PANEL_HOST}:{cfg.ADMIN_PANEL_PORT}")
    await server.serve()


async def alert_worker():
    """هر ۶۰ ثانیه Alertهای فعال را با قیمت لحظه‌ای مقایسه می‌کند و در صورت برخورد به کاربر پیام می‌دهد."""
    if not cfg.BOT_TOKEN:
        return
    bot = Bot(token=cfg.BOT_TOKEN)
    while True:
        try:
            with get_session() as s:
                alerts = s.query(Alert).filter_by(is_active=True).all()
                pending = [(a.id, a.user_id, a.symbol, a.condition, a.target_price) for a in alerts]

            for alert_id, user_id, symbol, condition, target in pending:
                try:
                    ticker = await market_provider.get_ticker(symbol)
                except Exception:
                    continue
                hit = (condition == "above" and ticker.price >= target) or \
                      (condition == "below" and ticker.price <= target)
                if hit:
                    with get_session() as s:
                        a = s.get(Alert, alert_id)
                        if not a or not a.is_active:
                            continue
                        a.is_active = False
                        from database import now
                        a.triggered_at = now()
                        user = s.get(User, user_id)
                        tg_id = user.telegram_id
                    try:
                        arrow = "📈" if condition == "above" else "📉"
                        await bot.send_message(
                            tg_id,
                            f"{arrow} *Smart Alert فعال شد!*\n\n"
                            f"نماد: {symbol}\nقیمت فعلی: {ticker.price}\nشرط: {condition} {target}",
                            parse_mode="Markdown",
                        )
                    except Exception as e:
                        logger.error(f"alert notify failed: {e}")
        except Exception as e:
            logger.error(f"alert_worker error: {e}")
        await asyncio.sleep(60)


async def main():
    init_db(seed=True)
    await asyncio.gather(
        run_bot(),
        run_admin_panel(),
        alert_worker(),
    )


if __name__ == "__main__":
    asyncio.run(main())
