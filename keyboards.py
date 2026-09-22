"""
Keyboards
==========
تمام Inline Keyboardهای ربات (منوی اصلی و منوهای تودرتو) اینجا تعریف شده‌اند
تا Navigation یکدست و قابل نگهداری باشد.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def _kb(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for row in rows:
        builder.row(*[InlineKeyboardButton(text=t, callback_data=cb) for t, cb in row])
    return builder.as_markup()


def main_menu() -> InlineKeyboardMarkup:
    return _kb(
        [("📊 داشبورد", "menu:dashboard")],
        [("🔎 اسکن بازار", "menu:scanner"), ("🤖 تحلیل هوشمند", "menu:ai")],
        [("📈 تحلیل چارت", "menu:chart"), ("🎯 Smart Alerts", "menu:alerts")],
        [("💰 مدیریت ریسک", "menu:risk"), ("🧮 محاسبه حجم", "menu:poscalc")],
        [("📓 ژورنال معاملاتی", "menu:journal"), ("📊 عملکرد من", "menu:performance")],
        [("⭐ اشتراک من", "menu:mysub"), ("💳 خرید اشتراک", "menu:buy")],
        [("⚙️ تنظیمات", "menu:settings"), ("ℹ️ راهنما", "menu:help")],
    )


def back_home(back_cb: str = "menu:home") -> InlineKeyboardMarkup:
    return _kb([("🔙 بازگشت", back_cb), ("🏠 منوی اصلی", "menu:home")])


def home_only() -> InlineKeyboardMarkup:
    return _kb([("🏠 منوی اصلی", "menu:home")])


def upsell_kb() -> InlineKeyboardMarkup:
    return _kb([("💳 خرید اشتراک", "menu:buy")], [("🏠 منوی اصلی", "menu:home")])


def plans_kb(plans: list) -> InlineKeyboardMarkup:
    rows = [[(f"{p.name} - {int(p.price):,} {p.currency}", f"plan:{p.id}")] for p in plans]
    rows.append([("🏠 منوی اصلی", "menu:home")])
    return _kb(*rows)


def plan_detail_kb(plan_id: int) -> InlineKeyboardMarkup:
    return _kb(
        [("✅ ادامه و انتخاب روش پرداخت", f"buy_plan:{plan_id}")],
        [("🔙 بازگشت", "menu:buy"), ("🏠 منوی اصلی", "menu:home")],
    )


def payment_methods_kb(methods: list, plan_id: int) -> InlineKeyboardMarkup:
    rows = [[(m.name, f"pay_method:{plan_id}:{m.key}")] for m in methods]
    rows.append([("🔙 بازگشت", "menu:buy"), ("🏠 منوی اصلی", "menu:home")])
    return _kb(*rows)


def after_receipt_kb() -> InlineKeyboardMarkup:
    return _kb([("✅ ارسال درخواست", "confirm_payment:1")], [("🏠 منوی اصلی", "menu:home")])


def admin_payment_actions_kb(payment_id: int) -> InlineKeyboardMarkup:
    return _kb(
        [("✅ تأیید پرداخت", f"adm_approve:{payment_id}"), ("❌ رد پرداخت", f"adm_reject:{payment_id}")],
        [("🎁 تغییر Plan", f"adm_changeplan:{payment_id}"), ("👤 پروفایل کاربر", f"adm_profile:{payment_id}")],
    )


def admin_choose_plan_kb(payment_id: int, plans: list) -> InlineKeyboardMarkup:
    rows = [[(p.name, f"adm_setplan:{payment_id}:{p.id}")] for p in plans]
    return _kb(*rows)


def scanner_menu_kb() -> InlineKeyboardMarkup:
    return _kb(
        [("🔥 Top Movers", "scan:top_movers"), ("⭐ Favorites", "scan:favorites")],
        [("📃 همه نمادها", "scan:all")],
        [("🔙 بازگشت", "menu:home")],
    )


def symbol_pick_kb(symbols: list[str], prefix: str, page: int = 0, per_page: int = 8) -> InlineKeyboardMarkup:
    start = page * per_page
    chunk = symbols[start:start + per_page]
    rows = [[(s, f"{prefix}:{s}")] for s in chunk]
    nav = []
    if page > 0:
        nav.append((f"◀️ قبلی", f"{prefix}_page:{page-1}"))
    if start + per_page < len(symbols):
        nav.append((f"بعدی ▶️", f"{prefix}_page:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([("🏠 منوی اصلی", "menu:home")])
    return _kb(*rows)


def alert_condition_kb(symbol: str) -> InlineKeyboardMarkup:
    return _kb(
        [("📈 بالاتر از", f"alertcond:{symbol}:above"), ("📉 پایین‌تر از", f"alertcond:{symbol}:below")],
        [("🏠 منوی اصلی", "menu:home")],
    )


def journal_menu_kb() -> InlineKeyboardMarkup:
    return _kb(
        [("➕ ثبت معامله جدید", "journal:add")],
        [("📋 معاملات اخیر", "journal:list")],
        [("🏠 منوی اصلی", "menu:home")],
    )


def trade_direction_kb() -> InlineKeyboardMarkup:
    return _kb([("🟢 Long", "tdir:long"), ("🔴 Short", "tdir:short")])


def trade_result_kb(trade_id: int) -> InlineKeyboardMarkup:
    return _kb(
        [("✅ Win", f"tres:{trade_id}:win"), ("❌ Loss", f"tres:{trade_id}:loss"), ("➖ BE", f"tres:{trade_id}:breakeven")],
        [("🏠 منوی اصلی", "menu:home")],
    )


def settings_kb(notif_on: bool) -> InlineKeyboardMarkup:
    toggle = "🔕 خاموش کردن نوتیفیکیشن‌ها" if notif_on else "🔔 روشن کردن نوتیفیکیشن‌ها"
    return _kb(
        [(toggle, "settings:toggle_notif")],
        [("🌐 زبان: فارسی 🇮🇷", "settings:lang")],
        [("🏠 منوی اصلی", "menu:home")],
    )


def confirm_cancel_kb(confirm_cb: str, cancel_cb: str = "menu:home") -> InlineKeyboardMarkup:
    return _kb([("✅ تایید", confirm_cb), ("❌ انصراف", cancel_cb)])
