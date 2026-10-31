"""Products (with variants), plans, taxes, discount rules and quotation templates.
Everyone signed in can read the catalog they need; only the admin can change it."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import (
    Discount, Plan, Product, ProductVariant, QuotationTemplate, SubscriptionLine, Tax, TemplateLine, User,
)
from app.schemas import DiscountIn, PlanIn, ProductIn, TaxIn, TemplateIn
from app.security import admin_only, current_user, internal
from app.serializers import discount_out, plan_out, product_out, tax_out, template_out
from app.services import get_or_404, plan_is_available, tax_lookup

router = APIRouter(prefix="/api", tags=["Catalog"])


# ------------------------------------------------------------------ taxes
@router.get("/taxes")
def list_taxes(_: User = Depends(internal), db: Session = Depends(get_db)):
    return [tax_out(t) for t in db.query(Tax).order_by(Tax.rate)]


@router.post("/taxes")
def add_tax(body: TaxIn, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    tax = Tax(**body.model_dump())
    db.add(tax)
    db.commit()
    return tax_out(tax)


@router.put("/taxes/{tax_id}")
def edit_tax(tax_id: int, body: TaxIn, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    tax = get_or_404(db, Tax, tax_id, "Tax")
    for k, v in body.model_dump().items():
        setattr(tax, k, v)
    db.commit()
    return tax_out(tax)


# ------------------------------------------------------------------ products
@router.get("/products")
def list_products(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(Product).options(selectinload(Product.variants), selectinload(Product.tax))
    if user.role == "customer":
        q = q.filter(Product.is_active.is_(True))
    rows = [product_out(p) for p in q.order_by(Product.name)]
    if user.role == "customer":
        for r in rows:
            r.pop("cost_price")  # internal information
    return rows


def _save_product(db: Session, product: Product, body: ProductIn):
    tax_lookup(db, body.tax_id)
    data = body.model_dump(exclude={"variants"})
    for k, v in data.items():
        setattr(product, k, v)
    keep = {v.id for v in body.variants if v.id}
    for existing in list(product.variants):
        if existing.id not in keep:
            if db.query(SubscriptionLine.id).filter(SubscriptionLine.variant_id == existing.id).first() or \
               db.query(TemplateLine.id).filter(TemplateLine.variant_id == existing.id).first():
                raise HTTPException(400, f"Variant '{existing.value}' is used by a subscription or template "
                                         "and cannot be removed.")
            product.variants.remove(existing)
    by_id = {v.id: v for v in product.variants}
    for v in body.variants:
        if v.id and v.id in by_id:
            by_id[v.id].attribute, by_id[v.id].value, by_id[v.id].extra_price = v.attribute, v.value, v.extra_price
        else:
            product.variants.append(ProductVariant(attribute=v.attribute, value=v.value, extra_price=v.extra_price))


@router.post("/products")
def add_product(body: ProductIn, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    product = Product()
    _save_product(db, product, body)
    db.add(product)
    db.commit()
    return product_out(product)


@router.put("/products/{product_id}")
def edit_product(product_id: int, body: ProductIn, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    product = get_or_404(db, Product, product_id, "Product")
    _save_product(db, product, body)
    db.commit()
    return product_out(product)


# ------------------------------------------------------------------ plans
@router.get("/plans")
def list_plans(user: User = Depends(current_user), db: Session = Depends(get_db)):
    plans = db.query(Plan).options(selectinload(Plan.tax)).order_by(Plan.price).all()
    if user.role == "customer":
        plans = [p for p in plans if plan_is_available(p, date.today())]
    return [plan_out(p) for p in plans]


@router.post("/plans")
def add_plan(body: PlanIn, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    tax_lookup(db, body.tax_id)
    plan = Plan(**body.model_dump())
    db.add(plan)
    db.commit()
    return plan_out(plan)


@router.put("/plans/{plan_id}")
def edit_plan(plan_id: int, body: PlanIn, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    plan = get_or_404(db, Plan, plan_id, "Plan")
    tax_lookup(db, body.tax_id)
    for k, v in body.model_dump().items():
        setattr(plan, k, v)
    db.commit()
    return plan_out(plan)


# ------------------------------------------------------------------ discounts (admin only)
@router.get("/discounts")
def list_discounts(_: User = Depends(internal), db: Session = Depends(get_db)):
    return [discount_out(d) for d in db.query(Discount).order_by(Discount.code)]


def _check_discount(db: Session, body: DiscountIn, discount_id: int | None = None):
    if body.product_id:
        get_or_404(db, Product, body.product_id, "Product")
    clash = db.query(Discount).filter(Discount.code == body.code)
    if discount_id:
        clash = clash.filter(Discount.id != discount_id)
    if clash.first():
        raise HTTPException(409, "That discount code already exists.")


@router.post("/discounts")
def add_discount(body: DiscountIn, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    _check_discount(db, body)
    discount = Discount(**body.model_dump())
    db.add(discount)
    db.commit()
    return discount_out(discount)


@router.put("/discounts/{discount_id}")
def edit_discount(discount_id: int, body: DiscountIn, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    discount = get_or_404(db, Discount, discount_id, "Discount")
    _check_discount(db, body, discount_id)
    for k, v in body.model_dump().items():
        setattr(discount, k, v)
    db.commit()
    return discount_out(discount)


# ------------------------------------------------------------------ quotation templates
@router.get("/templates")
def list_templates(_: User = Depends(internal), db: Session = Depends(get_db)):
    return [template_out(t) for t in db.query(QuotationTemplate).order_by(QuotationTemplate.name)]


def _save_template(db: Session, tpl: QuotationTemplate, body: TemplateIn):
    get_or_404(db, Plan, body.plan_id, "Plan")
    for k, v in body.model_dump(exclude={"lines"}).items():
        setattr(tpl, k, v)
    tpl.lines.clear()
    for line in body.lines:
        product = get_or_404(db, Product, line.product_id, "Product")
        if line.variant_id:
            variant = get_or_404(db, ProductVariant, line.variant_id, "Variant")
            if variant.product_id != product.id:
                raise HTTPException(400, "That variant does not belong to the chosen product.")
        tpl.lines.append(TemplateLine(product_id=line.product_id, variant_id=line.variant_id, quantity=line.quantity))


@router.post("/templates")
def add_template(body: TemplateIn, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    tpl = QuotationTemplate()
    _save_template(db, tpl, body)
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return template_out(tpl)


@router.put("/templates/{template_id}")
def edit_template(template_id: int, body: TemplateIn, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    tpl = get_or_404(db, QuotationTemplate, template_id, "Quotation template")
    _save_template(db, tpl, body)
    db.commit()
    db.refresh(tpl)
    return template_out(tpl)
