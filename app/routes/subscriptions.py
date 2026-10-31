"""Subscriptions: quotes, the Draft -> Quotation -> Confirmed -> Active -> Closed
lifecycle, pausing, renewing and closing."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Plan, QuotationTemplate, Subscription, SubscriptionLine, User
from app.schemas import LineIn, SubscriptionIn, TransitionIn
from app.security import current_user
from app.serializers import sub_out, sub_summary
from app.services import audit, build_lines, change_status, find_discount, get_or_404, plan_is_available

router = APIRouter(prefix="/api/subscriptions", tags=["Subscriptions"])

LIST_OPTIONS = (
    selectinload(Subscription.customer), selectinload(Subscription.plan), selectinload(Subscription.discount),
    selectinload(Subscription.lines).selectinload(SubscriptionLine.tax),
)


def load(db: Session, sub_id: int, user: User) -> Subscription:
    sub = db.get(Subscription, sub_id)
    if not sub or (user.role == "customer" and sub.customer_id != user.id):
        raise HTTPException(404, "Subscription not found.")
    return sub


@router.get("")
def list_subscriptions(status: str | None = None, plan_id: int | None = None, customer_id: int | None = None,
                       q: str | None = None, page: int = 1, page_size: int = 50,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    page, page_size = max(page, 1), min(max(page_size, 1), 200)
    query = db.query(Subscription)
    if user.role == "customer":
        query = query.filter(Subscription.customer_id == user.id)
    elif customer_id:
        query = query.filter(Subscription.customer_id == customer_id)
    if status == "paused":
        query = query.filter(Subscription.status == "active", Subscription.paused.is_(True))
    elif status:
        query = query.filter(Subscription.status == status)
    if plan_id:
        query = query.filter(Subscription.plan_id == plan_id)
    if q:
        like = f"%{q.strip()}%"
        query = query.join(User, Subscription.customer_id == User.id).filter(
            or_(Subscription.number.ilike(like), User.name.ilike(like), User.email.ilike(like)))
    total = query.count()
    rows = (query.options(*LIST_OPTIONS).order_by(Subscription.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    today = date.today()
    return {"items": [sub_summary(s, today) for s in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/{sub_id}")
def get_subscription(sub_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return sub_out(load(db, sub_id, user), date.today())


def _apply_form(db: Session, sub: Subscription, body: SubscriptionIn, user: User, today: date):
    """Fill a subscription from the form, optionally starting from a quotation template."""
    items: list[LineIn] = list(body.lines)
    plan_quantity = body.plan_quantity
    plan_id = body.plan_id
    if body.template_id:
        tpl = get_or_404(db, QuotationTemplate, body.template_id, "Quotation template")
        if not tpl.is_active:
            raise HTTPException(400, "That quotation template is no longer active.")
        plan_id = plan_id or tpl.plan_id
        if not body.lines:  # the template's product lines, unless the form overrides them
            items = [LineIn(product_id=l.product_id, variant_id=l.variant_id, quantity=l.quantity) for l in tpl.lines]
        if body.plan_quantity == 1:
            plan_quantity = tpl.plan_quantity
        sub.template_id = tpl.id

    plan = get_or_404(db, Plan, plan_id, "Plan")
    start = body.start_date or today
    if not plan_is_available(plan, start):
        raise HTTPException(400, f"The {plan.name} plan is not available on {start.isoformat()}.")
    if plan.end_date and body.expiry_date and body.expiry_date > plan.end_date + timedelta(days=1):
        raise HTTPException(400, f"The {plan.name} plan is only offered until {plan.end_date.isoformat()}.")

    if user.role == "customer":
        customer = user
    else:
        customer = get_or_404(db, User, body.customer_id, "Customer")
        if customer.role != "customer":
            raise HTTPException(400, "Subscriptions can only be created for customer accounts.")
        if not customer.is_active:
            raise HTTPException(400, "That customer account is deactivated.")

    discount = find_discount(db, body.discount_code, today)
    if discount and discount.applies_to == "product" and \
            discount.product_id not in {i.product_id for i in items}:
        raise HTTPException(400, f"The code {discount.code} only applies to {discount.product.name}, "
                                 "which is not on this subscription.")

    sub.customer_id, sub.plan_id, sub.plan = customer.id, plan.id, plan
    sub.start_date, sub.expiry_date = start, body.expiry_date
    sub.payment_terms_days, sub.notes = body.payment_terms_days, body.notes
    sub.discount_id, sub.discount = (discount.id, discount) if discount else (None, None)
    sub.lines.clear()
    db.flush()
    sub.lines.extend(build_lines(db, plan, plan_quantity, items))


@router.post("")
def create_subscription(body: SubscriptionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    today = date.today()
    sub = Subscription(status="draft", created_by_id=user.id)
    db.add(sub)
    _apply_form(db, sub, body, user, today)
    db.flush()
    sub.number = f"SUB-{sub.id:05d}"
    who = "Requested by the customer through the portal." if user.role == "customer" else "Created."
    audit(db, sub, "created", user, who, None, "draft")
    db.commit()
    return sub_out(sub, today)


@router.put("/{sub_id}")
def update_subscription(sub_id: int, body: SubscriptionIn, user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    sub = load(db, sub_id, user)
    if sub.status not in ("draft", "quotation"):
        raise HTTPException(400, "Only draft or quotation subscriptions can be edited.")
    if user.role == "customer" and sub.status != "draft":
        raise HTTPException(403, "This quotation has already been sent. Ask the team to change it.")
    _apply_form(db, sub, body, user, date.today())
    audit(db, sub, "edited", user, "Subscription details updated.")
    db.commit()
    return sub_out(sub, date.today())


@router.post("/{sub_id}/transition")
def transition(sub_id: int, body: TransitionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    today = date.today()
    sub = load(db, sub_id, user)

    if user.role == "customer":
        allowed = (sub.status == "quotation" and body.to in ("confirmed", "closed")) or \
                  (sub.status == "draft" and body.to == "closed") or \
                  (sub.status == "active" and body.to == "closed")
        if not allowed:
            raise HTTPException(403, "Customers can accept or decline a quotation, or close their own subscription.")

    early = sub.status == "active" and body.to == "closed" and (sub.expiry_date is None or sub.expiry_date > today)
    if early and not sub.plan.closable and user.role != "admin":
        raise HTTPException(400, f"The {sub.plan.name} plan cannot be closed early. "
                                 + ("Contact the team." if user.role == "customer" else "Ask an admin."))

    if body.to == "quotation":
        validity = 30
        if sub.template_id:
            validity = db.get(QuotationTemplate, sub.template_id).validity_days
        sub.quote_valid_until = today + timedelta(days=validity)

    change_status(db, sub, body.to, user, body.note, today)
    db.commit()
    return sub_out(sub, today)


@router.post("/{sub_id}/pause")
def pause(sub_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sub = load(db, sub_id, user)
    if sub.status != "active" or sub.paused:
        raise HTTPException(400, "Only a running active subscription can be paused.")
    if not sub.plan.pausable:
        raise HTTPException(400, f"The {sub.plan.name} plan cannot be paused.")
    sub.paused = True
    audit(db, sub, "paused", user, "Billing paused.")
    db.commit()
    return sub_out(sub, date.today())


@router.post("/{sub_id}/resume")
def resume(sub_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    today = date.today()
    sub = load(db, sub_id, user)
    if sub.status != "active" or not sub.paused:
        raise HTTPException(400, "This subscription is not paused.")
    sub.paused = False
    if sub.next_invoice_date and sub.next_invoice_date < today:
        sub.next_invoice_date = today  # paused periods are not billed
    audit(db, sub, "resumed", user, "Billing resumed.")
    db.commit()
    return sub_out(sub, today)


@router.post("/{sub_id}/renew")
def renew(sub_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sub = load(db, sub_id, user)
    if sub.status != "active":
        raise HTTPException(400, "Only active subscriptions can be renewed.")
    if not sub.plan.renewable:
        raise HTTPException(400, f"The {sub.plan.name} plan cannot be renewed.")
    if not sub.expiry_date or not sub.term_days:
        raise HTTPException(400, "This subscription has no expiry date, so it does not need renewing.")
    old = sub.expiry_date
    sub.expiry_date = old + timedelta(days=sub.term_days)
    audit(db, sub, "renewed", user, f"Expiry moved from {old.isoformat()} to {sub.expiry_date.isoformat()}.")
    db.commit()
    return sub_out(sub, date.today())
