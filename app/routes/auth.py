"""Sign up, sign in, sign out and password reset."""
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.mailer import send_email, smtp_configured
from app.models import AuthToken, PasswordResetToken, User
from app.schemas import ForgotIn, LoginIn, ProfileIn, RegisterIn, ResetIn
from app.security import RESET_MINUTES, current_user, hash_password, hash_token, issue_session, verify_password
from app.serializers import user_out

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/register")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    """Public sign-up always creates a customer account. Only an admin can add staff."""
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(409, "An account with this email already exists.")
    user = User(name=body.name.strip(), email=body.email, password_hash=hash_password(body.password),
                role="customer", company=body.company, phone=body.phone, address=body.address)
    db.add(user)
    db.commit()
    return {"token": issue_session(db, user), "user": user_out(user)}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.strip().lower()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password.")
    if not user.is_active:
        raise HTTPException(403, "This account has been deactivated. Contact an administrator.")
    return {"token": issue_session(db, user), "user": user_out(user)}


@router.post("/logout")
def logout(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    if authorization and authorization.startswith("Bearer "):
        row = db.get(AuthToken, authorization[7:])
        if row:
            db.delete(row)
            db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


@router.put("/me")
def update_profile(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user = db.merge(user)
    user.name, user.company, user.phone, user.address = body.name.strip(), body.company, body.phone, body.address
    db.commit()
    return user_out(user)


@router.post("/forgot-password")
def forgot_password(body: ForgotIn, request: Request, db: Session = Depends(get_db)):
    """Email a single-use reset link that expires after 30 minutes."""
    message = "If an account exists for that email, a password reset link has been sent to it."
    user = db.query(User).filter(User.email == body.email.strip().lower(), User.is_active.is_(True)).first()
    if not user:
        return {"message": message}

    token = secrets.token_urlsafe(32)
    db.add(PasswordResetToken(user_id=user.id, token_hash=hash_token(token),
                              expires_at=datetime.now() + timedelta(minutes=RESET_MINUTES)))
    db.commit()
    link = f"{str(request.base_url).rstrip('/')}/#reset?token={token}"
    sent = send_email(user.email, "Reset your INTRINSIC password",
                      f"Hi {user.name},\n\nUse this link to choose a new password. It expires in "
                      f"{RESET_MINUTES} minutes and works once:\n\n{link}\n\n"
                      "If you did not ask for this, you can ignore this email.")
    result = {"message": message}
    if not sent and not smtp_configured():
        # Demo mode (no mail server configured): hand the link back so the flow can be tried end to end.
        result["demo_reset_link"] = link
    return result


@router.post("/reset-password")
def reset_password(body: ResetIn, db: Session = Depends(get_db)):
    row = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == hash_token(body.token)).first()
    if not row or row.used or row.expires_at < datetime.now():
        raise HTTPException(400, "This reset link is invalid or has expired. Please request a new one.")
    row.used = True
    row.user.password_hash = hash_password(body.password)
    db.query(AuthToken).filter(AuthToken.user_id == row.user_id).delete()  # sign out everywhere
    db.commit()
    return {"message": "Your password has been changed. You can now sign in."}
