"""Billing engine trigger and the finance dashboard / reports."""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import extract, func
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Invoice, Payment, Plan, Subscription, SubscriptionLine, User
from app.security import current_user, internal
from app.serializers import invoice_summary, payment_out
from app.services import add_months, money, monthly_factor, price_lines, run_billing

router = APIRouter(prefix="/api", tags=["Billing & reports"])


@router.post("/billing/run")
def billing_run(user: User = Depends(internal), db: Session = Depends(get_db)):
    """Create every invoice that is due today. Safe to press more than once."""
    return run_billing(db, date.today(), user)


@router.get("/reports/summary")
def summary(date_from: date | None = None, date_to: date | None = None, plan_id: int | None = None,
            user: User = Depends(current_user), db: Session = Depends(get_db)):
    today = date.today()
    date_to = date_to or today
    date_from = date_from or date_to.replace(day=1)
    mine = user.role == "customer"

    subs = db.query(Subscription)
    invs = db.query(Invoice)
    pays = db.query(Payment).join(Invoice)
    if mine:
        subs = subs.filter(Subscription.customer_id == user.id)
        invs = invs.filter(Invoice.customer_id == user.id)
        pays = pays.filter(Invoice.customer_id == user.id)
    if plan_id:
        subs = subs.filter(Subscription.plan_id == plan_id)
        invs = invs.join(Subscription, Invoice.subscription_id == Subscription.id).filter(Subscription.plan_id == plan_id)
        pays = pays.join(Subscription, Invoice.subscription_id == Subscription.id).filter(Subscription.plan_id == plan_id)

    by_status = dict(subs.with_entities(Subscription.status, func.count(Subscription.id))
                     .group_by(Subscription.status).all())
    paused = subs.filter(Subscription.status == "active", Subscription.paused.is_(True)).count()

    running = (subs.filter(Subscription.status == "active", Subscription.paused.is_(False))
               .options(selectinload(Subscription.plan), selectinload(Subscription.discount),
                        selectinload(Subscription.lines).selectinload(SubscriptionLine.tax)).all())
    mrr = 0.0
    for s in running:
        p = price_lines(s.lines, s.discount, today)
        mrr += (p["subtotal"] - p["discount_total"]) * monthly_factor(s.plan.billing_period)

    billed = invs.filter(Invoice.status.in_(["confirmed", "paid"]))
    invoiced = billed.filter(Invoice.issue_date >= date_from, Invoice.issue_date <= date_to) \
        .with_entities(func.coalesce(func.sum(Invoice.total), 0)).scalar()
    collected = pays.filter(Payment.payment_date >= date_from, Payment.payment_date <= date_to) \
        .with_entities(func.coalesce(func.sum(Payment.amount), 0)).scalar()
    open_q = invs.filter(Invoice.status == "confirmed", Invoice.total > Invoice.amount_paid)
    outstanding = open_q.with_entities(func.coalesce(func.sum(Invoice.total - Invoice.amount_paid), 0)).scalar()
    overdue_q = open_q.filter(Invoice.due_date < today)
    overdue_count = overdue_q.count()
    overdue_amount = overdue_q.with_entities(func.coalesce(func.sum(Invoice.total - Invoice.amount_paid), 0)).scalar()
    drafts = 0 if mine else invs.filter(Invoice.status == "draft").count()

    # Money collected per month, last 6 months
    start6 = add_months(today.replace(day=1), -5)
    monthly = dict(((int(y), int(m)), float(v)) for y, m, v in
                   pays.filter(Payment.payment_date >= start6)
                   .with_entities(extract("year", Payment.payment_date), extract("month", Payment.payment_date),
                                  func.sum(Payment.amount))
                   .group_by(extract("year", Payment.payment_date), extract("month", Payment.payment_date)).all())
    months = []
    for i in range(6):
        m = add_months(start6, i)
        months.append({"month": m.strftime("%b %Y"), "collected": money(monthly.get((m.year, m.month), 0))})

    top_plans = (subs.filter(Subscription.status == "active").join(Plan, Subscription.plan_id == Plan.id)
                 .with_entities(Plan.name, func.count(Subscription.id))
                 .group_by(Plan.name).order_by(func.count(Subscription.id).desc()).limit(5).all())

    overdue_list = (overdue_q.options(selectinload(Invoice.customer), selectinload(Invoice.subscription))
                    .order_by(Invoice.due_date).limit(8).all())
    recent_payments = (pays.options(selectinload(Payment.invoice).selectinload(Invoice.customer))
                       .order_by(Payment.payment_date.desc(), Payment.id.desc()).limit(8).all())

    return {
        "range": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
        "active_subscriptions": by_status.get("active", 0) - paused,
        "paused_subscriptions": paused,
        "subscriptions_by_status": {s: by_status.get(s, 0) for s in
                                    ("draft", "quotation", "confirmed", "active", "closed")},
        "mrr": money(mrr),
        "invoiced": money(invoiced),
        "collected": money(collected),
        "outstanding": money(outstanding),
        "overdue_count": overdue_count,
        "overdue_amount": money(overdue_amount),
        "draft_invoices": drafts,
        "collected_by_month": months,
        "top_plans": [{"plan": n, "active": c} for n, c in top_plans],
        "overdue_invoices": [invoice_summary(i, today) for i in overdue_list],
        "recent_payments": [payment_out(p) for p in recent_payments],
    }
