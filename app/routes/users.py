"""Team management (admin) and the customer directory (admin + staff)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuthToken, Subscription, User
from app.schemas import RegisterIn, StaffIn
from app.security import admin_only, hash_password, internal
from app.serializers import user_out

router = APIRouter(prefix="/api", tags=["Users"])


@router.get("/users")
def list_team(role: str | None = None, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    q = db.query(User).filter(User.role.in_(["admin", "staff"]))
    if role:
        q = q.filter(User.role == role)
    return [user_out(u) for u in q.order_by(User.role, User.name)]


@router.post("/users")
def add_team_member(body: StaffIn, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    """Only an admin can add a new member of staff (or another admin)."""
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(409, "An account with this email already exists.")
    user = User(name=body.name.strip(), email=body.email, password_hash=hash_password(body.password),
                role=body.role, department=body.department)
    db.add(user)
    db.commit()
    return user_out(user)


@router.post("/users/{user_id}/toggle-active")
def toggle_active(user_id: int, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found.")
    if user.id == admin.id:
        raise HTTPException(400, "You cannot deactivate your own account.")
    user.is_active = not user.is_active
    if not user.is_active:
        db.query(AuthToken).filter(AuthToken.user_id == user.id).delete()  # sign them out
    db.commit()
    return user_out(user)


@router.get("/customers")
def list_customers(q: str | None = None, _: User = Depends(internal), db: Session = Depends(get_db)):
    active_subs = (db.query(Subscription.customer_id, func.count(Subscription.id))
                   .filter(Subscription.status == "active").group_by(Subscription.customer_id).all())
    counts = dict(active_subs)
    query = db.query(User).filter(User.role == "customer")
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(User.name.ilike(like), User.email.ilike(like), User.company.ilike(like)))
    out = []
    for u in query.order_by(User.name).limit(500):
        row = user_out(u)
        row["active_subscriptions"] = counts.get(u.id, 0)
        out.append(row)
    return out


@router.post("/customers")
def add_customer(body: RegisterIn, _: User = Depends(internal), db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(409, "An account with this email already exists.")
    user = User(name=body.name.strip(), email=body.email, password_hash=hash_password(body.password),
                role="customer", company=body.company, phone=body.phone, address=body.address)
    db.add(user)
    db.commit()
    return user_out(user)
