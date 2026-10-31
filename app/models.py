"""Database tables."""
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


def Money(nullable=False, default=0):
    # Stored as an exact decimal column, read back as a float rounded to cents.
    return Column(Numeric(12, 2, asdecimal=False), nullable=nullable, default=default)


# ------------------------------------------------------------------ people
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="customer", index=True)  # admin | staff | customer
    is_active = Column(Boolean, nullable=False, default=True)
    company = Column(String(200))
    phone = Column(String(50))
    address = Column(String(500))
    department = Column(String(100))
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    token = Column(String(128), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)

    user = relationship("User")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(128), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, nullable=False, default=False)

    user = relationship("User")


# ------------------------------------------------------------------ catalog
class Tax(Base):
    __tablename__ = "taxes"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    rate = Column(Numeric(6, 2, asdecimal=False), nullable=False)  # percent, e.g. 18.00
    is_active = Column(Boolean, nullable=False, default=True)


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    product_type = Column(String(30), nullable=False, default="service")  # service | goods | addon
    sales_price = Money()
    cost_price = Money()
    notes = Column(Text)
    tax_id = Column(Integer, ForeignKey("taxes.id"))
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    tax = relationship("Tax")
    variants = relationship("ProductVariant", back_populates="product", cascade="all, delete-orphan",
                            order_by="ProductVariant.id")


class ProductVariant(Base):
    __tablename__ = "product_variants"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    attribute = Column(String(100), nullable=False)  # e.g. Brand
    value = Column(String(100), nullable=False)      # e.g. Odoo
    extra_price = Money()                            # e.g. 560

    product = relationship("Product", back_populates="variants")


class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    price = Money()
    billing_period = Column(String(20), nullable=False, default="monthly")  # daily | weekly | monthly | yearly
    min_quantity = Column(Integer, nullable=False, default=1)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)
    auto_close = Column(Boolean, nullable=False, default=False)  # close subscriptions on their own at expiry
    closable = Column(Boolean, nullable=False, default=True)     # can be closed early
    pausable = Column(Boolean, nullable=False, default=False)
    renewable = Column(Boolean, nullable=False, default=True)
    tax_id = Column(Integer, ForeignKey("taxes.id"))
    is_active = Column(Boolean, nullable=False, default=True)

    tax = relationship("Tax")


class Discount(Base):
    __tablename__ = "discounts"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    discount_type = Column(String(20), nullable=False, default="percentage")  # percentage | fixed
    value = Money()
    min_amount = Money()
    min_quantity = Column(Integer, nullable=False, default=0)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)
    usage_limit = Column(Integer)                 # empty = unlimited
    used_count = Column(Integer, nullable=False, default=0)
    applies_to = Column(String(20), nullable=False, default="subscription")  # subscription | product
    product_id = Column(Integer, ForeignKey("products.id"))
    is_active = Column(Boolean, nullable=False, default=True)

    product = relationship("Product")


class QuotationTemplate(Base):
    __tablename__ = "quotation_templates"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    validity_days = Column(Integer, nullable=False, default=30)
    plan_quantity = Column(Integer, nullable=False, default=1)
    notes = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)

    plan = relationship("Plan")
    lines = relationship("TemplateLine", cascade="all, delete-orphan", order_by="TemplateLine.id")


class TemplateLine(Base):
    __tablename__ = "quotation_template_lines"

    id = Column(Integer, primary_key=True)
    template_id = Column(Integer, ForeignKey("quotation_templates.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    variant_id = Column(Integer, ForeignKey("product_variants.id"))
    quantity = Column(Integer, nullable=False, default=1)

    product = relationship("Product")
    variant = relationship("ProductVariant")


# ------------------------------------------------------------------ subscriptions
class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    number = Column(String(30), unique=True, index=True)
    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False, index=True)
    template_id = Column(Integer, ForeignKey("quotation_templates.id"))
    # Draft -> Quotation -> Confirmed -> Active -> Closed
    status = Column(String(20), nullable=False, default="draft", index=True)
    start_date = Column(Date, nullable=False)
    expiry_date = Column(Date)
    term_days = Column(Integer)  # contract length, used when renewing
    payment_terms_days = Column(Integer, nullable=False, default=15)
    quote_valid_until = Column(Date)
    next_invoice_date = Column(Date, index=True)
    discount_id = Column(Integer, ForeignKey("discounts.id"))
    paused = Column(Boolean, nullable=False, default=False)
    notes = Column(Text)
    created_by_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    closed_at = Column(DateTime)

    customer = relationship("User", foreign_keys=[customer_id])
    plan = relationship("Plan")
    discount = relationship("Discount")
    lines = relationship("SubscriptionLine", back_populates="subscription", cascade="all, delete-orphan",
                         order_by="SubscriptionLine.id")
    audit_logs = relationship("AuditLog", back_populates="subscription", cascade="all, delete-orphan",
                              order_by="AuditLog.id")


class SubscriptionLine(Base):
    __tablename__ = "subscription_lines"

    id = Column(Integer, primary_key=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))  # empty for the plan line itself
    variant_id = Column(Integer, ForeignKey("product_variants.id"))
    description = Column(String(300), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Money()
    tax_id = Column(Integer, ForeignKey("taxes.id"))

    subscription = relationship("Subscription", back_populates="lines")
    product = relationship("Product")
    variant = relationship("ProductVariant")
    tax = relationship("Tax")


class AuditLog(Base):
    __tablename__ = "subscription_audit_logs"

    id = Column(Integer, primary_key=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(50), nullable=False)
    from_status = Column(String(20))
    to_status = Column(String(20))
    user_name = Column(String(120))
    note = Column(String(500))
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    subscription = relationship("Subscription", back_populates="audit_logs")


# ------------------------------------------------------------------ invoicing
class Invoice(Base):
    __tablename__ = "invoices"
    # One invoice per subscription per billing period: nothing can be billed twice.
    __table_args__ = (UniqueConstraint("subscription_id", "period_start", name="uq_invoice_period"),)

    id = Column(Integer, primary_key=True)
    number = Column(String(30), unique=True, index=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="draft", index=True)  # draft | confirmed | paid | cancelled
    issue_date = Column(Date, nullable=False, index=True)
    due_date = Column(Date, nullable=False, index=True)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    subtotal = Money()
    discount_total = Money()
    tax_total = Money()
    total = Money()
    amount_paid = Money()
    discount_code = Column(String(50))
    sent_at = Column(DateTime)
    notes = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    customer = relationship("User")
    subscription = relationship("Subscription")
    lines = relationship("InvoiceLine", cascade="all, delete-orphan", order_by="InvoiceLine.id")
    payments = relationship("Payment", back_populates="invoice", cascade="all, delete-orphan",
                            order_by="Payment.id")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id = Column(Integer, primary_key=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    description = Column(String(300), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Money()
    subtotal = Money()
    discount_amount = Money()
    tax_name = Column(String(100))
    tax_rate = Column(Numeric(6, 2, asdecimal=False), nullable=False, default=0)
    tax_amount = Money()
    total = Money()


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Money()
    method = Column(String(30), nullable=False)  # cash | bank_transfer | card | upi | cheque
    payment_date = Column(Date, nullable=False, index=True)
    note = Column(String(500))
    recorded_by = Column(String(120))
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    invoice = relationship("Invoice", back_populates="payments")
