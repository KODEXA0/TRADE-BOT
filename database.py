"""
Database Layer
================
تمام مدل‌های SQLAlchemy، Session Factory و توابع کمکی init/seed اینجا هستند.
طراحی به گونه‌ای است که هیچ Plan/Feature/Payment Method ای Hard-Code نیست؛
همه از این جداول و از طریق Admin Panel مدیریت می‌شوند.

برای Migration واقعی در Production از Alembic استفاده کنید (alembic.ini نمونه در README).
برای شروع سریع، init_db() جداول را می‌سازد و داده‌های اولیه‌ی معقول را Seed می‌کند.
"""
from __future__ import annotations

import enum
import os
import uuid
import datetime as dt
from contextlib import contextmanager

from sqlalchemy import (
    create_engine, Column, Integer, BigInteger, String, Boolean, Float,
    DateTime, ForeignKey, Text, JSON, Enum as SAEnum, UniqueConstraint, Index
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, scoped_session

from config import cfg

os.makedirs(os.path.dirname(cfg.DATABASE_URL.split("///")[-1]) or ".", exist_ok=True) \
    if cfg.DATABASE_URL.startswith("sqlite") else None

connect_args = {"check_same_thread": False} if cfg.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(cfg.DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True))
Base = declarative_base()


def now() -> dt.datetime:
    return dt.datetime.utcnow()


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TradeDirection(str, enum.Enum):
    LONG = "long"
    SHORT = "short"


class TradeResult(str, enum.Enum):
    OPEN = "open"
    WIN = "win"
    LOSS = "loss"
    BREAKEVEN = "breakeven"


# ---------------------------------------------------------------------------
# Core: Users
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(64), nullable=True)
    first_name = Column(String(128), nullable=True)
    last_name = Column(String(128), nullable=True)

    joined_at = Column(DateTime, default=now)
    last_active_at = Column(DateTime, default=now)

    is_banned = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    language = Column(String(8), default="fa")

    # تنظیمات کاربر (نوتیفیکیشن و ...)
    settings = Column(JSON, default=dict)

    subscriptions = relationship("Subscription", back_populates="user", order_by="desc(Subscription.id)")
    payments = relationship("Payment", back_populates="user", order_by="desc(Payment.id)")
    usages = relationship("FeatureUsage", back_populates="user")
    trades = relationship("Trade", back_populates="user", order_by="desc(Trade.id)")
    alerts = relationship("Alert", back_populates="user", order_by="desc(Alert.id)")

    @property
    def full_name(self) -> str:
        return " ".join(filter(None, [self.first_name, self.last_name])) or (self.username or str(self.telegram_id))

    @property
    def active_subscription(self) -> "Subscription | None":
        active = [s for s in self.subscriptions if s.is_active and s.end_date > now()]
        return max(active, key=lambda s: s.end_date) if active else None

    @property
    def is_member(self) -> bool:
        return self.active_subscription is not None


# ---------------------------------------------------------------------------
# Features & Usage (Free-limit به صورت کامل از DB کنترل می‌شود)
# ---------------------------------------------------------------------------
class Feature(Base):
    __tablename__ = "features"

    id = Column(Integer, primary_key=True)
    key = Column(String(64), unique=True, nullable=False)
    name = Column(String(128), nullable=False)
    is_enabled = Column(Boolean, default=True)
    # NULL = نامحدود، 0 = کاملا غیرفعال برای Free، عدد مثبت = تعداد استفاده رایگان
    free_limit = Column(Integer, nullable=True)
    description = Column(Text, default="")


class FeatureUsage(Base):
    __tablename__ = "feature_usages"
    __table_args__ = (UniqueConstraint("user_id", "feature_key", name="uq_user_feature"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    feature_key = Column(String(64), nullable=False)
    count = Column(Integer, default=0)
    last_used_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="usages")


# ---------------------------------------------------------------------------
# Plans & Subscriptions
# ---------------------------------------------------------------------------
class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True)
    name = Column(String(64), nullable=False)
    price = Column(Float, nullable=False, default=0)
    currency = Column(String(16), default="IRT")
    duration_days = Column(Integer, nullable=False, default=30)
    description = Column(Text, default="")
    features_text = Column(Text, default="")  # نمایش خط به خط امکانات در پیام خرید
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)

    subscriptions = relationship("Subscription", back_populates="plan")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True)

    start_date = Column(DateTime, default=now)
    end_date = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)
    activated_by_admin_id = Column(BigInteger, nullable=True)

    user = relationship("User", back_populates="subscriptions")
    plan = relationship("Plan", back_populates="subscriptions")


# ---------------------------------------------------------------------------
# Payment Methods (Modular - کارت به کارت / TON / آینده: USDT، TRX، درگاه و ...)
# ---------------------------------------------------------------------------
class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id = Column(Integer, primary_key=True)
    key = Column(String(32), unique=True, nullable=False)   # card | ton | ...
    name = Column(String(64), nullable=False)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    # تمام جزئیات (شماره کارت، صاحب کارت، آدرس ولت، شبکه، توضیحات) در این JSON
    config = Column(JSON, default=dict)


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    payment_uid = Column(String(36), unique=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)

    amount = Column(Float, nullable=False)
    currency = Column(String(16), default="IRT")
    method_key = Column(String(32), nullable=False)

    status = Column(SAEnum(PaymentStatus), default=PaymentStatus.PENDING, index=True)

    receipt_file_id = Column(String(256), nullable=True)   # Telegram file_id اسکرین‌شات
    tx_hash = Column(String(256), nullable=True)
    user_note = Column(Text, default="")
    admin_note = Column(Text, default="")

    reviewed_by = Column(BigInteger, nullable=True)   # telegram_id ادمین بررسی‌کننده
    reviewed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=now)

    user = relationship("User", back_populates="payments")
    plan = relationship("Plan")


# ---------------------------------------------------------------------------
# Coupons
# ---------------------------------------------------------------------------
class Coupon(Base):
    __tablename__ = "coupons"

    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, nullable=False)
    discount_percent = Column(Float, nullable=True)
    discount_amount = Column(Float, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    max_uses = Column(Integer, nullable=True)
    used_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)


# ---------------------------------------------------------------------------
# Market: Symbols (Dynamic - هیچ ارزی Hard-Code نیست)
# ---------------------------------------------------------------------------
class Symbol(Base):
    __tablename__ = "symbols"
    __table_args__ = (UniqueConstraint("exchange", "symbol", name="uq_exchange_symbol"),)

    id = Column(Integer, primary_key=True)
    exchange = Column(String(32), nullable=False, default="binance")
    symbol = Column(String(32), nullable=False)   # e.g BTC/USDT
    base = Column(String(16), nullable=False)
    quote = Column(String(16), nullable=False)
    is_active = Column(Boolean, default=True)
    is_favorite = Column(Boolean, default=False)


# ---------------------------------------------------------------------------
# Smart Alerts
# ---------------------------------------------------------------------------
class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    symbol = Column(String(32), nullable=False)
    condition = Column(String(8), nullable=False)   # "above" | "below"
    target_price = Column(Float, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now)
    triggered_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="alerts")


# ---------------------------------------------------------------------------
# Trading Journal
# ---------------------------------------------------------------------------
class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    symbol = Column(String(32), nullable=False)
    direction = Column(SAEnum(TradeDirection), nullable=False)
    entry = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    position_size = Column(Float, nullable=True)
    result = Column(SAEnum(TradeResult), default=TradeResult.OPEN)
    profit_loss = Column(Float, nullable=True)
    strategy = Column(String(128), default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=now)

    user = relationship("User", back_populates="trades")


# ---------------------------------------------------------------------------
# Broadcast
# ---------------------------------------------------------------------------
class BroadcastLog(Base):
    __tablename__ = "broadcast_logs"

    id = Column(Integer, primary_key=True)
    admin_telegram_id = Column(BigInteger, nullable=True)
    segment = Column(String(32), default="all")   # all|free|member|plan:<id>|expired
    message = Column(Text, default="")
    image_file_id = Column(String(256), nullable=True)
    sent_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=now)


# ---------------------------------------------------------------------------
# Settings (Key-Value قابل تغییر از Admin Panel)
# ---------------------------------------------------------------------------
class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, default="")


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    actor = Column(String(64), nullable=False)   # e.g "user:123" or "admin:web"
    action = Column(String(128), nullable=False)
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime, default=now, index=True)


Index("ix_payments_status_created", Payment.status, Payment.created_at)


# ---------------------------------------------------------------------------
# Session helper
# ---------------------------------------------------------------------------
@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def log_audit(actor: str, action: str, meta: dict | None = None):
    """ثبت لاگ عملیات مهم. اطلاعات حساس (رمز، شماره کارت کامل و ...) نباید داخل meta ذخیره شود."""
    try:
        with get_session() as s:
            s.add(AuditLog(actor=actor, action=action, meta=meta or {}))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Default Settings keys (مقدار واقعی از Admin Panel تغییر می‌کند)
# ---------------------------------------------------------------------------
DEFAULT_SETTINGS = {
    "bot_name": "Trading Intelligence Platform",
    "welcome_message": (
        "👋 به *Trading Intelligence Platform* خوش آمدید!\n\n"
        "دستیار حرفه‌ای شما برای تحلیل بازار، مدیریت ریسک و رشد مهارت معامله‌گری."
    ),
    "expired_message": "⏳ اشتراک شما به پایان رسیده است. برای ادامه استفاده از امکانات، اشتراک خود را تمدید کنید.",
    "rules_text": "با استفاده از این ربات، شما مسئولیت تصمیمات معاملاتی خود را می‌پذیرید. این ربات مشاور مالی نیست.",
    "support_username": "@support",
}


def init_db(seed: bool = True):
    Base.metadata.create_all(engine)
    if not seed:
        return
    with get_session() as s:
        # Seed Settings
        for k, v in DEFAULT_SETTINGS.items():
            if not s.get(Setting, k):
                s.add(Setting(key=k, value=v))

        # Seed Features
        if s.query(Feature).count() == 0:
            for key, name, limit in cfg.ALL_FEATURES:
                s.add(Feature(key=key, name=name, is_enabled=True, free_limit=limit))

        # Seed Plans
        if s.query(Plan).count() == 0:
            s.add_all([
                Plan(name="Basic", price=490000, currency="IRT", duration_days=30,
                     description="مناسب شروع مسیر حرفه‌ای معامله‌گری",
                     features_text="✅ اسکن بازار نامحدود\n✅ تحلیل هوشمند AI (۱۰ بار/ماه)\n✅ ژورنال معاملاتی",
                     is_active=True, sort_order=1),
                Plan(name="Pro", price=990000, currency="IRT", duration_days=30,
                     description="برای معامله‌گران فعال",
                     features_text="✅ تمام امکانات Basic\n✅ تحلیل هوشمند AI نامحدود\n✅ Smart Alerts نامحدود\n✅ تحلیل چارت پیشرفته",
                     is_active=True, sort_order=2),
                Plan(name="VIP", price=1990000, currency="IRT", duration_days=30,
                     description="بالاترین سطح دسترسی و پشتیبانی اختصاصی",
                     features_text="✅ تمام امکانات Pro\n✅ پشتیبانی اختصاصی\n✅ دسترسی زودهنگام به امکانات جدید",
                     is_active=True, sort_order=3),
            ])

        # Seed Payment Methods
        if s.query(PaymentMethod).count() == 0:
            s.add_all([
                PaymentMethod(key="card", name="💳 کارت به کارت", is_active=True, sort_order=1, config={
                    "card_number": "6037-XXXX-XXXX-XXXX",
                    "card_holder": "نام صاحب کارت",
                    "instructions": "لطفا پس از واریز، اسکرین‌شات رسید را ارسال کنید.",
                }),
                PaymentMethod(key="ton", name="💎 TON", is_active=True, sort_order=2, config={
                    "wallet_address": "UQXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
                    "network": "TON",
                    "instructions": "لطفا پس از تراکنش، اسکرین‌شات و در صورت امکان TxID را ارسال کنید.",
                }),
            ])

        # Seed a few default symbols (کاربر/ادمین می‌توانند لیست را گسترش دهند)
        if s.query(Symbol).count() == 0:
            defaults = [
                ("BTC", "USDT"), ("ETH", "USDT"), ("SOL", "USDT"), ("BNB", "USDT"),
                ("XRP", "USDT"), ("ADA", "USDT"), ("DOGE", "USDT"), ("TON", "USDT"),
                ("AVAX", "USDT"), ("LINK", "USDT"), ("ETH", "BTC"), ("BTC", "USDC"),
            ]
            for base, quote in defaults:
                s.add(Symbol(exchange=cfg.CCXT_EXCHANGE, symbol=f"{base}/{quote}",
                              base=base, quote=quote, is_active=True))
