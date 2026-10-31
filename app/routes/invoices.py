"""Invoices (Draft -> Confirmed -> Paid), printing, sending and payments."""
import html
import os
from datetime import date, datetime
from string import Template

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.database import PROJECT_ROOT, get_db
from app.mailer import send_email
from app.models import Invoice, Payment, User
from app.schemas import PaymentIn, PortalPayIn
from app.security import current_user, internal
from app.serializers import invoice_out, invoice_summary, payment_out
from app.services import balance, record_payment

router = APIRouter(prefix="/api", tags=["Invoices & payments"])

INVOICE_TEMPLATE = os.path.join(PROJECT_ROOT, "templates", "invoice.html")
LIST_OPTIONS = (selectinload(Invoice.customer), selectinload(Invoice.subscription))


def load(db: Session, inv_id: int, user: User) -> Invoice:
    inv = db.get(Invoice, inv_id)
    if not inv or (user.role == "customer" and (inv.customer_id != user.id or inv.status == "draft")):
        raise HTTPException(404, "Invoice not found.")
    return inv


def filter_invoices(query, user: User, status, customer_id, q, date_from, date_to, today: date,
                    subscription_id: int | None = None):
    if subscription_id:
        query = query.filter(Invoice.subscription_id == subscription_id)
    if user.role == "customer":
        query = query.filter(Invoice.customer_id == user.id, Invoice.status != "draft")
    elif customer_id:
        query = query.filter(Invoice.customer_id == customer_id)
    if status == "overdue":
        query = query.filter(Invoice.status == "confirmed", Invoice.due_date < today,
                             Invoice.total > Invoice.amount_paid)
    elif status == "outstanding":
        query = query.filter(Invoice.status == "confirmed", Invoice.total > Invoice.amount_paid)
    elif status:
        query = query.filter(Invoice.status == status)
    if date_from:
        query = query.filter(Invoice.issue_date >= date_from)
    if date_to:
        query = query.filter(Invoice.issue_date <= date_to)
    if q:
        like = f"%{q.strip()}%"
        query = query.join(User, Invoice.customer_id == User.id).filter(
            or_(Invoice.number.ilike(like), User.name.ilike(like), User.email.ilike(like)))
    return query


@router.get("/invoices")
def list_invoices(status: str | None = None, customer_id: int | None = None, q: str | None = None,
                  date_from: date | None = None, date_to: date | None = None, subscription_id: int | None = None,
                  page: int = 1, page_size: int = 50,
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    today = date.today()
    page, page_size = max(page, 1), min(max(page_size, 1), 200)
    query = filter_invoices(db.query(Invoice), user, status, customer_id, q, date_from, date_to, today,
                            subscription_id)
    total = query.count()
    rows = (query.options(*LIST_OPTIONS).order_by(Invoice.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    return {"items": [invoice_summary(i, today) for i in rows], "total": total, "page": page,
            "page_size": page_size}


@router.get("/invoices/{inv_id}")
def get_invoice(inv_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return invoice_out(load(db, inv_id, user), date.today())


@router.post("/invoices/confirm-drafts")
def confirm_all_drafts(_: User = Depends(internal), db: Session = Depends(get_db)):
    """Billing day helper: confirm every draft invoice in one go."""
    count = db.query(Invoice).filter(Invoice.status == "draft").update({"status": "confirmed"})
    db.commit()
    return {"confirmed": count}


@router.post("/invoices/{inv_id}/confirm")
def confirm_invoice(inv_id: int, user: User = Depends(internal), db: Session = Depends(get_db)):
    inv = load(db, inv_id, user)
    if inv.status != "draft":
        raise HTTPException(400, "Only draft invoices can be confirmed.")
    inv.status = "confirmed"
    db.commit()
    return invoice_out(inv, date.today())


@router.post("/invoices/{inv_id}/cancel")
def cancel_invoice(inv_id: int, user: User = Depends(internal), db: Session = Depends(get_db)):
    inv = load(db, inv_id, user)
    if inv.status not in ("draft", "confirmed"):
        raise HTTPException(400, f"A {inv.status} invoice cannot be cancelled.")
    if inv.amount_paid > 0:
        raise HTTPException(400, "This invoice already has payments recorded and cannot be cancelled.")
    inv.status = "cancelled"
    db.commit()
    return invoice_out(inv, date.today())


@router.post("/invoices/{inv_id}/send")
def send_invoice(inv_id: int, user: User = Depends(internal), db: Session = Depends(get_db)):
    inv = load(db, inv_id, user)
    if inv.status not in ("confirmed", "paid"):
        raise HTTPException(400, "Confirm the invoice before sending it.")
    body = (f"Hi {inv.customer.name},\n\nYour invoice {inv.number} for {inv.total:.2f} is ready.\n"
            f"Billing period: {inv.period_start} to {inv.period_end}\nDue date: {inv.due_date}\n"
            f"Amount still owed: {balance(inv):.2f}\n\nYou can view and pay it in your INTRINSIC customer portal.")
    really_sent = send_email(inv.customer.email, f"Invoice {inv.number}", body, render_invoice(inv))
    inv.sent_at = datetime.now()
    db.commit()
    data = invoice_out(inv, date.today())
    data["message"] = (f"Invoice emailed to {inv.customer.email}." if really_sent else
                       f"Demo mode: no mail server is set up, so the email to {inv.customer.email} "
                       "was written to the server console instead.")
    return data


def render_invoice(inv: Invoice) -> str:
    esc = lambda v: html.escape(str(v)) if v is not None else ""
    rows = "".join(
        f"<tr><td>{esc(l.description)}</td><td class='n'>{l.quantity}</td><td class='n'>{l.unit_price:,.2f}</td>"
        f"<td class='n'>{l.discount_amount:,.2f}</td><td class='n'>{esc(l.tax_name or '-')}"
        f"{f' ({float(l.tax_rate):g}%)' if l.tax_name else ''}</td><td class='n'>{l.tax_amount:,.2f}</td>"
        f"<td class='n'>{l.total:,.2f}</td></tr>" for l in inv.lines)
    payments = "".join(
        f"<tr><td>{p.payment_date}</td><td>{esc(p.method.replace('_', ' ').title())}</td>"
        f"<td>{esc(p.note or '')}</td><td class='n'>{p.amount:,.2f}</td></tr>" for p in inv.payments
    ) or "<tr><td colspan='4' class='muted'>No payments yet.</td></tr>"
    c = inv.customer
    with open(INVOICE_TEMPLATE, encoding="utf-8") as fh:
        template = Template(fh.read())
    return template.safe_substitute(
        number=esc(inv.number), status=esc(inv.status.upper()), issue_date=inv.issue_date, due_date=inv.due_date,
        period=f"{inv.period_start} to {inv.period_end}", subscription=esc(inv.subscription.number),
        customer_name=esc(c.name), customer_company=esc(c.company), customer_email=esc(c.email),
        customer_phone=esc(c.phone), customer_address=esc(c.address), rows=rows, payments=payments,
        subtotal=f"{inv.subtotal:,.2f}", discount=f"{inv.discount_total:,.2f}",
        discount_code=f" ({esc(inv.discount_code)})" if inv.discount_code else "",
        tax=f"{inv.tax_total:,.2f}", total=f"{inv.total:,.2f}", paid=f"{inv.amount_paid:,.2f}",
        balance=f"{balance(inv):,.2f}")


@router.get("/invoices/{inv_id}/print", response_class=HTMLResponse)
def print_invoice(inv_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return HTMLResponse(render_invoice(load(db, inv_id, user)))


# ------------------------------------------------------------------ payments
@router.post("/invoices/{inv_id}/payments")
def add_payment(inv_id: int, body: PaymentIn, user: User = Depends(internal), db: Session = Depends(get_db)):
    """Record a payment (any method, any day, partial or full) against an invoice."""
    inv = load(db, inv_id, user)
    record_payment(db, inv, body.amount, body.method, body.payment_date or date.today(), body.note, user)
    db.commit()
    return invoice_out(inv, date.today())


@router.post("/invoices/{inv_id}/pay")
def portal_pay(inv_id: int, body: PortalPayIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Customer portal: pay the full amount still owed (simulated online payment)."""
    inv = load(db, inv_id, user)
    record_payment(db, inv, balance(inv), body.method, date.today(), "Paid online through the customer portal", user)
    db.commit()
    return invoice_out(inv, date.today())


@router.get("/payments")
def list_payments(method: str | None = None, customer_id: int | None = None, date_from: date | None = None,
                  date_to: date | None = None, page: int = 1, page_size: int = 50,
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    page, page_size = max(page, 1), min(max(page_size, 1), 200)
    query = db.query(Payment).join(Invoice)
    if user.role == "customer":
        query = query.filter(Invoice.customer_id == user.id)
    elif customer_id:
        query = query.filter(Invoice.customer_id == customer_id)
    if method:
        query = query.filter(Payment.method == method)
    if date_from:
        query = query.filter(Payment.payment_date >= date_from)
    if date_to:
        query = query.filter(Payment.payment_date <= date_to)
    total = query.count()
    rows = (query.options(selectinload(Payment.invoice).selectinload(Invoice.customer))
            .order_by(Payment.payment_date.desc(), Payment.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    return {"items": [payment_out(p) for p in rows], "total": total, "page": page, "page_size": page_size}
