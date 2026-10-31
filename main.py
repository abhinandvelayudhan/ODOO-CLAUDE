"""INTRINSIC — Subscription & Invoicing Management (FastAPI + SQLAlchemy + SQLite)."""
import hashlib, hmac, os, re, secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

BASE = os.path.dirname(os.path.abspath(__file__))
engine = create_engine(f"sqlite:///{BASE}/intrinsic.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base = declarative_base()

FLOW = {"Draft": ["Quotation"], "Quotation": ["Confirmed"], "Confirmed": ["Active"], "Active": ["Closed"], "Closed": []}
DEMO = {"admin": ("admin@intrinsic.io", "Admin", "Admin@1234!", "Ava Admin"),
        "staff": ("staff@intrinsic.io", "Staff", "Staff@1234!", "Sam Staff"),
        "customer": ("customer@intrinsic.io", "Customer", "Customer@123!", "Casey Customer")}


# ---------------------------------------------------------------- models
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="Customer")
    created_at = Column(DateTime, default=datetime.utcnow)


class AuthToken(Base):
    __tablename__ = "tokens"
    token = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    expires = Column(DateTime)
    user = relationship(User)


class Plan(Base):
    __tablename__ = "plans"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    interval = Column(String, default="monthly")  # monthly | yearly


class Discount(Base):
    __tablename__ = "discounts"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, nullable=False)
    percent = Column(Float, nullable=False)
    active = Column(Boolean, default=True)


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("users.id"))
    plan_id = Column(Integer, ForeignKey("plans.id"))
    discount_id = Column(Integer, ForeignKey("discounts.id"), nullable=True)
    status = Column(String, default="Draft")
    start_date = Column(Date, nullable=True)
    next_billing = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    customer = relationship(User)
    plan = relationship(Plan)
    discount = relationship(Discount)


class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True)
    number = Column(String)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"))
    customer_id = Column(Integer, ForeignKey("users.id"))
    gross = Column(Float)
    discount_amount = Column(Float, default=0)
    amount = Column(Float)
    status = Column(String, default="Pending")  # Pending | Paid | Overdue
    issued_at = Column(Date)
    due_date = Column(Date)
    paid_at = Column(Date, nullable=True)
    customer = relationship(User)
    subscription = relationship(Subscription)


# ---------------------------------------------------------------- security
def hash_pw(pw: str) -> str:
    salt = secrets.token_hex(16)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000).hex()


def verify_pw(pw: str, stored: str) -> bool:
    salt, digest = stored.split("$")
    test = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000).hex()
    return hmac.compare_digest(test, digest)


def check_password(p: str) -> str:
    if len(p) <= 8:
        raise ValueError("Password must be more than 8 characters.")
    if not re.search(r"[A-Z]", p):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", p):
        raise ValueError("Password must contain at least one lowercase letter.")
    if not re.search(r"[^A-Za-z0-9\s]", p):
        raise ValueError("Password must contain at least one special character.")
    return p


class LoginIn(BaseModel):
    email: str
    password: str


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        v = v.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Enter a valid email address.")
        return v

    @field_validator("password")
    @classmethod
    def _pw(cls, v):
        return check_password(v)


class StaffIn(RegisterIn):
    role: str

    @field_validator("role")
    @classmethod
    def _role(cls, v):
        if v not in ("Staff", "Admin"):
            raise ValueError("Role must be Staff or Admin.")
        return v


class SubIn(BaseModel):
    plan_id: int
    customer_id: int | None = None
    code: str | None = None


class TransitionIn(BaseModel):
    to: str


class PlanIn(BaseModel):
    name: str = Field(min_length=2)
    price: float = Field(gt=0)
    interval: str = Field(pattern="^(monthly|yearly)$")


class DiscountIn(BaseModel):
    code: str = Field(min_length=3)
    percent: float = Field(gt=0, le=100)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(authorization: str = Header(None), db=Depends(get_db)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Please sign in to continue.")
    t = db.get(AuthToken, authorization[7:])
    if not t or t.expires < datetime.utcnow():
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    return t.user


def require(*roles):
    def dep(u: User = Depends(current_user)):
        if u.role not in roles:
            raise HTTPException(403, "You do not have permission for this action.")
        return u
    return dep


def issue_token(db, user: User) -> dict:
    tok = secrets.token_urlsafe(32)
    db.add(AuthToken(token=tok, user_id=user.id, expires=datetime.utcnow() + timedelta(hours=12)))
    db.commit()
    return {"token": tok, "user": user_out(user)}


# ---------------------------------------------------------------- serializers / logic
def user_out(u):
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role,
            "created_at": u.created_at.strftime("%Y-%m-%d") if u.created_at else None}


def net_price(s: Subscription) -> float:
    pct = s.discount.percent if s.discount and s.discount.active else 0
    return round(s.plan.price * (1 - pct / 100), 2)


def sub_out(s):
    return {"id": s.id, "customer_id": s.customer_id, "customer": s.customer.name, "plan": s.plan.name,
            "interval": s.plan.interval, "price": s.plan.price, "net_price": net_price(s),
            "discount": s.discount.code if s.discount else None, "status": s.status,
            "next_billing": s.next_billing.isoformat() if s.next_billing else None,
            "start_date": s.start_date.isoformat() if s.start_date else None}


def inv_out(i):
    return {"id": i.id, "number": i.number, "customer": i.customer.name, "plan": i.subscription.plan.name,
            "gross": i.gross, "discount_amount": i.discount_amount, "amount": i.amount, "status": i.status,
            "issued_at": i.issued_at.isoformat(), "due_date": i.due_date.isoformat(),
            "paid_at": i.paid_at.isoformat() if i.paid_at else None}


def mark_overdue(db):
    db.query(Invoice).filter(Invoice.status == "Pending", Invoice.due_date < date.today()).update({"status": "Overdue"})
    db.commit()


def make_invoice(db, s: Subscription, issued: date, status="Pending", paid=None):
    pct = s.discount.percent if s.discount and s.discount.active else 0
    disc = round(s.plan.price * pct / 100, 2)
    inv = Invoice(subscription_id=s.id, customer_id=s.customer_id, gross=s.plan.price, discount_amount=disc,
                  amount=round(s.plan.price - disc, 2), status=status, issued_at=issued,
                  due_date=issued + timedelta(days=14), paid_at=paid)
    db.add(inv)
    db.flush()
    inv.number = f"INV-{inv.id:05d}"
    return inv


def run_billing(db) -> int:
    """Invoice every Active subscription whose next billing date has arrived."""
    today, created = date.today(), 0
    for s in db.query(Subscription).filter(Subscription.status == "Active", Subscription.next_billing <= today).all():
        step = 365 if s.plan.interval == "yearly" else 30
        for _ in range(12):
            if s.next_billing > today:
                break
            make_invoice(db, s, s.next_billing)
            s.next_billing += timedelta(days=step)
            created += 1
    db.commit()
    mark_overdue(db)
    return created


# ---------------------------------------------------------------- seed
def seed(db):
    if db.query(User).count():
        return
    users = {}
    for k, (email, role, pw, name) in DEMO.items():
        users[k] = User(name=name, email=email, role=role, password_hash=hash_pw(pw))
    extra = [User(name=n, email=e, role="Customer", password_hash=hash_pw("Customer@123!"))
             for n, e in [("Northwind Labs", "billing@northwind.io"), ("Acme Retail", "ap@acme.io"), ("Helio Studio", "hi@helio.io")]]
    db.add_all(list(users.values()) + extra)
    plans = [Plan(name="Starter", price=29, interval="monthly"), Plan(name="Growth", price=99, interval="monthly"),
             Plan(name="Scale", price=990, interval="yearly")]
    discounts = [Discount(code="WELCOME10", percent=10), Discount(code="ANNUAL20", percent=20)]
    db.add_all(plans + discounts)
    db.flush()
    c1, c2, c3, c4 = users["customer"], *extra
    today = date.today()
    spec = [(c1, plans[1], "Active", discounts[0], 0), (c2, plans[2], "Active", discounts[1], 15),
            (c3, plans[0], "Active", None, 15), (c4, plans[1], "Quotation", None, None),
            (c3, plans[1], "Draft", None, None), (c2, plans[0], "Closed", None, None)]
    for cust, plan, st, disc, nb in spec:
        s = Subscription(customer_id=cust.id, plan_id=plan.id, discount_id=disc.id if disc else None, status=st,
                         start_date=today - timedelta(days=60) if st in ("Active", "Closed") else None,
                         next_billing=today + timedelta(days=nb) if nb is not None else None)
        db.add(s)
        db.flush()
        if st == "Active":
            make_invoice(db, s, today - timedelta(days=60), "Paid", today - timedelta(days=55))
            if cust is c3:
                make_invoice(db, s, today - timedelta(days=30))  # becomes Overdue
            else:
                make_invoice(db, s, today - timedelta(days=30), "Paid", today - timedelta(days=26))
    db.commit()
    mark_overdue(db)


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title="INTRINSIC", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_handler(request, exc):
    msgs = []
    for e in exc.errors():
        m = e["msg"]
        msgs.append(m.replace("Value error, ", "") if m.startswith("Value error") else f"{e['loc'][-1]}: {m}")
    return JSONResponse({"detail": " ".join(msgs)}, status_code=422)


# ---------------------------------------------------------------- auth
@app.post("/api/auth/register")
def register(body: RegisterIn, db=Depends(get_db)):
    if db.query(User).filter_by(email=body.email).first():
        raise HTTPException(409, "An account with this email already exists.")
    u = User(name=body.name.strip(), email=body.email, role="Customer", password_hash=hash_pw(body.password))  # role is forced
    db.add(u)
    db.commit()
    return issue_token(db, u)


@app.post("/api/auth/login")
def login(body: LoginIn, db=Depends(get_db)):
    u = db.query(User).filter_by(email=body.email.strip().lower()).first()
    if not u or not verify_pw(body.password, u.password_hash):
        raise HTTPException(401, "Incorrect email or password.")
    return issue_token(db, u)


@app.post("/api/auth/demo/{persona}")
def demo_login(persona: str, db=Depends(get_db)):
    if persona not in DEMO:
        raise HTTPException(404, "Unknown persona.")
    return issue_token(db, db.query(User).filter_by(email=DEMO[persona][0]).first())


@app.post("/api/auth/logout")
def logout(authorization: str = Header(None), db=Depends(get_db)):
    if authorization and authorization.startswith("Bearer "):
        t = db.get(AuthToken, authorization[7:])
        if t:
            db.delete(t)
            db.commit()
    return {"ok": True}


@app.get("/api/auth/me")
def me(u: User = Depends(current_user)):
    return user_out(u)


# ---------------------------------------------------------------- team management (Admin)
@app.get("/api/users")
def list_users(u=Depends(require("Admin")), db=Depends(get_db)):
    return [user_out(x) for x in db.query(User).order_by(User.role, User.name)]


@app.post("/api/users")
def create_user(body: StaffIn, u=Depends(require("Admin")), db=Depends(get_db)):
    if db.query(User).filter_by(email=body.email).first():
        raise HTTPException(409, "An account with this email already exists.")
    n = User(name=body.name.strip(), email=body.email, role=body.role, password_hash=hash_pw(body.password))
    db.add(n)
    db.commit()
    return user_out(n)


@app.get("/api/customers")
def customers(u=Depends(require("Admin", "Staff")), db=Depends(get_db)):
    return [user_out(x) for x in db.query(User).filter_by(role="Customer").order_by(User.name)]


# ---------------------------------------------------------------- catalog
@app.get("/api/plans")
def plans(u=Depends(current_user), db=Depends(get_db)):
    return [{"id": p.id, "name": p.name, "price": p.price, "interval": p.interval} for p in db.query(Plan)]


@app.post("/api/plans")
def add_plan(body: PlanIn, u=Depends(require("Admin")), db=Depends(get_db)):
    db.add(Plan(**body.model_dump()))
    db.commit()
    return {"ok": True}


@app.get("/api/discounts")
def discounts(u=Depends(require("Admin", "Staff")), db=Depends(get_db)):
    return [{"id": d.id, "code": d.code, "percent": d.percent, "active": d.active} for d in db.query(Discount)]


@app.post("/api/discounts")
def add_discount(body: DiscountIn, u=Depends(require("Admin")), db=Depends(get_db)):
    code = body.code.strip().upper()
    if db.query(Discount).filter_by(code=code).first():
        raise HTTPException(409, "That discount code already exists.")
    db.add(Discount(code=code, percent=body.percent))
    db.commit()
    return {"ok": True}


@app.post("/api/discounts/{did}/toggle")
def toggle_discount(did: int, u=Depends(require("Admin")), db=Depends(get_db)):
    d = db.get(Discount, did)
    if not d:
        raise HTTPException(404, "Discount not found.")
    d.active = not d.active
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- subscriptions
@app.get("/api/subscriptions")
def list_subs(u=Depends(current_user), db=Depends(get_db)):
    q = db.query(Subscription).order_by(Subscription.id.desc())
    if u.role == "Customer":
        q = q.filter(Subscription.customer_id == u.id)
    return [sub_out(s) for s in q]


@app.post("/api/subscriptions")
def create_sub(body: SubIn, u=Depends(current_user), db=Depends(get_db)):
    cust_id = u.id if u.role == "Customer" else body.customer_id
    if not cust_id or not db.get(User, cust_id):
        raise HTTPException(400, "Choose a customer.")
    if not db.get(Plan, body.plan_id):
        raise HTTPException(400, "Choose a plan.")
    disc = None
    if body.code and body.code.strip():
        disc = db.query(Discount).filter_by(code=body.code.strip().upper(), active=True).first()
        if not disc:
            raise HTTPException(400, "That discount code is invalid or inactive.")
    s = Subscription(customer_id=cust_id, plan_id=body.plan_id, discount_id=disc.id if disc else None, status="Draft")
    db.add(s)
    db.commit()
    return sub_out(s)


@app.post("/api/subscriptions/{sid}/transition")
def transition(sid: int, body: TransitionIn, u=Depends(current_user), db=Depends(get_db)):
    s = db.get(Subscription, sid)
    if not s:
        raise HTTPException(404, "Subscription not found.")
    if u.role == "Customer" and (s.customer_id != u.id or body.to != "Closed"):
        raise HTTPException(403, "Customers can only cancel their own subscriptions.")
    allowed = {*FLOW[s.status], "Closed"} - {s.status}
    if body.to not in allowed:
        raise HTTPException(400, f"A {s.status} subscription cannot move to {body.to}.")
    if body.to == "Active":
        s.start_date = s.next_billing = date.today()
    s.status = body.to
    db.commit()
    return sub_out(s)


# ---------------------------------------------------------------- invoices / billing
@app.get("/api/invoices")
def list_invoices(u=Depends(current_user), db=Depends(get_db)):
    mark_overdue(db)
    q = db.query(Invoice).order_by(Invoice.id.desc())
    if u.role == "Customer":
        q = q.filter(Invoice.customer_id == u.id)
    return [inv_out(i) for i in q]


@app.post("/api/invoices/{iid}/pay")
def pay(iid: int, u=Depends(current_user), db=Depends(get_db)):
    i = db.get(Invoice, iid)
    if not i or (u.role == "Customer" and i.customer_id != u.id):
        raise HTTPException(404, "Invoice not found.")
    if i.status == "Paid":
        raise HTTPException(400, "This invoice is already paid.")
    i.status, i.paid_at = "Paid", date.today()
    db.commit()
    return inv_out(i)


@app.post("/api/billing/run")
def billing(u=Depends(require("Admin", "Staff")), db=Depends(get_db)):
    return {"created": run_billing(db)}


@app.get("/api/kpis")
def kpis(u=Depends(current_user), db=Depends(get_db)):
    mark_overdue(db)
    sq = db.query(Subscription).filter(Subscription.status == "Active")
    iq = db.query(Invoice)
    if u.role == "Customer":
        sq, iq = sq.filter(Subscription.customer_id == u.id), iq.filter(Invoice.customer_id == u.id)
    active = sq.all()
    mrr = sum(net_price(s) / (12 if s.plan.interval == "yearly" else 1) for s in active)
    overdue = iq.filter(Invoice.status == "Overdue").all()
    paid = iq.filter(Invoice.status == "Paid").all()
    return {"mrr": round(mrr, 2), "active": len(active), "overdue": len(overdue),
            "overdue_amount": round(sum(i.amount for i in overdue), 2),
            "revenue": round(sum(i.amount for i in paid), 2)}


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
