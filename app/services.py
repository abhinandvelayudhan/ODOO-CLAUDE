"""Business rules: pricing, taxes, discounts, the subscription lifecycle,
invoice generation, the billing engine and payments."""
import calendar
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    AuditLog, Discount, Invoice, InvoiceLine, Payment, Plan, Product, ProductVariant, Subscription,
    SubscriptionLine, Tax, User,
)

BILLING_PERIODS = ("daily", "weekly", "monthly", "yearly")
PAYMENT_METHODS = ("cash", "bank_transfer", "card", "upi", "cheque")

# Draft -> Quotation -> Confirmed -> Active -> Closed. Any open subscription can also be closed (cancelled).
TRANSITIONS = {
    "draft": ("quotation", "closed"),
    "quotation": ("confirmed", "closed"),
    "confirmed": ("active", "closed"),
    "active": ("closed",),
    "closed": (),
}
MAX_CATCH_UP_PERIODS = 36  # safety cap when a subscription is many periods behind


def money(value) -> float:
    """Round to cents, half-up (2.345 -> 2.35), avoiding float surprises."""
    return float(Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------------ dates
def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year, month = d.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def next_period_start(anchor: date, current: date, period: str) -> date:
    """Start of the period after `current`. Monthly and yearly periods stay aligned
    to the anchor day, so 31 Jan -> 28 Feb -> 31 Mar instead of drifting."""
    if period == "daily":
        return current + timedelta(days=1)
    if period == "weekly":
        return current + timedelta(days=7)
    step = 12 if period == "yearly" else 1
    elapsed = (current.year - anchor.year) * 12 + current.month - anchor.month
    k = elapsed // step
    candidate = add_months(anchor, (k + 1) * step)
    while candidate <= current:  # e.g. after a pause moved `current` off the anchor grid
        k += 1
        candidate = add_months(anchor, (k + 1) * step)
    return candidate


def monthly_factor(period: str) -> float:
    """Multiply a per-period amount by this to get a monthly amount (for MRR)."""
    return {"daily": 365 / 12, "weekly": 52 / 12, "monthly": 1.0, "yearly": 1 / 12}[period]


# ------------------------------------------------------------------ catalog helpers
def get_or_404(db: Session, model, obj_id, label: str):
    obj = db.get(model, obj_id) if obj_id is not None else None
    if not obj:
        raise HTTPException(404, f"{label} not found.")
    return obj


def variant_price(product: Product, variant: ProductVariant | None) -> float:
    return money(product.sales_price + (variant.extra_price if variant else 0))


def plan_is_available(plan: Plan, on: date) -> bool:
    return plan.is_active and plan.start_date <= on and (plan.end_date is None or on <= plan.end_date)


# ------------------------------------------------------------------ discounts
def discount_problem(discount: Discount, on: date) -> str | None:
    """Why a discount cannot be used right now, or None if it can."""
    if not discount.is_active:
        return "This discount is no longer active."
    if on < discount.start_date:
        return f"This discount starts on {discount.start_date.isoformat()}."
    if discount.end_date and on > discount.end_date:
        return "This discount has expired."
    if discount.usage_limit is not None and discount.used_count >= discount.usage_limit:
        return "This discount has reached its usage limit."
    return None


def find_discount(db: Session, code: str | None, on: date) -> Discount | None:
    if not code or not code.strip():
        return None
    discount = db.query(Discount).filter(Discount.code == code.strip().upper()).first()
    if not discount:
        raise HTTPException(400, "That discount code does not exist.")
    problem = discount_problem(discount, on)
    if problem:
        raise HTTPException(400, problem)
    return discount


# ------------------------------------------------------------------ pricing
def price_lines(lines: list[SubscriptionLine], discount: Discount | None, on: date) -> dict:
    """Work out subtotal, discount, tax and total for each line and overall.

    Discounts are taken off before tax. A product discount only touches lines of
    that product. Minimum purchase / quantity rules are checked against the
    lines the discount applies to. A fixed discount is shared across those
    lines in proportion to their value.
    """
    priced = []
    for line in lines:
        subtotal = money(line.unit_price * line.quantity)
        priced.append({
            "line": line, "description": line.description, "quantity": line.quantity,
            "unit_price": money(line.unit_price), "subtotal": subtotal, "discount_amount": 0.0,
            "tax_name": line.tax.name if line.tax else None,
            "tax_rate": float(line.tax.rate) if line.tax else 0.0,
        })

    applied, note = False, None
    if discount:
        note = discount_problem(discount, on)
        eligible = [p for p in priced if discount.applies_to == "subscription"
                    or (p["line"].product_id and p["line"].product_id == discount.product_id)]
        base = money(sum(p["subtotal"] for p in eligible))
        qty = sum(p["quantity"] for p in eligible)
        if note is None:
            if not eligible or base <= 0:
                note = "No lines qualify for this discount."
            elif base < discount.min_amount:
                note = f"Minimum purchase of {discount.min_amount:.2f} not reached."
            elif qty < discount.min_quantity:
                note = f"Minimum quantity of {discount.min_quantity} not reached."
        if note is None:
            if discount.discount_type == "percentage":
                for p in eligible:
                    p["discount_amount"] = money(p["subtotal"] * discount.value / 100)
            else:
                fixed_total = remaining = money(min(discount.value, base))
                for i, p in enumerate(eligible):
                    share = remaining if i == len(eligible) - 1 else money(fixed_total * p["subtotal"] / base)
                    share = min(share, remaining, p["subtotal"])
                    p["discount_amount"] = share
                    remaining = money(remaining - share)
            applied = True

    for p in priced:
        taxable = money(p["subtotal"] - p["discount_amount"])
        p["tax_amount"] = money(taxable * p["tax_rate"] / 100)
        p["total"] = money(taxable + p["tax_amount"])

    return {
        "lines": priced,
        "subtotal": money(sum(p["subtotal"] for p in priced)),
        "discount_total": money(sum(p["discount_amount"] for p in priced)),
        "tax_total": money(sum(p["tax_amount"] for p in priced)),
        "total": money(sum(p["total"] for p in priced)),
        "discount_applied": applied,
        "discount_note": note if discount else None,
    }


def build_lines(db: Session, plan: Plan, plan_quantity: int, items: list) -> list[SubscriptionLine]:
    """Create the subscription lines: the plan itself, then any products / add-ons."""
    if plan_quantity < plan.min_quantity:
        raise HTTPException(400, f"The {plan.name} plan needs a minimum quantity of {plan.min_quantity}.")
    lines = [SubscriptionLine(description=f"{plan.name} ({plan.billing_period} plan)", quantity=plan_quantity,
                              unit_price=money(plan.price), tax_id=plan.tax_id, tax=plan.tax)]
    for item in items:
        product = get_or_404(db, Product, item.product_id, "Product")
        if not product.is_active:
            raise HTTPException(400, f"{product.name} is no longer available.")
        variant = None
        if item.variant_id:
            variant = get_or_404(db, ProductVariant, item.variant_id, "Variant")
            if variant.product_id != product.id:
                raise HTTPException(400, "That variant does not belong to the chosen product.")
        label = product.name + (f" - {variant.attribute}: {variant.value}" if variant else "")
        lines.append(SubscriptionLine(product_id=product.id, product=product, variant_id=variant.id if variant else None,
                                      variant=variant, description=label, quantity=item.quantity,
                                      unit_price=variant_price(product, variant), tax_id=product.tax_id,
                                      tax=product.tax))
    return lines


# ------------------------------------------------------------------ lifecycle
def audit(db: Session, sub: Subscription, action: str, user: User | None, note: str | None = None,
          frm: str | None = None, to: str | None = None):
    db.add(AuditLog(subscription_id=sub.id, action=action, from_status=frm, to_status=to,
                    user_name=user.name if user else "System", note=note))


def change_status(db: Session, sub: Subscription, target: str, user: User, note: str | None, today: date):
    target = target.lower()
    if target not in TRANSITIONS.get(sub.status, ()):
        allowed = ", ".join(TRANSITIONS.get(sub.status, ())) or "none"
        raise HTTPException(400, f"A {sub.status} subscription cannot move to {target}. Allowed: {allowed}.")

    if target == "confirmed" and sub.quote_valid_until and today > sub.quote_valid_until:
        raise HTTPException(400, f"This quotation expired on {sub.quote_valid_until.isoformat()}. "
                                 "Ask the team for a new one.")
    if target == "active":
        if sub.expiry_date and sub.expiry_date <= sub.start_date:
            raise HTTPException(400, "The expiry date must be after the start date.")
        sub.next_invoice_date = sub.start_date
        sub.term_days = (sub.expiry_date - sub.start_date).days if sub.expiry_date else None
    if target == "closed":
        sub.closed_at = datetime.now()
        sub.next_invoice_date = None
        sub.paused = False

    previous = sub.status
    sub.status = target
    audit(db, sub, "status", user, note, previous, target)
    db.flush()
    if target == "active":
        bill_subscription(db, sub, today)  # first invoice straight away if the start date has arrived


# ------------------------------------------------------------------ invoicing
def create_invoice(db: Session, sub: Subscription, period_start: date, today: date) -> Invoice | None:
    """Invoice one billing period. Returns None if that period is already invoiced."""
    exists = db.query(Invoice.id).filter(Invoice.subscription_id == sub.id,
                                         Invoice.period_start == period_start).first()
    if exists:
        return None

    period_end = next_period_start(sub.start_date, period_start, sub.plan.billing_period) - timedelta(days=1)
    pricing = price_lines(sub.lines, sub.discount, today)
    issue = today
    inv = Invoice(subscription_id=sub.id, customer_id=sub.customer_id, status="draft", issue_date=issue,
                  due_date=issue + timedelta(days=sub.payment_terms_days), period_start=period_start,
                  period_end=period_end, subtotal=pricing["subtotal"], discount_total=pricing["discount_total"],
                  tax_total=pricing["tax_total"], total=pricing["total"], amount_paid=0,
                  discount_code=sub.discount.code if pricing["discount_applied"] else None)
    for p in pricing["lines"]:
        inv.lines.append(InvoiceLine(description=p["description"], quantity=p["quantity"],
                                     unit_price=p["unit_price"], subtotal=p["subtotal"],
                                     discount_amount=p["discount_amount"], tax_name=p["tax_name"],
                                     tax_rate=p["tax_rate"], tax_amount=p["tax_amount"], total=p["total"]))
    if pricing["discount_applied"]:
        sub.discount.used_count += 1  # each invoice it lands on counts as one use
    db.add(inv)
    db.flush()
    inv.number = f"INV-{inv.id:05d}"
    return inv


def bill_subscription(db: Session, sub: Subscription, today: date) -> list[Invoice]:
    """Create every invoice that is due for one subscription, oldest first."""
    created = []
    if sub.status != "active" or sub.paused or not sub.next_invoice_date:
        return created
    for _ in range(MAX_CATCH_UP_PERIODS):
        start = sub.next_invoice_date
        if start > today or (sub.expiry_date and start >= sub.expiry_date):
            break
        inv = create_invoice(db, sub, start, today)
        if inv:
            created.append(inv)
        sub.next_invoice_date = next_period_start(sub.start_date, start, sub.plan.billing_period)
    db.flush()
    return created


def run_billing(db: Session, today: date, user: User | None = None) -> dict:
    """Billing day: invoice every active subscription that is due, then close
    subscriptions whose plan closes them automatically at expiry.
    Safe to run any number of times - a period is never billed twice."""
    due = (db.query(Subscription)
           .filter(Subscription.status == "active", Subscription.paused.is_(False),
                   Subscription.next_invoice_date.isnot(None), Subscription.next_invoice_date <= today)
           .all())
    invoices = []
    for sub in due:
        invoices.extend(bill_subscription(db, sub, today))

    expired = (db.query(Subscription).join(Plan)
               .filter(Subscription.status == "active", Plan.auto_close.is_(True),
                       Subscription.expiry_date.isnot(None), Subscription.expiry_date <= today)
               .all())
    for sub in expired:
        sub.status, sub.closed_at, sub.next_invoice_date, sub.paused = "closed", datetime.now(), None, False
        audit(db, sub, "status", None, "Closed automatically at the end of its term.", "active", "closed")

    db.commit()
    return {
        "invoices_created": len(invoices),
        "amount_invoiced": money(sum(i.total for i in invoices)),
        "subscriptions_billed": len({i.subscription_id for i in invoices}),
        "subscriptions_closed": len(expired),
        "invoice_numbers": [i.number for i in invoices][:50],
        "run_at": datetime.now().isoformat(timespec="seconds"),
    }


def balance(inv: Invoice) -> float:
    return money(inv.total - inv.amount_paid)


def is_overdue(inv: Invoice, today: date) -> bool:
    return inv.status == "confirmed" and inv.due_date < today and balance(inv) > 0


def record_payment(db: Session, inv: Invoice, amount: float, method: str, paid_on: date,
                   note: str | None, user: User) -> Payment:
    if inv.status != "confirmed":
        raise HTTPException(400, "Payments can only be recorded against confirmed invoices.")
    amount = money(amount)
    if amount <= 0:
        raise HTTPException(400, "The payment amount must be greater than zero.")
    if amount > balance(inv):
        raise HTTPException(400, f"The payment is more than the amount still owed ({balance(inv):.2f}).")
    if method not in PAYMENT_METHODS:
        raise HTTPException(400, f"Payment method must be one of: {', '.join(PAYMENT_METHODS)}.")
    payment = Payment(invoice_id=inv.id, amount=amount, method=method, payment_date=paid_on, note=note,
                      recorded_by=user.name)
    inv.payments.append(payment)
    inv.amount_paid = money(inv.amount_paid + amount)
    if balance(inv) == 0:
        inv.status = "paid"
    db.flush()
    return payment


def tax_lookup(db: Session, tax_id: int | None) -> Tax | None:
    return get_or_404(db, Tax, tax_id, "Tax") if tax_id else None
