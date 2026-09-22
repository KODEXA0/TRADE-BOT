"""
Config - تمام تنظیمات پروژه از Environment Variables خوانده می‌شود.
هیچ Secret ای نباید داخل Source Code Hard-Code شود.
"""
import os
import logging
from dotenv import load_dotenv

load_dotenv()


def _split_ids(raw: str) -> set[int]:
    out = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS: set[int] = _split_ids(os.getenv("ADMIN_IDS", ""))
    ADMIN_NOTIFY_CHAT_ID: str = os.getenv("ADMIN_NOTIFY_CHAT_ID", "").strip()

    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./data/tradebot.db")

    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    AI_MODEL: str = os.getenv("AI_MODEL", "claude-sonnet-4-6")

    MARKET_DATA_PROVIDER: str = os.getenv("MARKET_DATA_PROVIDER", "mock")
    CCXT_EXCHANGE: str = os.getenv("CCXT_EXCHANGE", "binance")

    ADMIN_PANEL_HOST: str = os.getenv("ADMIN_PANEL_HOST", "0.0.0.0")
    ADMIN_PANEL_PORT: int = int(os.getenv("ADMIN_PANEL_PORT", "8000"))
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin")
    SESSION_SECRET: str = os.getenv("SESSION_SECRET", "insecure-dev-secret-change-me")

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # کلیدهای Feature ثابت (فقط شناسه‌ی داخلی؛ محدودیت/فعال بودن هرکدام کاملا از DB می‌آید)
    FEATURE_MARKET_SCANNER = "market_scanner"
    FEATURE_AI_ANALYSIS = "ai_analysis"
    FEATURE_CHART_ANALYSIS = "chart_analysis"
    FEATURE_SMART_ALERTS = "smart_alerts"
    FEATURE_RISK_MANAGEMENT = "risk_management"
    FEATURE_POSITION_CALC = "position_calculator"
    FEATURE_JOURNAL = "trading_journal"
    FEATURE_PERFORMANCE = "performance_analytics"

    ALL_FEATURES = [
        (FEATURE_MARKET_SCANNER, "اسکن بازار", 5),
        (FEATURE_AI_ANALYSIS, "تحلیل هوشمند AI", 1),
        (FEATURE_CHART_ANALYSIS, "تحلیل چارت", 1),
        (FEATURE_SMART_ALERTS, "Smart Alerts", 2),
        (FEATURE_RISK_MANAGEMENT, "مدیریت ریسک", None),  # نامحدود پیش‌فرض
        (FEATURE_POSITION_CALC, "محاسبه حجم معامله", None),
        (FEATURE_JOURNAL, "ژورنال معاملاتی", 3),
        (FEATURE_PERFORMANCE, "عملکرد من", None),
    ]


cfg = Config()

logging.basicConfig(
    level=getattr(logging, cfg.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("tradebot")
