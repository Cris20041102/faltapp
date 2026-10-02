"""Notificaciones push (Web Push, RFC 8291 + VAPID RFC 8292) solo con `cryptography` + httpx.

Las claves VAPID se generan solas la primera vez y quedan guardadas en la BD: no hay que configurar nada.
"""
import base64
import json
import logging
import os
import threading
import time
from urllib.parse import urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import AppSetting, PushSubscription, SentPush

log = logging.getLogger("faltapp.push")
CONTACT = "https://faltapp.appscristianrojo.cl"  # Apple exige un contacto en el token VAPID
# Solo se envía a los servicios push de los navegadores (evita que alguien nos haga llamar a URLs arbitrarias)
PUSH_HOSTS = ("fcm.googleapis.com", "updates.push.services.mozilla.com", ".push.apple.com", ".notify.windows.com")

b64e = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
b64d = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
raw_public = lambda k: k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def allowed_endpoint(url: str) -> bool:
    u = urlsplit(url)
    host = u.hostname or ""
    return u.scheme == "https" and any(host == h or (h.startswith(".") and host.endswith(h)) for h in PUSH_HOSTS)


def vapid_key(db: Session) -> ec.EllipticCurvePrivateKey:
    row = db.get(AppSetting, "vapid_private_pem")
    if not row:
        pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        db.add(AppSetting(key="vapid_private_pem", value=pem))
        try:
            db.commit()
        except IntegrityError:  # otro proceso la creó al mismo tiempo
            db.rollback()
        row = db.get(AppSetting, "vapid_private_pem")
    return serialization.load_pem_private_key(row.value.encode(), None)


def public_key(db: Session) -> str:
    return b64e(raw_public(vapid_key(db)))


def encrypt(payload: bytes, p256dh: str, auth: str, as_private=None, salt: bytes | None = None) -> bytes:
    """Cifrado aes128gcm de RFC 8291 (un solo registro)."""
    ua_public = b64d(p256dh)
    as_private = as_private or ec.generate_private_key(ec.SECP256R1())
    salt = salt or os.urandom(16)
    as_public = raw_public(as_private)
    shared = as_private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
    hkdf = lambda salt, info, n, ikm: HKDF(hashes.SHA256(), n, salt, info).derive(ikm)
    ikm = hkdf(b64d(auth), b"WebPush: info\x00" + ua_public + as_public, 32, shared)
    cek = hkdf(salt, b"Content-Encoding: aes128gcm\x00", 16, ikm)
    nonce = hkdf(salt, b"Content-Encoding: nonce\x00", 12, ikm)
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + (4096).to_bytes(4, "big") + bytes([len(as_public)]) + as_public + body


def deliver(subs: list[dict], payload: dict, key_pem: str) -> None:
    """Envía a cada dispositivo; borra los que el navegador dio de baja (404/410)."""
    key = serialization.load_pem_private_key(key_pem.encode(), None)
    data = json.dumps(payload).encode()
    dead = []
    for s in subs:
        u = urlsplit(s["endpoint"])
        token = jwt.encode({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": CONTACT}, key, algorithm="ES256")
        try:
            r = httpx.post(s["endpoint"], content=encrypt(data, s["p256dh"], s["auth"]), timeout=10, headers={
                "Authorization": f"vapid t={token}, k={b64e(raw_public(key))}",
                "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": "86400"})
            if r.status_code in (404, 410):
                dead.append(s["endpoint"])
            elif r.status_code >= 400:
                log.warning("push %s → %s %s", u.netloc, r.status_code, r.text[:200])
        except (httpx.HTTPError, ValueError) as e:  # ValueError: claves del dispositivo inválidas
            log.warning("push %s falló: %s", u.netloc, e)
    if dead:
        with SessionLocal() as db:
            db.execute(delete(PushSubscription).where(PushSubscription.endpoint.in_(dead)))
            db.commit()


def dispatch(subs: list[dict], payload: dict, key_pem: str) -> None:
    # en segundo plano: el que hizo la acción no espera a los servicios push
    threading.Thread(target=deliver, args=(subs, payload, key_pem), daemon=True).start()


def claim(db: Session, user_id: int, key: str) -> bool:
    """True la primera vez que se pide esta clave para el usuario (para no repetir avisos)."""
    if db.get(SentPush, (user_id, key)):
        return False
    db.add(SentPush(user_id=user_id, key=key))
    db.commit()
    return True


def notify(db: Session, user_ids, title: str, body: str, url: str = "/#inicio", key: str | None = None) -> None:
    ids = [i for i in user_ids if not key or claim(db, i, key)]
    subs = [{"endpoint": s.endpoint, "p256dh": s.p256dh, "auth": s.auth}
            for s in db.scalars(select(PushSubscription).where(PushSubscription.user_id.in_(ids)))] if ids else []
    if subs:
        key_pem = db.get(AppSetting, "vapid_private_pem") or (vapid_key(db) and db.get(AppSetting, "vapid_private_pem"))
        dispatch(subs, {"title": title, "body": body, "url": url, "tag": key or title}, key_pem.value)
