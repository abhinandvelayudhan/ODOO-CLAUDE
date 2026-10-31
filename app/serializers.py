"""Turn database rows into the JSON the frontend reads."""
from datetime import date

from app.models import (
    Discount, Invoice, Payment, Plan, Product, QuotationTemplate, Subscription, Tax, User,
)
from app.services import balance, discount_problem, is_overdue, money, price_lines


def iso(value):
    return value.isoformat() if value else None


def user_out(u: User) -> dict:
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "is_active": u.is_active,
            "company": u.company, "phone": u.phone, "address": u.address, "department": u.department,
            "created_at": iso(u.created_at.date() if u.created_at else None)}


def tax_out(t: Tax) -> dict:
    return {"id": t.id, "name": t.name, "rate": float(t.rate), "is_active": t.is_active}


def product_out(p: Product) -> dict:
    return {"id": p.id, "name": p.name, "product_type": p.product_type, "sales_price": money(p.sales_price),
            "cost_price": money(p.cost_price), "notes": p.notes, "tax_id": p.tax_id,
            "tax": tax_out(p.tax) if p.tax else None, "is_active": p.is_active,
            "variants": [{"id": v.id, "attribute": v.attribute, "value": v.value,
                          "extra_price": money(v.extra_price)} for v in p.variants]}


def plan_out(p: Plan) -> dict:
    return {"id": p.id, "name": p.name, "description": p.description, "price": money(p.price),
            "billing_period": p.billing_period, "min_quantity": p.min_quantity,
            "start_date": iso(p.start_date), "end_date": iso(p.end_date), "auto_close": p.auto_close,
            "closable": p.closable, "pausable": p.pausable, "renewable": p.renewable, "tax_id": p.tax_id,
            "tax": tax_out(p.tax) if p.tax else None, "is_active": p.is_active}


def discount_out(d: Discount, today: date | None = None) -> dict:
    today = today or date.today()
    problem = discount_problem(d, today)
    return {"id": d.id, "code": d.code, "name": d.name, "discount_type": d.discount_type, "value": money(d.value),
            "min_amount": money(d.min_amount), "min_quantity": d.min_quantity, "start_date": iso(d.start_date),
            "end_date": iso(d.end_date), "usage_limit": d.usage_limit, "used_count": d.used_count,
            "applies_to": d.applies_to, "product_id": d.product_id,
            "product": d.product.name if d.product else None, "is_active": d.is_active,
            "usable": problem is None, "status_note": problem or "Usable"}


def template_out(t: QuotationTemplate) -> dict:
    return {"id": t.id, "name": t.name, "plan_id": t.plan_id, "plan": t.plan.name, "plan_quantity": t.plan_quantity,
            "validity_days": t.validity_days, "notes": t.notes, "is_active": t.is_active,
            "lines": [{"product_id": l.product_id, "product": l.product.name, "variant_id": l.variant_id,
                       "variant": f"{l.variant.attribute}: {l.variant.value}" if l.variant else None,
                       "quantity": l.quantity} for l in t.lines]}


def sub_summary(s: Subscription, today: date) -> dict:
    pricing = price_lines(s.lines, s.discount, today)
    return {"id": s.id, "number": s.number, "customer_id": s.customer_id, "customer": s.customer.name,
            "customer_email": s.customer.email, "plan_id": s.plan_id, "plan": s.plan.name,
            "billing_period": s.plan.billing_period, "status": s.status, "paused": s.paused,
            "start_date": iso(s.start_date), "expiry_date": iso(s.expiry_date),
            "next_invoice_date": iso(s.next_invoice_date), "total": pricing["total"],
            "recurring_amount": pricing["total"]}


def sub_out(s: Subscription, today: date) -> dict:
    pricing = price_lines(s.lines, s.discount, today)
    data = sub_summary(s, today)
    data.update({
        "template_id": s.template_id, "payment_terms_days": s.payment_terms_days,
        "quote_valid_until": iso(s.quote_valid_until), "notes": s.notes,
        "plan_quantity": s.lines[0].quantity if s.lines else 1,
        "discount_code": s.discount.code if s.discount else None,
        "discount_applied": pricing["discount_applied"], "discount_note": pricing["discount_note"],
        "subtotal": pricing["subtotal"], "discount_total": pricing["discount_total"],
        "tax_total": pricing["tax_total"],
        "plan_rules": {"closable": s.plan.closable, "pausable": s.plan.pausable, "renewable": s.plan.renewable,
                       "auto_close": s.plan.auto_close},
        "lines": [{"id": p["line"].id, "product_id": p["line"].product_id, "variant_id": p["line"].variant_id,
                   "description": p["description"], "quantity": p["quantity"], "unit_price": p["unit_price"],
                   "subtotal": p["subtotal"], "discount_amount": p["discount_amount"], "tax_name": p["tax_name"],
                   "tax_rate": p["tax_rate"], "tax_amount": p["tax_amount"], "total": p["total"]}
                  for p in pricing["lines"]],
        "history": [{"action": a.action, "from": a.from_status, "to": a.to_status, "by": a.user_name,
                     "note": a.note, "at": a.created_at.isoformat(timespec="minutes")} for a in s.audit_logs],
    })
    return data


def invoice_status(inv: Invoice, today: date) -> str:
    return "overdue" if is_overdue(inv, today) else inv.status


def invoice_summary(inv: Invoice, today: date) -> dict:
    return {"id": inv.id, "number": inv.number, "subscription_id": inv.subscription_id,
            "subscription": inv.subscription.number, "customer_id": inv.customer_id, "customer": inv.customer.name,
            "status": inv.status, "display_status": invoice_status(inv, today), "overdue": is_overdue(inv, today),
            "issue_date": iso(inv.issue_date), "due_date": iso(inv.due_date), "period_start": iso(inv.period_start),
            "period_end": iso(inv.period_end), "total": money(inv.total), "amount_paid": money(inv.amount_paid),
            "balance": balance(inv), "sent_at": inv.sent_at.isoformat(timespec="minutes") if inv.sent_at else None}


def invoice_out(inv: Invoice, today: date) -> dict:
    data = invoice_summary(inv, today)
    c = inv.customer
    data.update({
        "customer_details": {"name": c.name, "email": c.email, "company": c.company, "phone": c.phone,
                             "address": c.address},
        "subtotal": money(inv.subtotal), "discount_total": money(inv.discount_total),
        "tax_total": money(inv.tax_total), "discount_code": inv.discount_code, "notes": inv.notes,
        "lines": [{"description": l.description, "quantity": l.quantity, "unit_price": money(l.unit_price),
                   "subtotal": money(l.subtotal), "discount_amount": money(l.discount_amount),
                   "tax_name": l.tax_name, "tax_rate": float(l.tax_rate), "tax_amount": money(l.tax_amount),
                   "total": money(l.total)} for l in inv.lines],
        "payments": [payment_out(p) for p in inv.payments],
    })
    return data


def payment_out(p: Payment) -> dict:
    return {"id": p.id, "invoice_id": p.invoice_id, "invoice": p.invoice.number if p.invoice else None,
            "customer": p.invoice.customer.name if p.invoice else None, "amount": money(p.amount),
            "method": p.method, "payment_date": iso(p.payment_date), "note": p.note, "recorded_by": p.recorded_by}
