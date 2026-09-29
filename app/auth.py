import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db import DATABASE_URL, get_db
from app.models import User

JWT_SECRET = os.environ.get("JWT_SECRET") or (
    "dev-secret-solo-para-desarrollo-local" if DATABASE_URL.startswith("sqlite") else None)
if not JWT_SECRET:  # sin esto cualquiera podría firmar sesiones
    raise RuntimeError("Falta la variable de entorno JWT_SECRET")
ITER = 200_000


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, ITER)
    return f"pbkdf2${ITER}${salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, it, salt, h = stored.split("$")
        got = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(got.hex(), h)
    except ValueError:
        return False


def make_token(user_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=30)
    return jwt.encode({"sub": str(user_id), "exp": exp}, JWT_SECRET, algorithm="HS256")


def current_user(authorization: str = Header(""), db: Session = Depends(get_db)) -> User:
    try:
        uid = int(jwt.decode(authorization.removeprefix("Bearer "), JWT_SECRET, algorithms=["HS256"])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "Sesión inválida")
    user = db.get(User, uid)
    if not user:
        raise HTTPException(401, "Sesión inválida")
    return user
