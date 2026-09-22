"""
Services Layer
================
تمام منطق تجاری (غیر از خود Handlerهای تلگرام) اینجاست:
- FeatureGate: کنترل Free-Trial / Limit هر Feature
- SubscriptionService: فعال‌سازی و بررسی اشتراک
- PaymentService: ایجاد و مدیریت درخواست پرداخت
- MarketDataProvider: Interface استاندارد + Mock + CCXT (چند صرافی/چند ارز به صورت Dynamic)
- AIAnalysisProvider: Interface + Mock + Anthropic-backed
- RiskCalculator: محاسبات مدیریت ریسک و حجم معامله
"""
from __future__ import annotations

import abc
import datetime as dt
import random
from dataclasses import dataclass, field

import httpx

from config import cfg, logger
from database import (
    get_session, User, Feature, FeatureUsage, Plan, Subscription, Payment,
    PaymentMethod, PaymentStatus, Symbol, Setting, log_audit, now,
)


# =============================================================================
# Feature Gate  (Free vs Member - محدودیت‌ها کاملا از DB می‌آید، هیچ عددی Hard-Code نیست)
# =============================================================================
@dataclass
class FeatureCheckResult:
    allowed: bool
    reason: str = ""           # "" | "disabled" | "limit_reached"
    remaining: int | None = None   # None = نامحدود


class FeatureGate:
    @staticmethod
    def check(user_id: int, feature_key: str) -> FeatureCheckResult:
        with get_session() as s:
            feature = s.query(Feature).filter_by(key=feature_key).first()
            if not feature or not feature.is_enabled:
                return FeatureCheckResult(False, reason="disabled")

            user = s.get(User, user_id)
            if user and user.is_member:
                return FeatureCheckResult(True, remaining=None)

            if feature.free_limit is None:
                return FeatureCheckResult(True, remaining=None)
            if feature.free_limit == 0:
                return FeatureCheckResult(False, reason="disabled")

            usage = s.query(FeatureUsage).filter_by(user_id=user_id, feature_key=feature_key).first()
            used = usage.count if usage else 0
            remaining = feature.free_limit - used
            if remaining <= 0:
                return FeatureCheckResult(False, reason="limit_reached", remaining=0)
            return FeatureCheckResult(True, remaining=remaining)

    @staticmethod
    def consume(user_id: int, feature_key: str):
        with get_session() as s:
            usage = s.query(FeatureUsage).filter_by(user_id=user_id, feature_key=feature_key).first()
            if not usage:
                usage = FeatureUsage(user_id=user_id, feature_key=feature_key, count=0)
                s.add(usage)
            usage.count += 1
            usage.last_used_at = now()
        log_audit(f"user:{user_id}", "feature_used", {"feature": feature_key})


# =============================================================================
# Subscription Service
# =============================================================================
class SubscriptionService:
    @staticmethod
    def activate(user_id: int, plan_id: int, payment_id: int | None, admin_telegram_id: int | None) -> Subscription:
        with get_session() as s:
            plan = s.get(Plan, plan_id)
            user = s.get(User, user_id)
            existing = user.active_subscription
            start = existing.end_date if existing else now()
            end = start + dt.timedelta(days=plan.duration_days)

            sub = Subscription(
                user_id=user_id, plan_id=plan_id, payment_id=payment_id,
                start_date=now(), end_date=end, is_active=True,
                activated_by_admin_id=admin_telegram_id,
            )
            s.add(sub)
            s.flush()
            sub_id = sub.id
        log_audit(f"admin:{admin_telegram_id}", "subscription_activated",
                   {"user_id": user_id, "plan_id": plan_id, "payment_id": payment_id})
        return sub_id

    @staticmethod
    def extend(user_id: int, days: int):
        with get_session() as s:
            user = s.get(User, user_id)
            sub = user.active_subscription
            if sub:
                sub.end_date = sub.end_date + dt.timedelta(days=days)
            else:
                plan = s.query(Plan).filter_by(is_active=True).order_by(Plan.sort_order).first()
                s.add(Subscription(user_id=user_id, plan_id=plan.id, start_date=now(),
                                    end_date=now() + dt.timedelta(days=days), is_active=True))


# =============================================================================
# Payment Service
# =============================================================================
class PaymentService:
    @staticmethod
    def create_request(user_id: int, plan_id: int, method_key: str) -> Payment:
        with get_session() as s:
            plan = s.get(Plan, plan_id)
            payment = Payment(
                user_id=user_id, plan_id=plan_id, amount=plan.price,
                currency=plan.currency, method_key=method_key,
                status=PaymentStatus.PENDING,
            )
            s.add(payment)
            s.flush()
            s.refresh(payment)
            pid = payment.id
        log_audit(f"user:{user_id}", "payment_created", {"plan_id": plan_id, "method": method_key})
        return pid

    @staticmethod
    def attach_receipt(payment_id: int, file_id: str | None, tx_hash: str | None, note: str | None):
        with get_session() as s:
            p = s.get(Payment, payment_id)
            if file_id:
                p.receipt_file_id = file_id
            if tx_hash:
                p.tx_hash = tx_hash
            if note:
                p.user_note = note

    @staticmethod
    def approve(payment_id: int, plan_id: int, admin_telegram_id: int) -> int:
        with get_session() as s:
            p = s.get(Payment, payment_id)
            p.status = PaymentStatus.APPROVED
            p.reviewed_by = admin_telegram_id
            p.reviewed_at = now()
            p.plan_id = plan_id
            user_id = p.user_id
        sub_id = SubscriptionService.activate(user_id, plan_id, payment_id, admin_telegram_id)
        log_audit(f"admin:{admin_telegram_id}", "payment_approved", {"payment_id": payment_id})
        return sub_id

    @staticmethod
    def reject(payment_id: int, reason: str, admin_telegram_id: int):
        with get_session() as s:
            p = s.get(Payment, payment_id)
            p.status = PaymentStatus.REJECTED
            p.admin_note = reason
            p.reviewed_by = admin_telegram_id
            p.reviewed_at = now()
        log_audit(f"admin:{admin_telegram_id}", "payment_rejected", {"payment_id": payment_id, "reason": reason})


# =============================================================================
# Market Data Provider  -  Interface استاندارد (Provider-agnostic)
# =============================================================================
@dataclass
class Ticker:
    symbol: str
    price: float
    change_24h: float | None = None
    volume_24h: float | None = None
    high_24h: float | None = None
    low_24h: float | None = None


class MarketDataProvider(abc.ABC):
    """Interface استاندارد - هر Provider جدید (Binance/Bybit/TradingView/...) این را پیاده می‌کند."""

    @abc.abstractmethod
    async def list_symbols(self) -> list[str]:
        ...

    @abc.abstractmethod
    async def get_ticker(self, symbol: str) -> Ticker:
        ...

    @abc.abstractmethod
    async def scan_top_movers(self, symbols: list[str], limit: int = 10) -> list[Ticker]:
        ...

    @abc.abstractmethod
    async def get_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 100) -> list[dict]:
        ...


class MockMarketDataProvider(MarketDataProvider):
    """برای Development / زمانی که هیچ API واقعی متصل نیست."""

    _BASE_PRICES = {"BTC": 65000, "ETH": 3400, "SOL": 145, "BNB": 590, "XRP": 0.62,
                     "ADA": 0.45, "DOGE": 0.14, "TON": 5.3, "AVAX": 27, "LINK": 14}

    async def list_symbols(self) -> list[str]:
        with get_session() as s:
            return [sym.symbol for sym in s.query(Symbol).filter_by(is_active=True).all()]

    def _price_for(self, symbol: str) -> float:
        base = symbol.split("/")[0]
        p = self._BASE_PRICES.get(base, 1.0)
        return round(p * (1 + random.uniform(-0.03, 0.03)), 6)

    async def get_ticker(self, symbol: str) -> Ticker:
        price = self._price_for(symbol)
        return Ticker(
            symbol=symbol, price=price,
            change_24h=round(random.uniform(-8, 8), 2),
            volume_24h=round(random.uniform(1_000_000, 500_000_000), 2),
            high_24h=round(price * 1.02, 6), low_24h=round(price * 0.98, 6),
        )

    async def scan_top_movers(self, symbols: list[str], limit: int = 10) -> list[Ticker]:
        tickers = [await self.get_ticker(sym) for sym in symbols]
        tickers.sort(key=lambda t: abs(t.change_24h or 0), reverse=True)
        return tickers[:limit]

    async def get_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 100) -> list[dict]:
        price = self._price_for(symbol)
        candles = []
        for i in range(limit):
            o = price * (1 + random.uniform(-0.01, 0.01))
            c = o * (1 + random.uniform(-0.01, 0.01))
            h = max(o, c) * (1 + random.uniform(0, 0.005))
            l = min(o, c) * (1 - random.uniform(0, 0.005))
            candles.append({"open": o, "high": h, "low": l, "close": c,
                             "volume": random.uniform(10, 1000)})
            price = c
        return candles


class CCXTMarketDataProvider(MarketDataProvider):
    """
    Provider واقعی مبتنی بر کتابخانه ccxt که ده‌ها Exchange و هزاران Symbol را
    به صورت Dynamic (بدون نیاز به تغییر کد) پشتیبانی می‌کند.
    """

    def __init__(self, exchange_id: str = "binance"):
        import ccxt  # local import تا وابستگی سنگین فقط وقتی لازم است بار شود
        self.exchange_id = exchange_id
        self.exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})

    async def list_symbols(self) -> list[str]:
        markets = self.exchange.load_markets()
        return [m for m in markets.keys() if markets[m].get("active", True)]

    async def get_ticker(self, symbol: str) -> Ticker:
        t = self.exchange.fetch_ticker(symbol)
        return Ticker(
            symbol=symbol, price=t.get("last") or t.get("close") or 0,
            change_24h=t.get("percentage"), volume_24h=t.get("quoteVolume"),
            high_24h=t.get("high"), low_24h=t.get("low"),
        )

    async def scan_top_movers(self, symbols: list[str], limit: int = 10) -> list[Ticker]:
        out = []
        for sym in symbols:
            try:
                out.append(await self.get_ticker(sym))
            except Exception as e:
                logger.warning(f"ccxt ticker failed for {sym}: {e}")
        out.sort(key=lambda t: abs(t.change_24h or 0), reverse=True)
        return out[:limit]

    async def get_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 100) -> list[dict]:
        raw = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return [{"open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]} for r in raw]


def get_market_provider() -> MarketDataProvider:
    if cfg.MARKET_DATA_PROVIDER == "ccxt":
        try:
            return CCXTMarketDataProvider(cfg.CCXT_EXCHANGE)
        except Exception as e:
            logger.error(f"CCXT provider init failed, falling back to Mock: {e}")
    return MockMarketDataProvider()


market_provider = get_market_provider()


# =============================================================================
# AI Analysis Provider  -  Interface + Mock + Anthropic-backed
# =============================================================================
class AIAnalysisProvider(abc.ABC):
    @abc.abstractmethod
    async def analyze_market(self, symbol: str, ticker: Ticker, candles: list[dict]) -> str:
        ...

    @abc.abstractmethod
    async def analyze_chart_image(self, image_bytes: bytes, symbol_hint: str = "") -> str:
        ...


class MockAIAnalysisProvider(AIAnalysisProvider):
    async def analyze_market(self, symbol: str, ticker: Ticker, candles: list[dict]) -> str:
        trend = "صعودی" if (ticker.change_24h or 0) >= 0 else "نزولی"
        return (
            f"🤖 *تحلیل هوشمند {symbol}* (نسخه آزمایشی/Mock)\n\n"
            f"📈 روند کوتاه‌مدت: {trend}\n"
            f"💰 قیمت فعلی: {ticker.price}\n"
            f"🔺 مقاومت تخمینی: {round(ticker.price * 1.03, 4)}\n"
            f"🔻 حمایت تخمینی: {round(ticker.price * 0.97, 4)}\n"
            f"🎯 سناریوهای محتمل: ادامه روند در صورت شکست مقاومت / اصلاح در صورت رد شدن از مقاومت\n"
            f"⚠️ نقطه ابطال تحلیل: شکست حمایت با حجم بالا\n"
            f"🛡 ریسک: متوسط\n\n"
            f"_این تحلیل صرفا جنبه آموزشی دارد و توصیه سرمایه‌گذاری نیست._"
        )

    async def analyze_chart_image(self, image_bytes: bytes, symbol_hint: str = "") -> str:
        return (
            "🤖 *تحلیل چارت* (نسخه آزمایشی/Mock)\n\n"
            "📊 ساختار بازار: در حال تثبیت (Range)\n"
            "🔺 ناحیه مقاومت شناسایی شد\n"
            "🔻 ناحیه حمایت شناسایی شد\n"
            "🎯 سناریو: انتظار شکست یکی از دو ناحیه برای تعیین جهت بعدی\n"
            "⚠️ نقطه ابطال: بسته شدن کندل خارج از Range\n\n"
            "_برای دریافت تحلیل واقعی مبتنی بر تصویر، ANTHROPIC_API_KEY را تنظیم کنید._"
        )


class AnthropicAIAnalysisProvider(AIAnalysisProvider):
    """از Anthropic API برای تحلیل متنی و تصویری (Vision) استفاده می‌کند."""

    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def _call(self, content: list[dict]) -> str:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": 700,
            "system": (
                "تو یک تحلیل‌گر ارشد بازار کریپتو هستی. تحلیل باید شامل روند، ساختار بازار، "
                "حمایت/مقاومت، سناریوهای محتمل، نقطه ابطال و سطح ریسک باشد. هرگز پیش‌بینی قطعی یا "
                "وعده سود نده. پاسخ را به فارسی و با فرمت خوانا (Markdown ساده) بده."
            ),
            "messages": [{"role": "user", "content": content}],
        }
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(self.API_URL, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
            return "\n".join(parts) or "پاسخی دریافت نشد."

    async def analyze_market(self, symbol: str, ticker: Ticker, candles: list[dict]) -> str:
        prompt = (
            f"نماد: {symbol}\nقیمت فعلی: {ticker.price}\nتغییر ۲۴ساعته: {ticker.change_24h}%\n"
            f"حجم ۲۴ساعته: {ticker.volume_24h}\nتعداد کندل موجود: {len(candles)}\n"
            "بر اساس این داده‌ها یک تحلیل کوتاه ارائه بده."
        )
        try:
            return await self._call([{"type": "text", "text": prompt}])
        except Exception as e:
            logger.error(f"AI analyze_market failed: {e}")
            return await MockAIAnalysisProvider().analyze_market(symbol, ticker, candles)

    async def analyze_chart_image(self, image_bytes: bytes, symbol_hint: str = "") -> str:
        import base64
        b64 = base64.b64encode(image_bytes).decode()
        content = [
            {"type": "text", "text": f"این تصویر چارت {symbol_hint or 'یک ارز دیجیتال'} است. تحلیل کن."},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
        ]
        try:
            return await self._call(content)
        except Exception as e:
            logger.error(f"AI analyze_chart_image failed: {e}")
            return await MockAIAnalysisProvider().analyze_chart_image(image_bytes, symbol_hint)


def get_ai_provider() -> AIAnalysisProvider:
    if cfg.ANTHROPIC_API_KEY:
        return AnthropicAIAnalysisProvider(cfg.ANTHROPIC_API_KEY, cfg.AI_MODEL)
    return MockAIAnalysisProvider()


ai_provider = get_ai_provider()


# =============================================================================
# Risk / Position Size Calculator
# =============================================================================
@dataclass
class RiskResult:
    position_size: float
    risk_amount: float
    potential_profit: float | None
    risk_reward: float | None
    stop_distance_pct: float


class RiskCalculator:
    @staticmethod
    def calculate(capital: float, risk_percent: float, entry: float,
                   stop_loss: float, take_profit: float | None = None) -> RiskResult:
        risk_amount = capital * (risk_percent / 100)
        stop_distance = abs(entry - stop_loss)
        if stop_distance <= 0:
            raise ValueError("فاصله Entry و Stop Loss باید بزرگتر از صفر باشد.")
        position_size = risk_amount / stop_distance
        stop_distance_pct = (stop_distance / entry) * 100

        potential_profit = None
        rr = None
        if take_profit:
            profit_distance = abs(take_profit - entry)
            potential_profit = position_size * profit_distance
            rr = round(profit_distance / stop_distance, 2)

        return RiskResult(
            position_size=round(position_size, 6),
            risk_amount=round(risk_amount, 2),
            potential_profit=round(potential_profit, 2) if potential_profit else None,
            risk_reward=rr,
            stop_distance_pct=round(stop_distance_pct, 2),
        )


# =============================================================================
# Settings helper
# =============================================================================
def get_setting(key: str, default: str = "") -> str:
    with get_session() as s:
        row = s.get(Setting, key)
        return row.value if row else default


def set_setting(key: str, value: str):
    with get_session() as s:
        row = s.get(Setting, key)
        if row:
            row.value = value
        else:
            s.add(Setting(key=key, value=value))
