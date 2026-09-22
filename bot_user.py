"""
Bot User Handlers
===================
تمام منوها و قابلیت‌های کاربر (غیر ادمین): داشبورد، اسکنر، AI، چارت، آلرت، ریسک،
ژورنال، عملکرد، خرید اشتراک و پرداخت، تنظیمات و راهنما.

Navigation: هر صفحه دکمه «🔙 بازگشت» و «🏠 منوی اصلی» دارد (کیبوردها در keyboards.py).
"""
from __future__ import annotations

import datetime as dt

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, BufferedInputFile

import keyboards as kb
from config import cfg, logger
from database import (
    get_session, User, Plan, PaymentMethod, Feature, Trade, TradeDirection,
    TradeResult, Alert, PaymentStatus, log_audit, now,
)
from services import (
    FeatureGate, PaymentService, market_provider, ai_provider, RiskCalculator, get_setting,
)

router = Router(name="user")


# =============================================================================
# FSM States
# =============================================================================
class BuyFlow(StatesGroup):
    waiting_receipt = State()
    waiting_tx_hash = State()
    waiting_amount_note = State()


class RiskFlow(StatesGroup):
    capital = State()
    risk_percent = State()
    entry = State()
    stop_loss = State()
    take_profit = State()


class JournalFlow(StatesGroup):
    symbol = State()
    direction = State()
    entry = State()
    stop_loss = State()
    take_profit = State()
    size = State()
    notes = State()


class AlertFlow(StatesGroup):
    waiting_symbol = State()
    waiting_price = State()


class AIFlow(StatesGroup):
    waiting_symbol = State()


class ChartFlow(StatesGroup):
    waiting_image = State()


# =============================================================================
# Helpers
# =============================================================================
def get_or_create_user(tg_user) -> int:
    with get_session() as s:
        user = s.query(User).filter_by(telegram_id=tg_user.id).first()
        if not user:
            user = User(
                telegram_id=tg_user.id, username=tg_user.username,
                first_name=tg_user.first_name, last_name=tg_user.last_name,
                is_admin=tg_user.id in cfg.ADMIN_IDS,
            )
            s.add(user)
            s.flush()
            log_audit(f"user:{user.id}", "user_created", {"telegram_id": tg_user.id})
        else:
            user.last_active_at = now()
            user.username = tg_user.username
            user.first_name = tg_user.first_name
            user.last_name = tg_user.last_name
        s.flush()
        return user.id


async def send_menu(target: Message | CallbackQuery, text: str, keyboard, edit: bool = True):
    if isinstance(target, CallbackQuery):
        try:
            if edit:
                await target.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
            else:
                await target.message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
        except Exception:
            await target.message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await target.answer(text, reply_markup=keyboard, parse_mode="Markdown")


def upsell_text(feature_name: str) -> str:
    return (
        f"🔒 *{feature_name}*\n\n"
        "شما از سهمیه استفاده رایگان این قابلیت استفاده کرده‌اید.\n"
        "برای استفاده نامحدود، اشتراک تهیه کنید 👇"
    )


# =============================================================================
# /start و منوی اصلی
# =============================================================================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    get_or_create_user(message.from_user)
    welcome = get_setting("welcome_message", "👋 خوش آمدید!")
    await message.answer(welcome, parse_mode="Markdown")
    await message.answer("از منوی زیر بخش موردنظر را انتخاب کنید:", reply_markup=kb.main_menu())


@router.callback_query(F.data == "menu:home")
async def cb_home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await send_menu(call, "🏠 *منوی اصلی*\nبخش موردنظر را انتخاب کنید:", kb.main_menu())
    await call.answer()


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🏠 *منوی اصلی*", reply_markup=kb.main_menu(), parse_mode="Markdown")


# =============================================================================
# 📊 داشبورد
# =============================================================================
@router.callback_query(F.data == "menu:dashboard")
async def cb_dashboard(call: CallbackQuery):
    with get_session() as s:
        user = s.query(User).filter_by(telegram_id=call.from_user.id).first()
        sub = user.active_subscription
        sub_text = "فاقد اشتراک فعال (Free)" if not sub else \
            f"{sub.plan.name} — تا {sub.end_date.strftime('%Y-%m-%d')}"
        trades_count = len(user.trades)

    text = (
        f"📊 *داشبورد شما*\n\n"
        f"👤 نام: {call.from_user.full_name}\n"
        f"📅 عضویت از: {user.joined_at.strftime('%Y-%m-%d')}\n"
        f"⭐ وضعیت اشتراک: {sub_text}\n"
        f"📓 تعداد معاملات ثبت‌شده: {trades_count}\n"
    )
    await send_menu(call, text, kb.back_home())
    await call.answer()


# =============================================================================
# ⭐ اشتراک من / 💳 خرید اشتراک
# =============================================================================
@router.callback_query(F.data == "menu:mysub")
async def cb_mysub(call: CallbackQuery):
    with get_session() as s:
        user = s.query(User).filter_by(telegram_id=call.from_user.id).first()
        sub = user.active_subscription
    if not sub:
        text = "⭐ *اشتراک من*\n\nشما در حال حاضر اشتراک فعالی ندارید."
        keyboard = kb.upsell_kb()
    else:
        text = (
            f"⭐ *اشتراک من*\n\n"
            f"پلن: {sub.plan.name}\n"
            f"شروع: {sub.start_date.strftime('%Y-%m-%d')}\n"
            f"پایان: {sub.end_date.strftime('%Y-%m-%d')}\n"
        )
        keyboard = kb.back_home()
    await send_menu(call, text, keyboard)
    await call.answer()


@router.callback_query(F.data == "menu:buy")
async def cb_buy(call: CallbackQuery):
    with get_session() as s:
        plans = s.query(Plan).filter_by(is_active=True).order_by(Plan.sort_order).all()
        plans = [(p.id, p.name, p.price, p.currency) for p in plans]
    if not plans:
        await send_menu(call, "در حال حاضر پلن فعالی موجود نیست.", kb.home_only())
        return await call.answer()

    class P:  # small proxy to keep keyboard helper generic
        def __init__(self, id, name, price, currency):
            self.id, self.name, self.price, self.currency = id, name, price, currency

    proxies = [P(*p) for p in plans]
    await send_menu(call, "💳 *خرید اشتراک*\n\nیکی از پلن‌های زیر را انتخاب کنید:", kb.plans_kb(proxies))
    await call.answer()


@router.callback_query(F.data.startswith("plan:"))
async def cb_plan_detail(call: CallbackQuery):
    plan_id = int(call.data.split(":")[1])
    with get_session() as s:
        plan = s.get(Plan, plan_id)
        if not plan or not plan.is_active:
            return await call.answer("این پلن در دسترس نیست.", show_alert=True)
        text = (
            f"📦 *{plan.name}*\n\n"
            f"💰 قیمت: {int(plan.price):,} {plan.currency}\n"
            f"⏱ مدت: {plan.duration_days} روز\n\n"
            f"{plan.description}\n\n"
            f"{plan.features_text}"
        )
    await send_menu(call, text, kb.plan_detail_kb(plan_id))
    await call.answer()


@router.callback_query(F.data.startswith("buy_plan:"))
async def cb_choose_method(call: CallbackQuery):
    plan_id = int(call.data.split(":")[1])
    with get_session() as s:
        methods = s.query(PaymentMethod).filter_by(is_active=True).order_by(PaymentMethod.sort_order).all()
        methods = [(m.id, m.key, m.name) for m in methods]
    if not methods:
        await send_menu(call, "در حال حاضر روش پرداخت فعالی موجود نیست.", kb.home_only())
        return await call.answer()

    class M:
        def __init__(self, id, key, name):
            self.id, self.key, self.name = id, key, name

    proxies = [M(*m) for m in methods]
    await send_menu(call, "روش پرداخت را انتخاب کنید:", kb.payment_methods_kb(proxies, plan_id))
    await call.answer()


@router.callback_query(F.data.startswith("pay_method:"))
async def cb_payment_instructions(call: CallbackQuery, state: FSMContext):
    _, plan_id, method_key = call.data.split(":")
    plan_id = int(plan_id)
    with get_session() as s:
        plan = s.get(Plan, plan_id)
        method = s.query(PaymentMethod).filter_by(key=method_key, is_active=True).first()
        if not plan or not method:
            return await call.answer("گزینه انتخابی در دسترس نیست.", show_alert=True)
        cfg_data = method.config or {}

    payment_id = PaymentService.create_request(
        user_id=_user_pk(call.from_user.id), plan_id=plan_id, method_key=method_key
    )
    await state.update_data(payment_id=payment_id, plan_id=plan_id, method_key=method_key)

    if method_key == "card":
        text = (
            f"💳 *پرداخت کارت به کارت*\n\n"
            f"شماره کارت: `{cfg_data.get('card_number', '-')}`\n"
            f"به نام: {cfg_data.get('card_holder', '-')}\n"
            f"مبلغ دقیق: {int(plan.price):,} {plan.currency}\n\n"
            f"{cfg_data.get('instructions', '')}\n\n"
            f"⬇️ پس از پرداخت، *اسکرین‌شات رسید* را ارسال کنید."
        )
        await state.set_state(BuyFlow.waiting_receipt)
    else:  # ton یا سایر crypto
        text = (
            f"💎 *پرداخت {method.name}*\n\n"
            f"آدرس ولت: `{cfg_data.get('wallet_address', '-')}`\n"
            f"شبکه: {cfg_data.get('network', '-')}\n"
            f"مبلغ: {int(plan.price):,} {plan.currency} معادل\n\n"
            f"{cfg_data.get('instructions', '')}\n\n"
            f"⬇️ پس از تراکنش، *اسکرین‌شات* را ارسال کنید (و در صورت امکان TxID)."
        )
        await state.set_state(BuyFlow.waiting_receipt)

    await send_menu(call, text, kb.home_only())
    await call.answer()


def _user_pk(telegram_id: int) -> int:
    with get_session() as s:
        return s.query(User).filter_by(telegram_id=telegram_id).first().id


@router.message(BuyFlow.waiting_receipt, F.photo)
async def receive_receipt(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    payment_id = data.get("payment_id")
    file_id = message.photo[-1].file_id
    PaymentService.attach_receipt(payment_id, file_id, None, None)
    await state.set_state(BuyFlow.waiting_tx_hash)
    await message.answer(
        "✅ رسید دریافت شد.\n\n"
        "در صورت داشتن شماره پیگیری/TxID یا توضیح اضافه، ارسال کنید؛ در غیر این صورت بنویسید «ندارم».",
    )


@router.message(BuyFlow.waiting_tx_hash, F.text)
async def receive_tx_hash(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    payment_id = data.get("payment_id")
    note = message.text.strip()
    tx = None if note in ("ندارم", "-", "") else note
    PaymentService.attach_receipt(payment_id, None, tx, note)
    await state.clear()

    with get_session() as s:
        from database import Payment
        p = s.get(Payment, payment_id)
        user = s.get(User, p.user_id)
        plan = s.get(Plan, p.plan_id)
        summary = (
            f"🧾 *درخواست پرداخت شما ثبت شد*\n\n"
            f"شناسه پرداخت: `{p.payment_uid[:8]}`\n"
            f"پلن: {plan.name}\n"
            f"مبلغ: {int(p.amount):,} {p.currency}\n"
            f"وضعیت: در انتظار بررسی ادمین ⏳"
        )
        admin_msg = (
            f"🆕 *درخواست پرداخت جدید*\n\n"
            f"👤 کاربر: {user.full_name} (@{user.username or '-'})\n"
            f"🆔 Telegram ID: `{user.telegram_id}`\n"
            f"🧾 Payment ID: `{p.payment_uid[:8]}`\n"
            f"📦 پلن درخواستی: {plan.name}\n"
            f"💰 مبلغ: {int(p.amount):,} {p.currency}\n"
            f"💳 روش: {p.method_key}\n"
            f"📝 یادداشت: {p.user_note or '-'}"
        )
        receipt_file_id = p.receipt_file_id
        pid = p.id

    await message.answer(summary, parse_mode="Markdown", reply_markup=kb.home_only())

    # اطلاع‌رسانی فوری به ادمین‌ها
    targets = [cfg.ADMIN_NOTIFY_CHAT_ID] if cfg.ADMIN_NOTIFY_CHAT_ID else list(cfg.ADMIN_IDS)
    for chat_id in targets:
        try:
            if receipt_file_id:
                await bot.send_photo(chat_id, receipt_file_id, caption=admin_msg, parse_mode="Markdown",
                                      reply_markup=kb.admin_payment_actions_kb(pid))
            else:
                await bot.send_message(chat_id, admin_msg, parse_mode="Markdown",
                                        reply_markup=kb.admin_payment_actions_kb(pid))
        except Exception as e:
            logger.error(f"Failed to notify admin {chat_id}: {e}")


# =============================================================================
# 🔎 اسکن بازار
# =============================================================================
@router.callback_query(F.data == "menu:scanner")
async def cb_scanner_menu(call: CallbackQuery):
    check = FeatureGate.check(_user_pk(call.from_user.id), cfg.FEATURE_MARKET_SCANNER)
    if not check.allowed:
        return await send_upsell(call, "اسکن بازار", check)
    await send_menu(call, "🔎 *اسکن بازار*\n\nحالت اسکن را انتخاب کنید:", kb.scanner_menu_kb())
    await call.answer()


async def send_upsell(call: CallbackQuery, name: str, check):
    if check.reason == "disabled":
        text = f"🔒 *{name}*\n\nاین قابلیت در حال حاضر غیرفعال است."
        keyboard = kb.home_only()
    else:
        text = upsell_text(name)
        keyboard = kb.upsell_kb()
    await send_menu(call, text, keyboard)
    await call.answer()


@router.callback_query(F.data.startswith("scan:"))
async def cb_scan_run(call: CallbackQuery):
    user_pk = _user_pk(call.from_user.id)
    check = FeatureGate.check(user_pk, cfg.FEATURE_MARKET_SCANNER)
    if not check.allowed:
        return await send_upsell(call, "اسکن بازار", check)

    mode = call.data.split(":")[1]
    symbols = await market_provider.list_symbols()
    if mode == "favorites":
        with get_session() as s:
            from database import Symbol
            symbols = [sy.symbol for sy in s.query(Symbol).filter_by(is_favorite=True, is_active=True).all()] or symbols[:5]

    if mode in ("top_movers", "favorites"):
        results = await market_provider.scan_top_movers(symbols, limit=10)
        lines = ["🔎 *نتایج اسکن بازار*\n"]
        for t in results:
            arrow = "🟢" if (t.change_24h or 0) >= 0 else "🔴"
            lines.append(f"{arrow} `{t.symbol}` — {t.price}  ({t.change_24h}%)")
        text = "\n".join(lines)
        await send_menu(call, text, kb.back_home())
    else:  # all
        await send_menu(call, "📃 لیست نماد را انتخاب کنید:", kb.symbol_pick_kb(symbols, "ticker"))

    FeatureGate.consume(user_pk, cfg.FEATURE_MARKET_SCANNER)
    await call.answer()


@router.callback_query(F.data.startswith("ticker:"))
async def cb_ticker_detail(call: CallbackQuery):
    symbol = call.data.split(":", 1)[1]
    t = await market_provider.get_ticker(symbol)
    text = (
        f"📊 *{symbol}*\n\n"
        f"💰 قیمت: {t.price}\n"
        f"📈 تغییر ۲۴ساعته: {t.change_24h}%\n"
        f"🔺 سقف ۲۴ساعته: {t.high_24h}\n"
        f"🔻 کف ۲۴ساعته: {t.low_24h}\n"
        f"📦 حجم: {t.volume_24h}\n"
    )
    await send_menu(call, text, kb.back_home("menu:scanner"))
    await call.answer()


@router.callback_query(F.data.startswith("ticker_page:"))
async def cb_ticker_page(call: CallbackQuery):
    page = int(call.data.split(":")[1])
    symbols = await market_provider.list_symbols()
    await send_menu(call, "📃 لیست نماد را انتخاب کنید:", kb.symbol_pick_kb(symbols, "ticker", page=page))
    await call.answer()


# =============================================================================
# 🤖 تحلیل هوشمند AI
# =============================================================================
@router.callback_query(F.data == "menu:ai")
async def cb_ai_menu(call: CallbackQuery, state: FSMContext):
    user_pk = _user_pk(call.from_user.id)
    check = FeatureGate.check(user_pk, cfg.FEATURE_AI_ANALYSIS)
    if not check.allowed:
        return await send_upsell(call, "تحلیل هوشمند AI", check)
    await state.set_state(AIFlow.waiting_symbol)
    await send_menu(call, "🤖 *تحلیل هوشمند AI*\n\nنماد موردنظر را تایپ کنید (مثل BTC/USDT):", kb.back_home())
    await call.answer()


@router.message(AIFlow.waiting_symbol, F.text)
async def do_ai_analysis(message: Message, state: FSMContext):
    user_pk = _user_pk(message.from_user.id)
    check = FeatureGate.check(user_pk, cfg.FEATURE_AI_ANALYSIS)
    if not check.allowed:
        await state.clear()
        text = upsell_text("تحلیل هوشمند AI")
        return await message.answer(text, reply_markup=kb.upsell_kb(), parse_mode="Markdown")

    symbol = message.text.strip().upper()
    wait_msg = await message.answer("⏳ در حال تحلیل بازار...")
    ticker = await market_provider.get_ticker(symbol)
    candles = await market_provider.get_ohlcv(symbol, "1h", 50)
    analysis = await ai_provider.analyze_market(symbol, ticker, candles)
    FeatureGate.consume(user_pk, cfg.FEATURE_AI_ANALYSIS)
    await state.clear()
    await wait_msg.delete()
    await message.answer(analysis, reply_markup=kb.back_home(), parse_mode="Markdown")


# =============================================================================
# 📈 تحلیل چارت (تصویر)
# =============================================================================
@router.callback_query(F.data == "menu:chart")
async def cb_chart_menu(call: CallbackQuery, state: FSMContext):
    user_pk = _user_pk(call.from_user.id)
    check = FeatureGate.check(user_pk, cfg.FEATURE_CHART_ANALYSIS)
    if not check.allowed:
        return await send_upsell(call, "تحلیل چارت", check)
    await state.set_state(ChartFlow.waiting_image)
    await send_menu(call, "📈 *تحلیل چارت*\n\nتصویر چارت را ارسال کنید:", kb.back_home())
    await call.answer()


@router.message(ChartFlow.waiting_image, F.photo)
async def do_chart_analysis(message: Message, state: FSMContext, bot: Bot):
    user_pk = _user_pk(message.from_user.id)
    check = FeatureGate.check(user_pk, cfg.FEATURE_CHART_ANALYSIS)
    if not check.allowed:
        await state.clear()
        return await message.answer(upsell_text("تحلیل چارت"), reply_markup=kb.upsell_kb(), parse_mode="Markdown")

    wait_msg = await message.answer("⏳ در حال تحلیل چارت...")
    file = await bot.get_file(message.photo[-1].file_id)
    buf = await bot.download_file(file.file_path)
    analysis = await ai_provider.analyze_chart_image(buf.read())
    FeatureGate.consume(user_pk, cfg.FEATURE_CHART_ANALYSIS)
    await state.clear()
    await wait_msg.delete()
    await message.answer(analysis, reply_markup=kb.back_home(), parse_mode="Markdown")


# =============================================================================
# 🎯 Smart Alerts
# =============================================================================
@router.callback_query(F.data == "menu:alerts")
async def cb_alerts_menu(call: CallbackQuery, state: FSMContext):
    user_pk = _user_pk(call.from_user.id)
    check = FeatureGate.check(user_pk, cfg.FEATURE_SMART_ALERTS)
    if not check.allowed:
        return await send_upsell(call, "Smart Alerts", check)

    with get_session() as s:
        alerts = s.query(Alert).filter_by(user_id=user_pk, is_active=True).all()
    lines = ["🎯 *Smart Alerts*\n", "هشدارهای فعال شما:\n"]
    if not alerts:
        lines.append("_هیچ هشدار فعالی ندارید._")
    for a in alerts:
        arrow = "📈" if a.condition == "above" else "📉"
        lines.append(f"{arrow} {a.symbol} {'بالاتر از' if a.condition=='above' else 'پایین‌تر از'} {a.target_price}")

    await state.set_state(AlertFlow.waiting_symbol)
    text = "\n".join(lines) + "\n\nبرای ساخت هشدار جدید، نماد را تایپ کنید (مثل BTC/USDT):"
    await send_menu(call, text, kb.back_home())
    await call.answer()


@router.message(AlertFlow.waiting_symbol, F.text)
async def alert_symbol_received(message: Message, state: FSMContext):
    symbol = message.text.strip().upper()
    await state.update_data(symbol=symbol)
    await message.answer(f"شرط هشدار برای {symbol}:", reply_markup=kb.alert_condition_kb(symbol))


@router.callback_query(F.data.startswith("alertcond:"))
async def alert_condition_received(call: CallbackQuery, state: FSMContext):
    _, symbol, cond = call.data.split(":")
    await state.update_data(symbol=symbol, condition=cond)
    await state.set_state(AlertFlow.waiting_price)
    await send_menu(call, f"قیمت هدف برای {symbol} را وارد کنید (فقط عدد):", kb.back_home())
    await call.answer()


@router.message(AlertFlow.waiting_price, F.text)
async def alert_price_received(message: Message, state: FSMContext):
    user_pk = _user_pk(message.from_user.id)
    try:
        price = float(message.text.strip().replace(",", ""))
    except ValueError:
        return await message.answer("لطفا فقط عدد وارد کنید.")

    data = await state.get_data()
    with get_session() as s:
        s.add(Alert(user_id=user_pk, symbol=data["symbol"], condition=data["condition"],
                     target_price=price, is_active=True))
    FeatureGate.consume(user_pk, cfg.FEATURE_SMART_ALERTS)
    await state.clear()
    await message.answer("✅ هشدار ذخیره شد و در پس‌زمینه بررسی می‌شود.", reply_markup=kb.back_home())


# =============================================================================
# 💰 مدیریت ریسک  /  🧮 محاسبه حجم معامله  (هر دو از یک Flow استفاده می‌کنند)
# =============================================================================
@router.callback_query(F.data.in_({"menu:risk", "menu:poscalc"}))
async def cb_risk_start(call: CallbackQuery, state: FSMContext):
    feature = cfg.FEATURE_RISK_MANAGEMENT if call.data == "menu:risk" else cfg.FEATURE_POSITION_CALC
    user_pk = _user_pk(call.from_user.id)
    check = FeatureGate.check(user_pk, feature)
    if not check.allowed:
        return await send_upsell(call, "مدیریت ریسک", check)
    await state.update_data(feature=feature)
    await state.set_state(RiskFlow.capital)
    await send_menu(call, "💰 *مدیریت ریسک*\n\nسرمایه کل (Capital) را وارد کنید:", kb.back_home())
    await call.answer()


async def _ask_float(message: Message, state: FSMContext, field: str, next_state, prompt: str):
    try:
        val = float(message.text.strip().replace(",", ""))
    except ValueError:
        return await message.answer("لطفا فقط عدد وارد کنید.")
    await state.update_data(**{field: val})
    await state.set_state(next_state)
    await message.answer(prompt)


@router.message(RiskFlow.capital, F.text)
async def risk_capital(message: Message, state: FSMContext):
    await _ask_float(message, state, "capital", RiskFlow.risk_percent,
                      "درصد ریسک قابل قبول در این معامله چند درصد است؟ (مثلا 1)")


@router.message(RiskFlow.risk_percent, F.text)
async def risk_percent(message: Message, state: FSMContext):
    await _ask_float(message, state, "risk_percent", RiskFlow.entry, "قیمت Entry را وارد کنید:")


@router.message(RiskFlow.entry, F.text)
async def risk_entry(message: Message, state: FSMContext):
    await _ask_float(message, state, "entry", RiskFlow.stop_loss, "قیمت Stop Loss را وارد کنید:")


@router.message(RiskFlow.stop_loss, F.text)
async def risk_sl(message: Message, state: FSMContext):
    await _ask_float(message, state, "stop_loss", RiskFlow.take_profit,
                      "قیمت Take Profit را وارد کنید (یا «ندارم»):")


@router.message(RiskFlow.take_profit, F.text)
async def risk_tp(message: Message, state: FSMContext):
    data = await state.get_data()
    tp = None
    txt = message.text.strip()
    if txt not in ("ندارم", "-", ""):
        try:
            tp = float(txt.replace(",", ""))
        except ValueError:
            return await message.answer("لطفا عدد معتبر یا «ندارم» وارد کنید.")

    user_pk = _user_pk(message.from_user.id)
    try:
        result = RiskCalculator.calculate(data["capital"], data["risk_percent"], data["entry"], data["stop_loss"], tp)
    except ValueError as e:
        await state.clear()
        return await message.answer(f"⚠️ خطا: {e}", reply_markup=kb.back_home())

    text = (
        f"💰 *نتیجه محاسبه مدیریت ریسک*\n\n"
        f"📏 حجم پوزیشن پیشنهادی: `{result.position_size}`\n"
        f"⚠️ مبلغ در معرض ریسک: `{result.risk_amount}`\n"
        f"📐 فاصله Stop (%): `{result.stop_distance_pct}%`\n"
    )
    if result.potential_profit is not None:
        text += f"🎯 سود بالقوه: `{result.potential_profit}`\n📊 نسبت R/R: `{result.risk_reward}`\n"

    FeatureGate.consume(user_pk, data.get("feature", cfg.FEATURE_RISK_MANAGEMENT))
    await state.clear()
    await message.answer(text, reply_markup=kb.back_home(), parse_mode="Markdown")


# =============================================================================
# 📓 ژورنال معاملاتی
# =============================================================================
@router.callback_query(F.data == "menu:journal")
async def cb_journal_menu(call: CallbackQuery):
    check = FeatureGate.check(_user_pk(call.from_user.id), cfg.FEATURE_JOURNAL)
    if not check.allowed:
        return await send_upsell(call, "ژورنال معاملاتی", check)
    await send_menu(call, "📓 *ژورنال معاملاتی*", kb.journal_menu_kb())
    await call.answer()


@router.callback_query(F.data == "journal:add")
async def cb_journal_add(call: CallbackQuery, state: FSMContext):
    check = FeatureGate.check(_user_pk(call.from_user.id), cfg.FEATURE_JOURNAL)
    if not check.allowed:
        return await send_upsell(call, "ژورنال معاملاتی", check)
    await state.set_state(JournalFlow.symbol)
    await send_menu(call, "نماد معامله را وارد کنید (مثل BTC/USDT):", kb.back_home("menu:journal"))
    await call.answer()


@router.message(JournalFlow.symbol, F.text)
async def journal_symbol(message: Message, state: FSMContext):
    await state.update_data(symbol=message.text.strip().upper())
    await state.set_state(JournalFlow.direction)
    await message.answer("جهت معامله؟", reply_markup=kb.trade_direction_kb())


@router.callback_query(JournalFlow.direction, F.data.startswith("tdir:"))
async def journal_direction(call: CallbackQuery, state: FSMContext):
    direction = call.data.split(":")[1]
    await state.update_data(direction=direction)
    await state.set_state(JournalFlow.entry)
    await send_menu(call, "قیمت Entry؟", kb.back_home("menu:journal"))
    await call.answer()


@router.message(JournalFlow.entry, F.text)
async def journal_entry(message: Message, state: FSMContext):
    await _ask_float(message, state, "entry", JournalFlow.stop_loss, "قیمت Stop Loss؟ (یا «ندارم»)")


@router.message(JournalFlow.stop_loss, F.text)
async def journal_sl(message: Message, state: FSMContext):
    txt = message.text.strip()
    val = None if txt in ("ندارم", "-", "") else float(txt.replace(",", ""))
    await state.update_data(stop_loss=val)
    await state.set_state(JournalFlow.take_profit)
    await message.answer("قیمت Take Profit؟ (یا «ندارم»)")


@router.message(JournalFlow.take_profit, F.text)
async def journal_tp(message: Message, state: FSMContext):
    txt = message.text.strip()
    val = None if txt in ("ندارم", "-", "") else float(txt.replace(",", ""))
    await state.update_data(take_profit=val)
    await state.set_state(JournalFlow.size)
    await message.answer("حجم پوزیشن؟ (یا «ندارم»)")


@router.message(JournalFlow.size, F.text)
async def journal_size(message: Message, state: FSMContext):
    txt = message.text.strip()
    val = None if txt in ("ندارم", "-", "") else float(txt.replace(",", ""))
    await state.update_data(size=val)
    await state.set_state(JournalFlow.notes)
    await message.answer("یادداشت/استراتژی (اختیاری - یا «ندارم»)")


@router.message(JournalFlow.notes, F.text)
async def journal_notes(message: Message, state: FSMContext):
    notes = "" if message.text.strip() in ("ندارم", "-") else message.text.strip()
    data = await state.get_data()
    user_pk = _user_pk(message.from_user.id)

    with get_session() as s:
        trade = Trade(
            user_id=user_pk, symbol=data["symbol"],
            direction=TradeDirection.LONG if data["direction"] == "long" else TradeDirection.SHORT,
            entry=data["entry"], stop_loss=data.get("stop_loss"), take_profit=data.get("take_profit"),
            position_size=data.get("size"), notes=notes,
        )
        s.add(trade)
        s.flush()
        trade_id = trade.id

    FeatureGate.consume(user_pk, cfg.FEATURE_JOURNAL)
    await state.clear()
    await message.answer("✅ معامله ثبت شد. نتیجه معامله را می‌توانید بعدا مشخص کنید:",
                          reply_markup=kb.trade_result_kb(trade_id))


@router.callback_query(F.data.startswith("tres:"))
async def journal_set_result(call: CallbackQuery):
    _, trade_id, result = call.data.split(":")
    with get_session() as s:
        trade = s.get(Trade, int(trade_id))
        trade.result = {"win": TradeResult.WIN, "loss": TradeResult.LOSS,
                         "breakeven": TradeResult.BREAKEVEN}[result]
    await send_menu(call, "✅ نتیجه معامله ثبت شد.", kb.back_home("menu:journal"))
    await call.answer()


@router.callback_query(F.data == "journal:list")
async def journal_list(call: CallbackQuery):
    user_pk = _user_pk(call.from_user.id)
    with get_session() as s:
        trades = s.query(Trade).filter_by(user_id=user_pk).order_by(Trade.id.desc()).limit(10).all()
    if not trades:
        text = "📋 هنوز معامله‌ای ثبت نشده است."
    else:
        lines = ["📋 *۱۰ معامله اخیر*\n"]
        for t in trades:
            emoji = {"win": "✅", "loss": "❌", "breakeven": "➖", "open": "⏳"}[t.result.value]
            lines.append(f"{emoji} {t.symbol} | {t.direction.value} | Entry: {t.entry}")
        text = "\n".join(lines)
    await send_menu(call, text, kb.back_home("menu:journal"))
    await call.answer()


# =============================================================================
# 📊 عملکرد من (Performance Analytics)
# =============================================================================
@router.callback_query(F.data == "menu:performance")
async def cb_performance(call: CallbackQuery):
    user_pk = _user_pk(call.from_user.id)
    check = FeatureGate.check(user_pk, cfg.FEATURE_PERFORMANCE)
    if not check.allowed:
        return await send_upsell(call, "عملکرد من", check)

    with get_session() as s:
        trades = s.query(Trade).filter_by(user_id=user_pk).all()

    closed = [t for t in trades if t.result != TradeResult.OPEN]
    wins = [t for t in closed if t.result == TradeResult.WIN]
    losses = [t for t in closed if t.result == TradeResult.LOSS]
    win_rate = round(len(wins) / len(closed) * 100, 1) if closed else 0
    total_pl = sum([t.profit_loss or 0 for t in closed])
    avg_win = round(sum([t.profit_loss or 0 for t in wins]) / len(wins), 2) if wins else 0
    avg_loss = round(sum([t.profit_loss or 0 for t in losses]) / len(losses), 2) if losses else 0

    text = (
        f"📊 *عملکرد من*\n\n"
        f"📈 تعداد کل معاملات: {len(trades)}\n"
        f"✅ معاملات موفق: {len(wins)}\n"
        f"❌ معاملات ناموفق: {len(losses)}\n"
        f"🎯 Win Rate: {win_rate}%\n"
        f"💰 مجموع سود/زیان: {total_pl}\n"
        f"📈 میانگین سود: {avg_win}\n"
        f"📉 میانگین زیان: {avg_loss}\n"
    )
    FeatureGate.consume(user_pk, cfg.FEATURE_PERFORMANCE)
    await send_menu(call, text, kb.back_home())
    await call.answer()


# =============================================================================
# ⚙️ تنظیمات  /  ℹ️ راهنما
# =============================================================================
@router.callback_query(F.data == "menu:settings")
async def cb_settings(call: CallbackQuery):
    with get_session() as s:
        user = s.query(User).filter_by(telegram_id=call.from_user.id).first()
        notif_on = (user.settings or {}).get("notifications", True)
    await send_menu(call, "⚙️ *تنظیمات*", kb.settings_kb(notif_on))
    await call.answer()


@router.callback_query(F.data == "settings:toggle_notif")
async def cb_toggle_notif(call: CallbackQuery):
    with get_session() as s:
        user = s.query(User).filter_by(telegram_id=call.from_user.id).first()
        settings = dict(user.settings or {})
        settings["notifications"] = not settings.get("notifications", True)
        user.settings = settings
        notif_on = settings["notifications"]
    await send_menu(call, "⚙️ *تنظیمات*\n\n✅ به‌روزرسانی شد.", kb.settings_kb(notif_on))
    await call.answer()


@router.callback_query(F.data == "settings:lang")
async def cb_lang(call: CallbackQuery):
    await call.answer("در حال حاضر فقط زبان فارسی پشتیبانی می‌شود.", show_alert=True)


@router.callback_query(F.data == "menu:help")
async def cb_help(call: CallbackQuery):
    support = get_setting("support_username", "@support")
    rules = get_setting("rules_text", "")
    text = (
        "ℹ️ *راهنما*\n\n"
        "از منوی اصلی می‌توانید به تمام امکانات دسترسی داشته باشید.\n"
        "کاربران Free امکان استفاده محدود از هر قابلیت را دارند.\n\n"
        f"{rules}\n\n"
        f"پشتیبانی: {support}"
    )
    await send_menu(call, text, kb.back_home())
    await call.answer()


# =============================================================================
# Fallback: هر متن ناشناخته خارج از FSM
# =============================================================================
@router.message(F.text)
async def fallback_text(message: Message, state: FSMContext):
    current = await state.get_state()
    if current:
        return  # در حال پر کردن یک فرم است؛ Handler مربوطه رسیدگی می‌کند
    get_or_create_user(message.from_user)
    await message.answer("از منوی زیر بخش موردنظر را انتخاب کنید:", reply_markup=kb.main_menu())
