import base64

from cryptography.hazmat.primitives.asymmetric import ec

from app import push

b64 = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def test_cifrado_igual_al_ejemplo_del_rfc8291():
    # RFC 8291, Apéndice A: con las mismas claves y sal, el mensaje cifrado debe salir idéntico byte a byte
    as_private = ec.derive_private_key(int.from_bytes(b64("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"), ec.SECP256R1())
    body = push.encrypt(b"When I grow up, I want to be a watermelon",
                        "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
                        "BTBZMqHH6r4Tts7J_aSIgg", as_private=as_private, salt=b64("DGv6ra1nlYgDCS1FRnbzlw"))
    assert body == b64("DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")


# ---------- avisos (se intercepta el envío: no sale nada a internet) ----------
import pytest  # noqa: E402

from tests.conftest import new_course, new_semester, register  # noqa: E402
from tests.test_social import friends, me  # noqa: E402

EP = "https://fcm.googleapis.com/fcm/send/{}"
KEYS = {"p256dh": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4", "auth": "BTBZMqHH6r4Tts7J_aSIgg"}


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr("app.push.dispatch", lambda subs, payload, key: out.append((sorted(s["endpoint"] for s in subs), payload)))
    return out


def subscribe(client, h, device):
    r = client.post("/api/push/subscribe", headers=h, json={"endpoint": EP.format(device), "keys": KEYS})
    assert r.status_code == 204, r.text


def test_suscribirse_y_probar(client, sent):
    h = register(client)
    key = client.get("/api/push/key", headers=h).json()["key"]
    assert len(b64(key)) == 65 and client.get("/api/push/key", headers=h).json()["key"] == key  # se genera una vez
    bad = {"endpoint": "https://intranet.local/robar", "keys": KEYS}  # solo servicios push reales
    assert client.post("/api/push/subscribe", headers=h, json=bad).status_code == 422
    subscribe(client, h, "cel")
    subscribe(client, h, "cel")  # repetir no duplica
    client.post("/api/push/test", headers=h)
    assert sent == [([EP.format("cel")], sent[0][1])] and "activadas" in sent[0][1]["title"]
    h2 = register(client, "beto")
    subscribe(client, h2, "cel")  # el mismo celular, ahora con otra cuenta
    client.post("/api/push/test", headers=h)
    assert len(sent) == 1
    assert client.request("DELETE", "/api/push/subscribe", headers=h2, json={"endpoint": EP.format("cel")}).status_code == 204
    client.post("/api/push/test", headers=h2)
    assert len(sent) == 1


def test_avisos_de_amigos_y_propuestas(client, sent):
    ha, hb = register(client, "ana"), register(client, "beto")
    subscribe(client, ha, "ana")
    subscribe(client, hb, "beto")
    client.post("/api/friends", headers=ha, json={"username": "beto"})
    assert sent[-1][0] == [EP.format("beto")] and "ana quiere ser tu amigo" in sent[-1][1]["title"]
    client.post(f"/api/friends/{me(client, ha)['id']}/accept", headers=hb)
    assert sent[-1][0] == [EP.format("ana")] and "beto aceptó" in sent[-1][1]["title"]
    pid = client.post("/api/proposals", headers=ha, json={"date": "2026-10-09", "user_ids": [me(client, hb)["id"]], "note": "playa"}).json()["id"]
    assert sent[-1][0] == [EP.format("beto")] and "ana te propone faltar" in sent[-1][1]["title"] and sent[-1][1]["url"] == "/#propuestas"
    client.post(f"/api/proposals/{pid}/respond", headers=hb, json={"accept": True})
    assert sent[-1][0] == [EP.format("ana")] and "beto se suma" in sent[-1][1]["title"]


def test_alertas_de_faltas(client, sent):
    h = register(client)
    subscribe(client, h, "cel")
    s = new_semester(client, h)
    c = new_course(client, h, s["id"])  # BD Lab los miércoles: 17 clases al 70% → puede faltar 5
    for d in ("2026-08-12", "2026-08-19", "2026-08-26"):
        client.post("/api/absences", headers=h, json={"date": d})
    assert sent == []  # le quedan 2: nada que avisar
    client.post("/api/absences", headers=h, json={"date": "2026-09-02"})
    assert "Te queda 1 falta en BD Lab" in sent[-1][1]["title"]
    client.post("/api/absences/import", headers=h, json={"items": [{"course_id": c["id"], "absent": ["2026-09-09"]}]})
    assert "No puedes faltar más a BD Lab" in sent[-1][1]["title"]
    client.post("/api/absences", headers=h, json={"date": "2026-09-23"})
    assert "Reprobarías BD Lab" in sent[-1][1]["title"]
    assert len(sent) == 3


def test_cron_diario(client, sent, monkeypatch):
    h = register(client)
    subscribe(client, h, "cel")
    s = new_semester(client, h)
    c = new_course(client, h, s["id"])  # miércoles
    client.post(f"/api/semesters/{s['id']}/events", headers=h, json={"kind": "prueba", "date": "2026-10-01", "title": "Certamen 2", "course_id": c["id"]})
    assert client.get("/api/cron/daily", params={"key": "x"}).status_code == 503  # sin CRON_SECRET no corre
    monkeypatch.setenv("CRON_SECRET", "s3cr3t")
    assert client.get("/api/cron/daily", params={"key": "x"}).status_code == 403
    run = lambda d: client.get("/api/cron/daily", params={"key": "s3cr3t", "today": d}).status_code
    titles = lambda: [p["title"] for _, p in sent]
    assert run("2026-09-30") == 200  # miércoles con clases y sin faltas; mañana hay prueba
    assert any("¿Faltaste" in t for t in titles()) and any("Mañana: Certamen 2" in t for t in titles())
    n = len(sent)
    run("2026-09-30")  # si el cron se repite, no repite avisos
    run("2026-10-01")  # jueves sin clases ni pruebas mañana
    assert len(sent) == n
    client.post("/api/absences", headers=h, json={"date": "2026-10-07"})
    run("2026-10-07")  # ya marcó la falta de hoy: no pregunta
    assert not any("¿Faltaste" in p["title"] for _, p in sent[n:])
    run("2026-11-26")  # solo queda el 2/12 y le sobran faltas
    run("2026-11-27")
    assert sum("faltar a todo" in t for t in titles()) == 1


def test_envio_se_descifra_como_en_el_celular(monkeypatch):
    import json
    import os
    import re

    import jwt
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    ua, auth = ec.generate_private_key(ec.SECP256R1()), os.urandom(16)  # claves del "celular"
    server = ec.generate_private_key(ec.SECP256R1())
    pem = server.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    calls = []
    ok = type("R", (), {"status_code": 201, "text": ""})()
    monkeypatch.setattr("app.push.httpx.post", lambda url, content, headers, timeout: calls.append((url, content, headers)) or ok)
    push.deliver([{"endpoint": EP.format("x"), "p256dh": push.b64e(push.raw_public(ua)), "auth": push.b64e(auth)}],
                 {"title": "Mañana: Certamen 2"}, pem)
    url, body, headers = calls[0]
    salt, idlen = body[:16], body[20]
    as_pub, ct = body[21:21 + idlen], body[21 + idlen:]
    shared = ua.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))
    ikm = HKDF(hashes.SHA256(), 32, auth, b"WebPush: info\x00" + push.raw_public(ua) + as_pub).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    plain = AESGCM(cek).decrypt(nonce, ct, None)
    assert json.loads(plain[:-1]) == {"title": "Mañana: Certamen 2"} and plain[-1:] == b"\x02"
    token, k = re.fullmatch(r"vapid t=(\S+), k=(\S+)", headers["Authorization"]).groups()
    claims = jwt.decode(token, server.public_key(), algorithms=["ES256"], audience="https://fcm.googleapis.com")
    assert claims["sub"].startswith("https://") and k == push.b64e(push.raw_public(server))
    assert headers["Content-Encoding"] == "aes128gcm" and headers["TTL"]


def test_cron_diario_con_tope(client, sent, monkeypatch):
    """Con un tope resuelto (un ramo marcado como falta), igual pregunta por las otras clases del día."""
    monkeypatch.setenv("CRON_SECRET", "s3cr3t")
    h = register(client)
    subscribe(client, h, "cel")
    s = new_semester(client, h)
    bd = new_course(client, h, s["id"])
    new_course(client, h, s["id"], name="Inv. de Oper. I", kind="T", min_pct=60)  # mismo bloque del miércoles
    client.post(f"/api/slots/{bd['slots'][0]['id']}/rest", headers=h, json={"since": "2026-09-30"})
    client.get("/api/cron/daily", params={"key": "s3cr3t", "today": "2026-09-30"})
    p = next(p for _, p in sent if "¿Faltaste" in p["title"])
    assert "Inv. de Oper. I" in p["body"] and "BD Lab" not in p["body"]
