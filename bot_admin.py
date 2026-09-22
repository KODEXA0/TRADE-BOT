"""
Bot Admin Handlers
====================
عملیات مدیریتی که مستقیما از داخل تلگرام قابل انجام است:
تأیید/رد پرداخت، تغییر Plan هنگام تأیید، مشاهده پروفایل کاربر.
(مدیریت کامل‌تر - از جمله Plans/Features/Broadcast/Coupons - در Admin Panel وب است.)
"""
from __future__ import annotations

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import CallbackQuery, Message

import keyboards as kb
from config import cfg, logger
from database import get_session, User, Payment, Plan, PaymentStatus
from services import PaymentService

router = Router(name="admin")


def is_admin(telegram_id: int) -> bool:
    if telegram_id in cfg.ADMIN_IDS:
        return True
    with get_session() as s:
        u = s.query(User).filter_by(telegram_id=telegram_id).first()
        return bool(u and u.is_admin)


class RejectFlow(StatesGroup):
    waiting_reason = State()


@router.callback_query(F.data.startswith("adm_"))
async def admin_guard(call: CallbackQuery, state: FSMContext, bot: Bot):
    if not is_admin(call.from_user.id):
        return await call.answer("⛔️ دسترسی ندارید.", show_alert=True)

    action, *rest = call.data.split(":")

    if action == "adm_approve":
        payment_id = int(rest[0])
        with get_session() as s:
            payment = s.get(Payment, payment_id)
            if not payment or payment.status != PaymentStatus.PENDING:
                return await call.answer("این پرداخت قبلا بررسی شده است.", show_alert=True)
            plans = s.query(Plan).filter_by(is_active=True).order_by(Plan.sort_order).all()
            plans = [(p.id, p.name) for p in plans]

        class P:
            def __init__(self, id, name):
                self.id, self.name = id, name

        await call.message.answer(
            "پلنی که باید برای کاربر فعال شود را انتخاب کنید:",
            reply_markup=kb.admin_choose_plan_kb(payment_id, [P(*p) for p in plans]),
        )
        return await call.answer()

    if action == "adm_setplan":
        payment_id, plan_id = int(rest[0]), int(rest[1])
        PaymentService.approve(payment_id, plan_id, call.from_user.id)
        with get_session() as s:
            payment = s.get(Payment, payment_id)
            user = s.get(User, payment.user_id)
            plan = s.get(Plan, plan_id)
            user_tg_id = user.telegram_id
            plan_name = plan.name
            end_date = user.active_subscription.end_date.strftime("%Y-%m-%d") if user.active_subscription else "-"

        await call.message.answer(f"✅ پرداخت تأیید و پلن *{plan_name}* فعال شد.", parse_mode="Markdown")
        try:
            await bot.send_message(
                user_tg_id,
                f"🎉 پرداخت شما تأیید شد!\n\n📦 پلن: {plan_name}\n📅 تا تاریخ: {end_date}\n\n"
                "اکنون به تمام امکانات دسترسی دارید.",
                reply_markup=kb.home_only(),
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_tg_id}: {e}")
        return await call.answer()

    if action == "adm_reject":
        payment_id = int(rest[0])
        await state.set_state(RejectFlow.waiting_reason)
        await state.update_data(payment_id=payment_id)
        await call.message.answer("دلیل رد کردن پرداخت را بنویسید:")
        return await call.answer()

    if action == "adm_changeplan":
        payment_id = int(rest[0])
        with get_session() as s:
            plans = s.query(Plan).filter_by(is_active=True).order_by(Plan.sort_order).all()
            plans = [(p.id, p.name) for p in plans]

        class P:
            def __init__(self, id, name):
                self.id, self.name = id, name

        await call.message.answer("پلن جدید را انتخاب کنید:",
                                    reply_markup=kb.admin_choose_plan_kb(payment_id, [P(*p) for p in plans]))
        return await call.answer()

    if action == "adm_profile":
        payment_id = int(rest[0])
        with get_session() as s:
            payment = s.get(Payment, payment_id)
            user = s.get(User, payment.user_id)
            sub = user.active_subscription
            text = (
                f"👤 *پروفایل کاربر*\n\n"
                f"نام: {user.full_name}\n"
                f"Username: @{user.username or '-'}\n"
                f"Telegram ID: `{user.telegram_id}`\n"
                f"عضویت: {user.joined_at.strftime('%Y-%m-%d')}\n"
                f"وضعیت: {'مسدود' if user.is_banned else 'فعال'}\n"
                f"اشتراک: {sub.plan.name + ' تا ' + sub.end_date.strftime('%Y-%m-%d') if sub else 'Free'}\n"
                f"تعداد کل پرداخت‌ها: {len(user.payments)}\n"
            )
        await call.message.answer(text, parse_mode="Markdown")
        return await call.answer()


@router.message(RejectFlow.waiting_reason, F.text)
async def admin_reject_reason(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    payment_id = data["payment_id"]
    reason = message.text.strip()
    PaymentService.reject(payment_id, reason, message.from_user.id)

    with get_session() as s:
        payment = s.get(Payment, payment_id)
        user = s.get(User, payment.user_id)
        user_tg_id = user.telegram_id

    await state.clear()
    await message.answer("❌ پرداخت رد شد و کاربر مطلع شد.")
    try:
        await bot.send_message(
            user_tg_id,
            f"❌ متاسفانه پرداخت شما تأیید نشد.\n\n📝 دلیل: {reason}\n\n"
            "در صورت نیاز می‌توانید مجددا اقدام به پرداخت کنید.",
            reply_markup=kb.upsell_kb(),
        )
    except Exception as e:
        logger.error(f"Failed to notify user {user_tg_id} of rejection: {e}")


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    with get_session() as s:
        pending = s.query(Payment).filter_by(status=PaymentStatus.PENDING).count()
        users = s.query(User).count()
    await message.answer(
        f"🛠 *پنل مدیریت سریع*\n\nکاربران: {users}\nپرداخت‌های در انتظار: {pending}\n\n"
        f"برای مدیریت کامل به Admin Panel وب مراجعه کنید.",
        parse_mode="Markdown",
    )
