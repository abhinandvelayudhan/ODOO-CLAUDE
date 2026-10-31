"""Passwords, sign-in sessions and role checks."""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuthToken, User

SESSION_HOURS = 12
RESET_MINUTES = 30
PBKDF2_ROUNDS = 200_000


# ------------------------------------------------------------------ passwords
def validate_password(password: str) -> str:
    """More than 8 characters, one uppercase, one lowercase and one special character."""
    if not password or len(password) <= 8:
        raise ValueError("Password must be more than 8 characters long.")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter.")
    if not re.search(r"[^A-Za-z0-9\s]", password):
        raise ValueError("Password must contain at least one special character.")
    return password


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ROUNDS).hex()
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, digest = stored.split("$")
        test = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds)).hex()
        return hmac.compare_digest(test, digest)
    except (ValueError, AttributeError):
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ------------------------------------------------------------------ sessions
def issue_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(AuthToken(token=token, user_id=user.id, expires_at=datetime.now() + timedelta(hours=SESSION_HOURS)))
    db.commit()
    return token


def current_user(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Please sign in to continue.")
    row = db.get(AuthToken, authorization[7:])
    if not row or row.expires_at < datetime.now():
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    if not row.user.is_active:
        raise HTTPException(403, "This account has been deactivated. Contact an administrator.")
    return row.user


def require(*roles: str):
    """Dependency that only lets the given roles through."""
    def check(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "You do not have permission for this action.")
        return user
    return check


admin_only = require("admin")
internal = require("admin", "staff")
