"""Request bodies, validated before they reach the business logic."""
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.security import validate_password

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_email(value: str) -> str:
    value = (value or "").strip().lower()
    if not EMAIL_RE.match(value):
        raise ValueError("Enter a valid email address.")
    return value


# ------------------------------------------------------------------ auth & people
class LoginIn(BaseModel):
    email: str
    password: str


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str
    password: str
    company: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=50)
    address: str | None = Field(None, max_length=500)

    _email = field_validator("email")(clean_email)

    @field_validator("password")
    @classmethod
    def _password(cls, v):
        return validate_password(v)


class ForgotIn(BaseModel):
    email: str


class ResetIn(BaseModel):
    token: str = Field(min_length=10)
    password: str

    @field_validator("password")
    @classmethod
    def _password(cls, v):
        return validate_password(v)


class StaffIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str
    password: str
    role: Literal["staff", "admin"] = "staff"
    department: str | None = Field(None, max_length=100)

    _email = field_validator("email")(clean_email)

    @field_validator("password")
    @classmethod
    def _password(cls, v):
        return validate_password(v)


class ProfileIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    company: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=50)
    address: str | None = Field(None, max_length=500)


# ------------------------------------------------------------------ catalog
class TaxIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    rate: float = Field(ge=0, le=100)
    is_active: bool = True


class VariantIn(BaseModel):
    id: int | None = None  # set when editing an existing variant
    attribute: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=100)
    extra_price: float = Field(0, ge=0)


class ProductIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    product_type: Literal["service", "goods", "addon"] = "service"
    sales_price: float = Field(ge=0)
    cost_price: float = Field(0, ge=0)
    notes: str | None = None
    tax_id: int | None = None
    is_active: bool = True
    variants: list[VariantIn] = []


class PlanIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None
    price: float = Field(ge=0)
    billing_period: Literal["daily", "weekly", "monthly", "yearly"] = "monthly"
    min_quantity: int = Field(1, ge=1)
    start_date: date
    end_date: date | None = None
    auto_close: bool = False
    closable: bool = True
    pausable: bool = False
    renewable: bool = True
    tax_id: int | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def _dates(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("The plan's end date must be on or after its start date.")
        return self


class DiscountIn(BaseModel):
    code: str = Field(min_length=3, max_length=50)
    name: str = Field(min_length=2, max_length=200)
    discount_type: Literal["percentage", "fixed"] = "percentage"
    value: float = Field(gt=0)
    min_amount: float = Field(0, ge=0)
    min_quantity: int = Field(0, ge=0)
    start_date: date
    end_date: date | None = None
    usage_limit: int | None = Field(None, ge=1)
    applies_to: Literal["subscription", "product"] = "subscription"
    product_id: int | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def _check(self):
        self.code = self.code.strip().upper()
        if self.discount_type == "percentage" and self.value > 100:
            raise ValueError("A percentage discount cannot be more than 100%.")
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("The discount's end date must be on or after its start date.")
        if self.applies_to == "product" and not self.product_id:
            raise ValueError("Choose the product this discount applies to.")
        if self.applies_to == "subscription":
            self.product_id = None
        return self


class LineIn(BaseModel):
    product_id: int
    variant_id: int | None = None
    quantity: int = Field(1, ge=1, le=100000)


class TemplateIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    plan_id: int
    plan_quantity: int = Field(1, ge=1)
    validity_days: int = Field(30, ge=1, le=365)
    notes: str | None = None
    is_active: bool = True
    lines: list[LineIn] = []


# ------------------------------------------------------------------ subscriptions
class SubscriptionIn(BaseModel):
    customer_id: int | None = None          # ignored for customers (always themselves)
    plan_id: int | None = None
    template_id: int | None = None          # start from a quotation template
    plan_quantity: int = Field(1, ge=1)
    start_date: date | None = None
    expiry_date: date | None = None
    payment_terms_days: int = Field(15, ge=0, le=180)
    discount_code: str | None = None
    notes: str | None = None
    lines: list[LineIn] = []

    @model_validator(mode="after")
    def _check(self):
        if not self.plan_id and not self.template_id:
            raise ValueError("Choose a plan or a quotation template.")
        if self.start_date and self.expiry_date and self.expiry_date <= self.start_date:
            raise ValueError("The expiry date must be after the start date.")
        return self


class TransitionIn(BaseModel):
    to: Literal["quotation", "confirmed", "active", "closed"]
    note: str | None = Field(None, max_length=500)


class PaymentIn(BaseModel):
    amount: float = Field(gt=0)
    method: Literal["cash", "bank_transfer", "card", "upi", "cheque"]
    payment_date: date | None = None
    note: str | None = Field(None, max_length=500)


class PortalPayIn(BaseModel):
    method: Literal["card", "upi", "bank_transfer"] = "card"
