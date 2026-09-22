"""
Admin Web Panel (FastAPI)
===========================
پنل مدیریت تحت وب حرفه‌ای. برای سادگی نگهداری (طبق درخواست کاربر: تعداد فایل کم)،
تمام Templateها به صورت HTML درون همین فایل تولید می‌شوند (به جای پوشه templates/ جدا)،
اما به شکل Modular با یک تابع layout() مشترک.

اجرا: uvicorn admin_panel:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import datetime as dt
import httpx

from sqlalchemy import String, cast
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import URLSafeSerializer, BadSignature

from config import cfg, logger
from database import (
    init_db, get_session, User, Plan, Feature, PaymentMethod, Payment, PaymentStatus,
    Subscription, Symbol, Coupon, Setting, BroadcastLog, log_audit, now,
)
from services import SubscriptionService, PaymentService, get_setting, set_setting

app = FastAPI(title="Trading Platform Admin")
signer = URLSafeSerializer(cfg.SESSION_SECRET, salt="admin-session")

init_db(seed=True)


# =============================================================================
# Layout / Shared UI
# =============================================================================
NAV_ITEMS = [
    ("/", "📊 Dashboard"),
    ("/users", "👥 Users"),
    ("/payments", "💳 Payments"),
    ("/plans", "📦 Plans"),
    ("/features", "🧩 Features"),
    ("/payment-methods", "🏦 Payment Methods"),
    ("/symbols", "🔣 Symbols"),
    ("/coupons", "🎟 Coupons"),
    ("/broadcast", "📢 Broadcast"),
    ("/settings", "⚙️ Settings"),
]


def layout(title: str, body: str, active: str = "/") -> str:
    nav_html = "".join(
        f'<a class="nav-link {"active" if href == active else ""}" href="{href}">{label}</a>'
        for href, label in NAV_ITEMS
    )
    return f"""
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Trading Platform Admin</title>
<style>
  :root {{
    --bg:#0b0f19; --panel:#131a2b; --panel2:#161f33; --border:#243050;
    --text:#e7ecf7; --muted:#94a3c4; --accent:#5b8cff; --accent2:#22c55e;
    --danger:#ef4444; --warn:#f59e0b;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:'Segoe UI',Tahoma,sans-serif; background:var(--bg); color:var(--text); }}
  .layout {{ display:flex; min-height:100vh; }}
  .sidebar {{ width:220px; background:var(--panel); border-left:1px solid var(--border); padding:20px 12px; flex-shrink:0; }}
  .brand {{ font-weight:700; font-size:17px; margin-bottom:20px; padding:0 8px; color:var(--accent); }}
  .nav-link {{ display:block; padding:10px 12px; border-radius:8px; color:var(--muted); text-decoration:none; margin-bottom:4px; font-size:14px; }}
  .nav-link:hover {{ background:var(--panel2); color:var(--text); }}
  .nav-link.active {{ background:var(--accent); color:#fff; }}
  .main {{ flex:1; padding:24px 32px; }}
  h1 {{ font-size:22px; margin:0 0 20px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:14px; margin-bottom:24px; }}
  .card {{ background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:16px; }}
  .card .num {{ font-size:26px; font-weight:700; }}
  .card .lbl {{ color:var(--muted); font-size:13px; margin-top:4px; }}
  table {{ width:100%; border-collapse:collapse; background:var(--panel); border-radius:12px; overflow:hidden; }}
  th, td {{ padding:10px 12px; text-align:right; border-bottom:1px solid var(--border); font-size:13.5px; }}
  th {{ background:var(--panel2); color:var(--muted); font-weight:600; }}
  tr:hover td {{ background:#141c30; }}
  .badge {{ padding:3px 9px; border-radius:20px; font-size:12px; }}
  .badge.pending {{ background:#3a2f0e; color:var(--warn); }}
  .badge.approved {{ background:#0e3a1e; color:var(--accent2); }}
  .badge.rejected {{ background:#3a0e0e; color:var(--danger); }}
  .badge.active {{ background:#0e2f3a; color:#38bdf8; }}
  .btn {{ display:inline-block; padding:7px 14px; border-radius:8px; border:none; cursor:pointer; font-size:13px; text-decoration:none; }}
  .btn-primary {{ background:var(--accent); color:#fff; }}
  .btn-success {{ background:var(--accent2); color:#fff; }}
  .btn-danger {{ background:var(--danger); color:#fff; }}
  .btn-muted {{ background:var(--panel2); color:var(--text); border:1px solid var(--border); }}
  form.inline {{ display:inline; }}
  input, select, textarea {{ background:var(--panel2); border:1px solid var(--border); color:var(--text); border-radius:8px; padding:8px 10px; font-size:14px; width:100%; }}
  label {{ display:block; margin:10px 0 4px; color:var(--muted); font-size:13px; }}
  .form-box {{ background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:20px; max-width:520px; }}
  .row {{ display:flex; gap:10px; }}
  .row > * {{ flex:1; }}
  .top {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; }}
  a {{ color:var(--accent); }}
  .muted {{ color:var(--muted); }}
  .login-wrap {{ display:flex; align-items:center; justify-content:center; height:100vh; }}
</style>
</head>
<body>
<div class="layout">
  <div class="sidebar">
    <div class="brand">⚡ Trading Platform</div>
    {nav_html}
  </div>
  <div class="main">
    {body}
  </div>
</div>
</body>
</html>
"""


def login_page(error: str = "") -> str:
    err_html = f'<p style="color:#ef4444">{error}</p>' if error else ""
    return f"""
<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<title>Login · Admin</title>
<style>
 body{{background:#0b0f19;color:#e7ecf7;font-family:Tahoma,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
 .box{{background:#131a2b;border:1px solid #243050;padding:32px;border-radius:14px;width:320px}}
 h2{{margin-top:0}}
 input{{width:100%;padding:10px;margin:8px 0;border-radius:8px;border:1px solid #243050;background:#161f33;color:#fff}}
 button{{width:100%;padding:10px;border-radius:8px;border:none;background:#5b8cff;color:#fff;font-size:15px;cursor:pointer;margin-top:10px}}
</style></head><body>
<div class="box">
  <h2>⚡ ورود به پنل مدیریت</h2>
  {err_html}
  <form method="post" action="/login">
    <input name="username" placeholder="نام کاربری" required>
    <input name="password" type="password" placeholder="رمز عبور" required>
    <button type="submit">ورود</button>
  </form>
</div>
</body></html>
"""


def require_admin(request: Request):
    token = request.cookies.get("admin_session")
    if not token:
        raise HTTPException(status_code=303, detail="redirect")
    try:
        data = signer.loads(token)
        if data.get("u") != cfg.ADMIN_USERNAME:
            raise HTTPException(status_code=303, detail="redirect")
    except BadSignature:
        raise HTTPException(status_code=303, detail="redirect")
    return True


@app.exception_handler(HTTPException)
async def auth_redirect(request: Request, exc: HTTPException):
    if exc.status_code == 303:
        return RedirectResponse("/login")
    return HTMLResponse(str(exc.detail), status_code=exc.status_code)


# =============================================================================
# Auth
# =============================================================================
@app.get("/login", response_class=HTMLResponse)
async def login_form():
    return login_page()


@app.post("/login")
async def login_submit(username: str = Form(...), password: str = Form(...)):
    if username == cfg.ADMIN_USERNAME and password == cfg.ADMIN_PASSWORD:
        token = signer.dumps({"u": username})
        resp = RedirectResponse("/", status_code=302)
        resp.set_cookie("admin_session", token, httponly=True, max_age=60 * 60 * 24 * 7)
        log_audit("admin:web", "admin_login", {})
        return resp
    return HTMLResponse(login_page("نام کاربری یا رمز عبور اشتباه است."))


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login")
    resp.delete_cookie("admin_session")
    return resp


# =============================================================================
# Dashboard
# =============================================================================
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, _=Depends(require_admin)):
    with get_session() as s:
        total_users = s.query(User).count()
        active_subs = s.query(Subscription).filter(
            Subscription.is_active == True, Subscription.end_date > now()
        ).count()
        expired_subs = s.query(Subscription).filter(Subscription.end_date <= now()).count()
        pending_payments = s.query(Payment).filter_by(status=PaymentStatus.PENDING).count()
        approved_payments = s.query(Payment).filter_by(status=PaymentStatus.APPROVED).all()
        revenue = sum(p.amount for p in approved_payments)
        this_month = [p for p in approved_payments if p.reviewed_at and p.reviewed_at.month == now().month]
        monthly_revenue = sum(p.amount for p in this_month)
        new_users_week = s.query(User).filter(User.joined_at >= now() - dt.timedelta(days=7)).count()

    cards = [
        ("Total Users", total_users), ("New Users (7d)", new_users_week),
        ("Active Subscriptions", active_subs), ("Expired Subscriptions", expired_subs),
        ("Pending Payments", pending_payments), ("Total Revenue", f"{int(revenue):,}"),
        ("Monthly Revenue", f"{int(monthly_revenue):,}"),
    ]
    cards_html = "".join(f'<div class="card"><div class="num">{v}</div><div class="lbl">{k}</div></div>' for k, v in cards)
    body = f'<h1>📊 Dashboard</h1><div class="cards">{cards_html}</div>'
    return layout("Dashboard", body, "/")


# =============================================================================
# Users
# =============================================================================
@app.get("/users", response_class=HTMLResponse)
async def users_list(request: Request, q: str = "", _=Depends(require_admin)):
    with get_session() as s:
        query = s.query(User)
        if q:
            like = f"%{q}%"
            query = query.filter((User.username.like(like)) | (User.first_name.like(like)) |
                                  (cast(User.telegram_id, String).like(like)))
        users = query.order_by(User.id.desc()).limit(200).all()
        rows = ""
        for u in users:
            sub = u.active_subscription
            sub_badge = f'<span class="badge active">{sub.plan.name}</span>' if sub else '<span class="muted">Free</span>'
            ban_badge = '<span class="badge rejected">Banned</span>' if u.is_banned else '<span class="badge approved">Active</span>'
            rows += f"""<tr>
              <td>{u.id}</td><td>{u.full_name}</td><td>@{u.username or '-'}</td>
              <td>{u.telegram_id}</td><td>{sub_badge}</td><td>{ban_badge}</td>
              <td><a class="btn btn-muted" href="/users/{u.id}">مشاهده</a></td>
            </tr>"""
    body = f"""
    <h1>👥 Users</h1>
    <form method="get" style="margin-bottom:14px;max-width:340px">
      <input name="q" placeholder="جستجو با نام، یوزرنیم یا آیدی" value="{q}">
    </form>
    <table><tr><th>ID</th><th>نام</th><th>Username</th><th>Telegram ID</th><th>اشتراک</th><th>وضعیت</th><th></th></tr>{rows}</table>
    """
    return layout("Users", body, "/users")


@app.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail(request: Request, user_id: int, _=Depends(require_admin)):
    with get_session() as s:
        u = s.get(User, user_id)
        if not u:
            return HTMLResponse("Not found", status_code=404)
        plans = s.query(Plan).order_by(Plan.sort_order).all()
        plan_options = "".join(f'<option value="{p.id}">{p.name}</option>' for p in plans)
        payments = u.payments[:10]
        pay_rows = "".join(
            f"<tr><td>{p.payment_uid[:8]}</td><td>{p.plan.name}</td><td>{int(p.amount):,}</td>"
            f"<td><span class='badge {p.status.value}'>{p.status.value}</span></td>"
            f"<td>{p.created_at.strftime('%Y-%m-%d')}</td></tr>"
            for p in payments
        )
        sub = u.active_subscription
        sub_info = f"{sub.plan.name} تا {sub.end_date.strftime('%Y-%m-%d')}" if sub else "Free"

    body = f"""
    <h1>👤 {u.full_name}</h1>
    <div class="cards">
      <div class="card"><div class="num">{u.telegram_id}</div><div class="lbl">Telegram ID</div></div>
      <div class="card"><div class="num">{sub_info}</div><div class="lbl">اشتراک فعلی</div></div>
      <div class="card"><div class="num">{'مسدود' if u.is_banned else 'فعال'}</div><div class="lbl">وضعیت</div></div>
    </div>

    <div style="display:flex; gap:20px; flex-wrap:wrap;">
      <div class="form-box">
        <h3>مدیریت حساب</h3>
        <form method="post" action="/users/{u.id}/ban">
          <button class="btn {'btn-success' if u.is_banned else 'btn-danger'}">
            {'✅ رفع مسدودیت' if u.is_banned else '⛔️ مسدود کردن کاربر'}
          </button>
        </form>
      </div>

      <div class="form-box">
        <h3>🎁 تنظیم/تمدید اشتراک</h3>
        <form method="post" action="/users/{u.id}/subscription">
          <label>Plan</label>
          <select name="plan_id">{plan_options}</select>
          <label>تعداد روز</label>
          <input name="days" type="number" value="30">
          <button class="btn btn-primary" style="margin-top:12px">اعمال</button>
        </form>
      </div>
    </div>

    <h3 style="margin-top:24px">تاریخچه پرداخت‌ها</h3>
    <table><tr><th>Payment ID</th><th>Plan</th><th>مبلغ</th><th>وضعیت</th><th>تاریخ</th></tr>{pay_rows}</table>
    """
    return layout(f"User #{user_id}", body, "/users")


@app.post("/users/{user_id}/ban")
async def toggle_ban(user_id: int, _=Depends(require_admin)):
    with get_session() as s:
        u = s.get(User, user_id)
        u.is_banned = not u.is_banned
    log_audit("admin:web", "user_ban_toggled", {"user_id": user_id})
    return RedirectResponse(f"/users/{user_id}", status_code=302)


@app.post("/users/{user_id}/subscription")
async def set_subscription(user_id: int, plan_id: int = Form(...), days: int = Form(30), _=Depends(require_admin)):
    with get_session() as s:
        u = s.get(User, user_id)
        plan = s.get(Plan, plan_id)
        s.add(Subscription(user_id=user_id, plan_id=plan_id, start_date=now(),
                            end_date=now() + dt.timedelta(days=days), is_active=True))
    log_audit("admin:web", "subscription_set_manually", {"user_id": user_id, "plan_id": plan_id, "days": days})
    return RedirectResponse(f"/users/{user_id}", status_code=302)


# =============================================================================
# Payments
# =============================================================================
@app.get("/payments", response_class=HTMLResponse)
async def payments_list(request: Request, status: str = "", _=Depends(require_admin)):
    with get_session() as s:
        query = s.query(Payment)
        if status:
            query = query.filter_by(status=PaymentStatus(status))
        payments = query.order_by(Payment.id.desc()).limit(300).all()
        rows = ""
        for p in payments:
            rows += f"""<tr>
              <td>{p.payment_uid[:8]}</td><td>{p.user.full_name}</td><td>{p.plan.name}</td>
              <td>{int(p.amount):,} {p.currency}</td><td>{p.method_key}</td>
              <td><span class="badge {p.status.value}">{p.status.value}</span></td>
              <td>{p.created_at.strftime('%Y-%m-%d %H:%M')}</td>
              <td><a class="btn btn-muted" href="/payments/{p.id}">مشاهده</a></td>
            </tr>"""
    filters = "".join(
        f'<a class="btn {"btn-primary" if status==s_ else "btn-muted"}" href="/payments?status={s_}">{s_ or "همه"}</a> '
        for s_ in ["", "pending", "approved", "rejected", "expired"]
    )
    body = f"<h1>💳 Payments</h1><div style='margin-bottom:14px'>{filters}</div><table>" \
           f"<tr><th>ID</th><th>کاربر</th><th>پلن</th><th>مبلغ</th><th>روش</th><th>وضعیت</th><th>تاریخ</th><th></th></tr>{rows}</table>"
    return layout("Payments", body, "/payments")


@app.get("/payments/{payment_id}", response_class=HTMLResponse)
async def payment_detail(request: Request, payment_id: int, _=Depends(require_admin)):
    with get_session() as s:
        p = s.get(Payment, payment_id)
        if not p:
            return HTMLResponse("Not found", status_code=404)
        plans = s.query(Plan).filter_by(is_active=True).order_by(Plan.sort_order).all()
        plan_options = "".join(
            f'<option value="{pl.id}" {"selected" if pl.id==p.plan_id else ""}>{pl.name}</option>' for pl in plans
        )
        actions = ""
        if p.status == PaymentStatus.PENDING:
            actions = f"""
            <form method="post" action="/payments/{p.id}/approve" style="margin-top:10px">
              <label>پلنی که باید فعال شود</label>
              <select name="plan_id">{plan_options}</select>
              <button class="btn btn-success" style="margin-top:10px">✅ تأیید پرداخت</button>
            </form>
            <form method="post" action="/payments/{p.id}/reject" style="margin-top:14px">
              <label>دلیل رد شدن</label>
              <textarea name="reason" rows="2"></textarea>
              <button class="btn btn-danger" style="margin-top:10px">❌ رد پرداخت</button>
            </form>
            """
        receipt_html = f'<img src="/receipt/{p.id}" style="max-width:320px;border-radius:10px;border:1px solid #243050">' \
            if p.receipt_file_id else '<span class="muted">رسیدی ارسال نشده</span>'

    body = f"""
    <h1>🧾 Payment #{p.payment_uid[:8]}</h1>
    <div class="form-box">
      <p><b>کاربر:</b> {p.user.full_name} (@{p.user.username or '-'}) — <a href="/users/{p.user_id}">مشاهده پروفایل</a></p>
      <p><b>پلن درخواستی:</b> {p.plan.name}</p>
      <p><b>مبلغ:</b> {int(p.amount):,} {p.currency}</p>
      <p><b>روش پرداخت:</b> {p.method_key}</p>
      <p><b>TX Hash / توضیح:</b> {p.tx_hash or p.user_note or '-'}</p>
      <p><b>وضعیت:</b> <span class="badge {p.status.value}">{p.status.value}</span></p>
      <p><b>رسید:</b><br>{receipt_html}</p>
      {actions}
    </div>
    """
    return layout(f"Payment #{payment_id}", body, "/payments")


@app.post("/payments/{payment_id}/approve")
async def approve_payment(payment_id: int, plan_id: int = Form(...), _=Depends(require_admin)):
    with get_session() as s:
        p = s.get(Payment, payment_id)
        if p.status != PaymentStatus.PENDING:
            return RedirectResponse(f"/payments/{payment_id}", status_code=302)
    PaymentService.approve(payment_id, plan_id, admin_telegram_id=0)
    with get_session() as s:
        p = s.get(Payment, payment_id)
        user_tg = s.get(User, p.user_id).telegram_id
    await _notify_telegram(user_tg, "🎉 پرداخت شما توسط ادمین (پنل وب) تأیید شد و اشتراک فعال گردید.")
    return RedirectResponse(f"/payments/{payment_id}", status_code=302)


@app.post("/payments/{payment_id}/reject")
async def reject_payment(payment_id: int, reason: str = Form(""), _=Depends(require_admin)):
    PaymentService.reject(payment_id, reason, admin_telegram_id=0)
    with get_session() as s:
        p = s.get(Payment, payment_id)
        user_tg = s.get(User, p.user_id).telegram_id
    await _notify_telegram(user_tg, f"❌ پرداخت شما رد شد.\nدلیل: {reason}")
    return RedirectResponse(f"/payments/{payment_id}", status_code=302)


@app.get("/receipt/{payment_id}")
async def receipt_redirect(payment_id: int, _=Depends(require_admin)):
    """رسید مستقیما از تلگرام سرو نمی‌شود (نیاز به دانلود از Bot API)؛ این Endpoint file_id را برمی‌گرداند."""
    with get_session() as s:
        p = s.get(Payment, payment_id)
        file_id = p.receipt_file_id
    if not file_id or not cfg.BOT_TOKEN:
        return HTMLResponse("رسید در دسترس نیست")
    async with httpx.AsyncClient() as client:
        r = await client.get(f"https://api.telegram.org/bot{cfg.BOT_TOKEN}/getFile", params={"file_id": file_id})
        path = r.json().get("result", {}).get("file_path")
    if not path:
        return HTMLResponse("رسید در دسترس نیست")
    return RedirectResponse(f"https://api.telegram.org/file/bot{cfg.BOT_TOKEN}/{path}")


async def _notify_telegram(chat_id: int, text: str):
    if not cfg.BOT_TOKEN:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"https://api.telegram.org/bot{cfg.BOT_TOKEN}/sendMessage",
                               json={"chat_id": chat_id, "text": text})
    except Exception as e:
        logger.error(f"notify_telegram failed: {e}")


# =============================================================================
# Plans CRUD
# =============================================================================
@app.get("/plans", response_class=HTMLResponse)
async def plans_list(_=Depends(require_admin)):
    with get_session() as s:
        plans = s.query(Plan).order_by(Plan.sort_order).all()
        rows = "".join(f"""<tr>
          <td>{p.id}</td><td>{p.name}</td><td>{int(p.price):,} {p.currency}</td><td>{p.duration_days} روز</td>
          <td>{'✅' if p.is_active else '❌'}</td>
          <td>
            <form class="inline" method="post" action="/plans/{p.id}/toggle"><button class="btn btn-muted">Toggle</button></form>
            <a class="btn btn-muted" href="/plans/{p.id}/edit">ویرایش</a>
          </td></tr>""" for p in plans)
    body = f"""
    <div class="top"><h1>📦 Plans</h1><a class="btn btn-primary" href="/plans/new">+ Plan جدید</a></div>
    <table><tr><th>ID</th><th>نام</th><th>قیمت</th><th>مدت</th><th>فعال</th><th></th></tr>{rows}</table>
    """
    return layout("Plans", body, "/plans")


def plan_form(plan=None) -> str:
    action = f"/plans/{plan.id}/edit" if plan else "/plans/new"
    return f"""
    <div class="form-box">
      <form method="post" action="{action}">
        <label>نام Plan</label><input name="name" value="{plan.name if plan else ''}" required>
        <div class="row">
          <div><label>قیمت</label><input name="price" type="number" step="0.01" value="{plan.price if plan else 0}"></div>
          <div><label>ارز</label><input name="currency" value="{plan.currency if plan else 'IRT'}"></div>
        </div>
        <label>مدت (روز)</label><input name="duration_days" type="number" value="{plan.duration_days if plan else 30}">
        <label>توضیحات</label><textarea name="description" rows="2">{plan.description if plan else ''}</textarea>
        <label>امکانات (هر خط یک مورد)</label><textarea name="features_text" rows="4">{plan.features_text if plan else ''}</textarea>
        <label>ترتیب نمایش</label><input name="sort_order" type="number" value="{plan.sort_order if plan else 0}">
        <button class="btn btn-primary" style="margin-top:14px">ذخیره</button>
      </form>
    </div>
    """


@app.get("/plans/new", response_class=HTMLResponse)
async def plan_new_form(_=Depends(require_admin)):
    return layout("New Plan", f"<h1>📦 Plan جدید</h1>{plan_form()}", "/plans")


@app.post("/plans/new")
async def plan_new_submit(name: str = Form(...), price: float = Form(0), currency: str = Form("IRT"),
                           duration_days: int = Form(30), description: str = Form(""),
                           features_text: str = Form(""), sort_order: int = Form(0),
                           _=Depends(require_admin)):
    with get_session() as s:
        s.add(Plan(name=name, price=price, currency=currency, duration_days=duration_days,
                    description=description, features_text=features_text, sort_order=sort_order, is_active=True))
    return RedirectResponse("/plans", status_code=302)


@app.get("/plans/{plan_id}/edit", response_class=HTMLResponse)
async def plan_edit_form(plan_id: int, _=Depends(require_admin)):
    with get_session() as s:
        plan = s.get(Plan, plan_id)
    return layout("Edit Plan", f"<h1>ویرایش {plan.name}</h1>{plan_form(plan)}", "/plans")


@app.post("/plans/{plan_id}/edit")
async def plan_edit_submit(plan_id: int, name: str = Form(...), price: float = Form(0), currency: str = Form("IRT"),
                            duration_days: int = Form(30), description: str = Form(""),
                            features_text: str = Form(""), sort_order: int = Form(0),
                            _=Depends(require_admin)):
    with get_session() as s:
        plan = s.get(Plan, plan_id)
        plan.name, plan.price, plan.currency = name, price, currency
        plan.duration_days, plan.description = duration_days, description
        plan.features_text, plan.sort_order = features_text, sort_order
    return RedirectResponse("/plans", status_code=302)


@app.post("/plans/{plan_id}/toggle")
async def plan_toggle(plan_id: int, _=Depends(require_admin)):
    with get_session() as s:
        plan = s.get(Plan, plan_id)
        plan.is_active = not plan.is_active
    return RedirectResponse("/plans", status_code=302)


# =============================================================================
# Features
# =============================================================================
@app.get("/features", response_class=HTMLResponse)
async def features_list(_=Depends(require_admin)):
    with get_session() as s:
        features = s.query(Feature).all()
        rows = "".join(f"""<tr>
          <td>{f.name}</td><td>{f.key}</td>
          <td>{'نامحدود' if f.free_limit is None else f.free_limit}</td>
          <td>{'✅ فعال' if f.is_enabled else '❌ غیرفعال'}</td>
          <td>
            <form class="inline" method="post" action="/features/{f.id}/update">
              <input style="width:80px;display:inline-block" name="free_limit" value="{'' if f.free_limit is None else f.free_limit}" placeholder="خالی=نامحدود">
              <button class="btn btn-primary">ذخیره حد مجاز</button>
            </form>
            <form class="inline" method="post" action="/features/{f.id}/toggle"><button class="btn btn-muted">Toggle</button></form>
          </td></tr>""" for f in features)
    body = f"<h1>🧩 Features</h1><table><tr><th>نام</th><th>Key</th><th>Free Limit</th><th>وضعیت</th><th>عملیات</th></tr>{rows}</table>"
    return layout("Features", body, "/features")


@app.post("/features/{feature_id}/toggle")
async def feature_toggle(feature_id: int, _=Depends(require_admin)):
    with get_session() as s:
        f = s.get(Feature, feature_id)
        f.is_enabled = not f.is_enabled
    return RedirectResponse("/features", status_code=302)


@app.post("/features/{feature_id}/update")
async def feature_update(feature_id: int, free_limit: str = Form(""), _=Depends(require_admin)):
    with get_session() as s:
        f = s.get(Feature, feature_id)
        f.free_limit = int(free_limit) if free_limit.strip() != "" else None
    return RedirectResponse("/features", status_code=302)


# =============================================================================
# Payment Methods
# =============================================================================
@app.get("/payment-methods", response_class=HTMLResponse)
async def payment_methods_list(_=Depends(require_admin)):
    with get_session() as s:
        methods = s.query(PaymentMethod).order_by(PaymentMethod.sort_order).all()
        rows = ""
        for m in methods:
            cfg_pairs = "<br>".join(f"{k}: {v}" for k, v in (m.config or {}).items())
            rows += f"""<tr><td>{m.name}</td><td style="font-size:12px">{cfg_pairs}</td>
              <td>{'✅' if m.is_active else '❌'}</td>
              <td><a class="btn btn-muted" href="/payment-methods/{m.id}/edit">ویرایش</a>
              <form class="inline" method="post" action="/payment-methods/{m.id}/toggle"><button class="btn btn-muted">Toggle</button></form></td></tr>"""
    body = f"<h1>🏦 Payment Methods</h1><table><tr><th>نام</th><th>تنظیمات</th><th>فعال</th><th></th></tr>{rows}</table>"
    return layout("Payment Methods", body, "/payment-methods")


@app.get("/payment-methods/{method_id}/edit", response_class=HTMLResponse)
async def payment_method_edit_form(method_id: int, _=Depends(require_admin)):
    with get_session() as s:
        m = s.get(PaymentMethod, method_id)
        cfg_data = m.config or {}
    fields = "".join(
        f'<label>{k}</label><input name="cfg_{k}" value="{v}">' for k, v in cfg_data.items()
    )
    body = f"""
    <h1>ویرایش {m.name}</h1>
    <div class="form-box">
      <form method="post" action="/payment-methods/{method_id}/edit">
        {fields}
        <button class="btn btn-primary" style="margin-top:14px">ذخیره</button>
      </form>
    </div>
    """
    return layout("Edit Payment Method", body, "/payment-methods")


@app.post("/payment-methods/{method_id}/edit")
async def payment_method_edit_submit(method_id: int, request: Request, _=Depends(require_admin)):
    form = await request.form()
    with get_session() as s:
        m = s.get(PaymentMethod, method_id)
        new_cfg = dict(m.config or {})
        for k, v in form.items():
            if k.startswith("cfg_"):
                new_cfg[k[4:]] = v
        m.config = new_cfg
    return RedirectResponse("/payment-methods", status_code=302)


@app.post("/payment-methods/{method_id}/toggle")
async def payment_method_toggle(method_id: int, _=Depends(require_admin)):
    with get_session() as s:
        m = s.get(PaymentMethod, method_id)
        m.is_active = not m.is_active
    return RedirectResponse("/payment-methods", status_code=302)


# =============================================================================
# Symbols
# =============================================================================
@app.get("/symbols", response_class=HTMLResponse)
async def symbols_list(_=Depends(require_admin)):
    with get_session() as s:
        symbols = s.query(Symbol).order_by(Symbol.id).all()
        rows = "".join(f"""<tr><td>{sy.symbol}</td><td>{sy.exchange}</td>
          <td>{'✅' if sy.is_active else '❌'}</td><td>{'⭐' if sy.is_favorite else '-'}</td>
          <td><form class="inline" method="post" action="/symbols/{sy.id}/toggle"><button class="btn btn-muted">فعال/غیرفعال</button></form>
              <form class="inline" method="post" action="/symbols/{sy.id}/favorite"><button class="btn btn-muted">⭐ Favorite</button></form></td></tr>"""
                        for sy in symbols)
    body = f"""
    <div class="top"><h1>🔣 Symbols</h1></div>
    <div class="form-box">
      <form method="post" action="/symbols/add">
        <div class="row">
          <div><label>Base (مثل BTC)</label><input name="base" required></div>
          <div><label>Quote (مثل USDT)</label><input name="quote" required></div>
        </div>
        <label>Exchange</label><input name="exchange" value="{cfg.CCXT_EXCHANGE}">
        <button class="btn btn-primary" style="margin-top:10px">+ افزودن نماد</button>
      </form>
    </div>
    <br>
    <table><tr><th>Symbol</th><th>Exchange</th><th>فعال</th><th>Favorite</th><th></th></tr>{rows}</table>
    """
    return layout("Symbols", body, "/symbols")


@app.post("/symbols/add")
async def symbol_add(base: str = Form(...), quote: str = Form(...), exchange: str = Form(...), _=Depends(require_admin)):
    with get_session() as s:
        s.add(Symbol(exchange=exchange, symbol=f"{base.upper()}/{quote.upper()}",
                      base=base.upper(), quote=quote.upper(), is_active=True))
    return RedirectResponse("/symbols", status_code=302)


@app.post("/symbols/{symbol_id}/toggle")
async def symbol_toggle(symbol_id: int, _=Depends(require_admin)):
    with get_session() as s:
        sy = s.get(Symbol, symbol_id)
        sy.is_active = not sy.is_active
    return RedirectResponse("/symbols", status_code=302)


@app.post("/symbols/{symbol_id}/favorite")
async def symbol_favorite(symbol_id: int, _=Depends(require_admin)):
    with get_session() as s:
        sy = s.get(Symbol, symbol_id)
        sy.is_favorite = not sy.is_favorite
    return RedirectResponse("/symbols", status_code=302)


# =============================================================================
# Coupons
# =============================================================================
@app.get("/coupons", response_class=HTMLResponse)
async def coupons_list(_=Depends(require_admin)):
    with get_session() as s:
        coupons = s.query(Coupon).all()
        rows = "".join(f"""<tr><td>{c.code}</td><td>{c.discount_percent or ''}{'%' if c.discount_percent else ''}
          {c.discount_amount or ''}</td><td>{c.used_count}/{c.max_uses or '∞'}</td>
          <td>{'✅' if c.is_active else '❌'}</td>
          <td><form class="inline" method="post" action="/coupons/{c.id}/toggle"><button class="btn btn-muted">Toggle</button></form></td></tr>"""
                        for c in coupons)
    body = f"""
    <div class="top"><h1>🎟 Coupons</h1></div>
    <div class="form-box">
      <form method="post" action="/coupons/add">
        <label>کد</label><input name="code" required>
        <div class="row">
          <div><label>درصد تخفیف</label><input name="discount_percent" type="number" step="0.01"></div>
          <div><label>مبلغ ثابت تخفیف</label><input name="discount_amount" type="number" step="0.01"></div>
        </div>
        <label>حداکثر استفاده</label><input name="max_uses" type="number">
        <button class="btn btn-primary" style="margin-top:10px">+ ایجاد کوپن</button>
      </form>
    </div><br>
    <table><tr><th>کد</th><th>تخفیف</th><th>استفاده</th><th>فعال</th><th></th></tr>{rows}</table>
    """
    return layout("Coupons", body, "/coupons")


@app.post("/coupons/add")
async def coupon_add(code: str = Form(...), discount_percent: str = Form(""), discount_amount: str = Form(""),
                      max_uses: str = Form(""), _=Depends(require_admin)):
    with get_session() as s:
        s.add(Coupon(
            code=code.upper(),
            discount_percent=float(discount_percent) if discount_percent else None,
            discount_amount=float(discount_amount) if discount_amount else None,
            max_uses=int(max_uses) if max_uses else None,
            is_active=True,
        ))
    return RedirectResponse("/coupons", status_code=302)


@app.post("/coupons/{coupon_id}/toggle")
async def coupon_toggle(coupon_id: int, _=Depends(require_admin)):
    with get_session() as s:
        c = s.get(Coupon, coupon_id)
        c.is_active = not c.is_active
    return RedirectResponse("/coupons", status_code=302)


# =============================================================================
# Broadcast
# =============================================================================
@app.get("/broadcast", response_class=HTMLResponse)
async def broadcast_form(_=Depends(require_admin)):
    with get_session() as s:
        logs = s.query(BroadcastLog).order_by(BroadcastLog.id.desc()).limit(10).all()
        rows = "".join(f"<tr><td>{l.segment}</td><td>{l.sent_count}</td><td>{l.failed_count}</td>"
                        f"<td>{l.created_at.strftime('%Y-%m-%d %H:%M')}</td></tr>" for l in logs)
    body = f"""
    <h1>📢 Broadcast</h1>
    <div class="form-box">
      <form method="post" action="/broadcast">
        <label>مخاطبین</label>
        <select name="segment">
          <option value="all">همه کاربران</option>
          <option value="free">فقط Free</option>
          <option value="member">فقط دارای اشتراک</option>
          <option value="expired">اشتراک منقضی‌شده</option>
        </select>
        <label>متن پیام</label>
        <textarea name="message" rows="5" required></textarea>
        <button class="btn btn-primary" style="margin-top:10px">ارسال Broadcast</button>
      </form>
    </div>
    <h3 style="margin-top:24px">تاریخچه ارسال</h3>
    <table><tr><th>گروه</th><th>موفق</th><th>ناموفق</th><th>تاریخ</th></tr>{rows}</table>
    """
    return layout("Broadcast", body, "/broadcast")


@app.post("/broadcast")
async def broadcast_send(segment: str = Form(...), message: str = Form(...), _=Depends(require_admin)):
    with get_session() as s:
        users = s.query(User).filter_by(is_banned=False).all()
        targets = []
        for u in users:
            has_sub = u.active_subscription is not None
            if segment == "all" or (segment == "free" and not has_sub) or \
               (segment == "member" and has_sub) or \
               (segment == "expired" and not has_sub and len(u.subscriptions) > 0):
                targets.append(u.telegram_id)

    sent, failed = 0, 0
    if cfg.BOT_TOKEN:
        async with httpx.AsyncClient() as client:
            for tg_id in targets:
                try:
                    r = await client.post(f"https://api.telegram.org/bot{cfg.BOT_TOKEN}/sendMessage",
                                           json={"chat_id": tg_id, "text": message})
                    if r.json().get("ok"):
                        sent += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1

    with get_session() as s:
        s.add(BroadcastLog(segment=segment, message=message, sent_count=sent, failed_count=failed))
    log_audit("admin:web", "broadcast_sent", {"segment": segment, "sent": sent, "failed": failed})
    return RedirectResponse("/broadcast", status_code=302)


# =============================================================================
# Settings
# =============================================================================
SETTINGS_KEYS = ["bot_name", "welcome_message", "expired_message", "rules_text", "support_username"]


@app.get("/settings", response_class=HTMLResponse)
async def settings_form(_=Depends(require_admin)):
    fields = ""
    for key in SETTINGS_KEYS:
        val = get_setting(key, "")
        fields += f'<label>{key}</label><textarea name="{key}" rows="2">{val}</textarea>'
    body = f"""
    <h1>⚙️ Settings</h1>
    <div class="form-box" style="max-width:640px">
      <form method="post" action="/settings">
        {fields}
        <button class="btn btn-primary" style="margin-top:14px">ذخیره تنظیمات</button>
      </form>
    </div>
    """
    return layout("Settings", body, "/settings")


@app.post("/settings")
async def settings_save(request: Request, _=Depends(require_admin)):
    form = await request.form()
    for key in SETTINGS_KEYS:
        if key in form:
            set_setting(key, form[key])
    return RedirectResponse("/settings", status_code=302)
