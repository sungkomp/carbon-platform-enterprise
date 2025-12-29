from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Callable
import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.auth.models import User

bearer = HTTPBearer()

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))

def create_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.username,
        "roles": user.roles,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=12)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except Exception:
        raise HTTPException(401, "Invalid token")

def get_current_user(
    cred: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    data = decode_token(cred.credentials)
    u = db.query(User).filter(User.username == data["sub"]).one_or_none()
    if not u or not u.is_active:
        raise HTTPException(401, "User not found/inactive")
    return u

def require_roles(*required: str) -> Callable:
    def dep(user: User = Depends(get_current_user)) -> User:
        if "ADMIN" in user.roles:
            return user
        if not set(required).intersection(set(user.roles)):
            raise HTTPException(403, f"Requires role(s): {required}")
        return user
    return dep

from fastapi import Request
from app.tenancy.models import OrgMember, Org

def get_org_roles(db: Session, username: str, org: Org) -> list[str]:
    u = db.query(User).filter(User.username == username).one_or_none()
    if not u:
        return []
    m = db.query(OrgMember).filter(OrgMember.org_id == org.id, OrgMember.user_id == u.id).one_or_none()
    return (m.roles if m else [])

def require_org_roles(*required: str) -> Callable:
    def dep(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if "ADMIN" in user.roles:
            return user
        org = getattr(request.state, "org", None)
        if org is None:
            raise HTTPException(400, "Org context missing")
        org_roles = get_org_roles(db, user.username, org)
        if not set(required).intersection(set(org_roles)):
            raise HTTPException(403, f"Requires org role(s): {required}")
        return user
    return dep
