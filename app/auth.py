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


def pw_mark(u: User) -> str:
    """Huella de la contraseña actual: lo firmado con ella (sesiones, enlace para cambiarla) deja de servir apenas cambia."""
    return hashlib.sha256(u.password_hash.encode()).hexdigest()[:16]


def make_token(u: User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=30)
    return jwt.encode({"sub": str(u.id), "exp": exp, "pw": pw_mark(u)}, JWT_SECRET, algorithm="HS256")


def make_link(user_id: int, use: str, minutes: int, **extra) -> str:
    """Token para un enlace que va por correo. Lleva "use": sirve solo para eso, nunca como sesión."""
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return jwt.encode({"sub": str(user_id), "use": use, "exp": exp, **extra}, JWT_SECRET, algorithm="HS256")


def read_link(token: str, use: str, db: Session) -> tuple[User, dict]:
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user = db.get(User, int(data["sub"])) if data.get("use") == use else None
    except (jwt.PyJWTError, KeyError, ValueError):
        user = None
    if not user:
        raise HTTPException(400, "El enlace no sirve o ya venció. Pide otro")
    return user, data


def current_user(authorization: str = Header(""), db: Session = Depends(get_db)) -> User:
    try:
        data = jwt.decode(authorization.removeprefix("Bearer "), JWT_SECRET, algorithms=["HS256"])
        if data.get("use"):  # un enlace de correo (podría llegarle a un extraño) no es una sesión
            raise ValueError
        uid = int(data["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "Sesión inválida")
    user = db.get(User, uid)
    # "pw" distinta: la sesión se abrió con otra contraseña (la cambiaron después), así que ya no vale.
    # shortcut: las sesiones de antes de este cambio no traen "pw" y valen hasta vencer; a los 30 días de publicado no queda ninguna
    if not user or ("pw" in data and not hmac.compare_digest(str(data["pw"]), pw_mark(user))):
        raise HTTPException(401, "Sesión inválida")
    return user
