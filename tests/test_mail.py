"""Correo de recuperación: se verifica con un enlace y sirve para poner otra contraseña. No sale nada a internet."""
import re
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.auth import JWT_SECRET
from tests.conftest import register

token_in = lambda text, kind: re.search(rf"https://faltapp\.appscristianrojo\.cl/#{kind}/([\w.-]+)", text).group(1)


@pytest.fixture
def mails(monkeypatch):
    out = []
    monkeypatch.setenv("RESEND_API_KEY", "re_prueba")
    monkeypatch.setattr("app.api.send_mail", lambda to, subject, text: out.append((to, subject, text)))
    monkeypatch.setattr("app.api.SENT", {})
    return out


def verified(client, mails, username, email):
    h = register(client, username)
    assert client.put("/api/me/email", headers=h, json={"email": email}).status_code == 200
    r = client.post("/api/auth/verify-email", json={"token": token_in(mails[-1][2], "verificar")})
    assert r.status_code == 200, r.text
    return h


def test_correo_se_guarda_solo_al_abrir_el_enlace(client, mails):
    h = register(client, "ana")
    r = client.put("/api/me/email", headers=h, json={"email": " Ana@Correo.CL "})
    assert r.status_code == 200, r.text
    assert client.get("/api/me", headers=h).json()["email"] is None  # aún sin confirmar
    assert mails[0][0] == "ana@correo.cl"
    r = client.post("/api/auth/verify-email", json={"token": token_in(mails[0][2], "verificar")})  # sin sesión: se abre desde el correo
    assert r.json() == {"email": "ana@correo.cl"}
    assert client.get("/api/me", headers=h).json()["email"] == "ana@correo.cl"
    assert "email" not in client.get(f"/api/users/{client.get('/api/me', headers=h).json()['id']}/profile", headers=h).json()  # privado


def test_correo_invalido(client, mails):
    h = register(client)
    for malo in ("no-es-correo", "a@b", "a b@c.cl", "x" * 250 + "@c.cl"):
        assert client.put("/api/me/email", headers=h, json={"email": malo}).status_code == 422, malo
    assert mails == []


def test_sin_servicio_de_correo_la_opcion_no_existe(client):
    h = register(client)
    assert client.get("/api/auth/options").json() == {"mail": False}
    assert client.get("/api/me", headers=h).json()["mail_on"] is False
    assert client.put("/api/me/email", headers=h, json={"email": "a@b.cl"}).status_code == 503
    assert client.post("/api/auth/forgot", json={"login": "cristian"}).status_code == 503


def test_con_servicio_de_correo_la_opcion_aparece(client, mails):
    assert client.get("/api/auth/options").json() == {"mail": True}
    assert client.get("/api/me", headers=register(client)).json()["mail_on"] is True


def test_un_correo_no_puede_quedar_en_dos_cuentas(client, mails):
    verified(client, mails, "ana", "compartido@correo.cl")
    hb = register(client, "beto")
    assert client.put("/api/me/email", headers=hb, json={"email": "compartido@correo.cl"}).status_code == 200  # no delata que existe
    r = client.post("/api/auth/verify-email", json={"token": token_in(mails[-1][2], "verificar")})
    assert r.status_code == 409
    assert client.get("/api/me", headers=hb).json()["email"] is None


def test_el_enlace_del_correo_no_sirve_como_sesion(client, mails):
    """Si alguien escribe mal su correo, el enlace le llega a un extraño: no debe poder entrar a la cuenta con él."""
    h = register(client, "ana")
    client.put("/api/me/email", headers=h, json={"email": "extrano@correo.cl"})
    t = token_in(mails[0][2], "verificar")
    assert client.get("/api/me", headers={"Authorization": f"Bearer {t}"}).status_code == 401
    assert client.post("/api/auth/reset", json={"token": t, "password": "nueva123"}).status_code == 400  # ni para cambiar la contraseña
    sesion = h["Authorization"].removeprefix("Bearer ")
    assert client.post("/api/auth/verify-email", json={"token": sesion}).status_code == 400
    assert client.post("/api/auth/reset", json={"token": sesion, "password": "nueva123"}).status_code == 400


def test_cambiar_la_clave_con_el_enlace_del_correo(client, mails):
    verified(client, mails, "ana", "ana@correo.cl")
    assert client.post("/api/auth/forgot", json={"login": " ANA "}).json() == {"ok": True}
    to, _, text = mails[-1]
    assert to == "ana@correo.cl"
    t = token_in(text, "restablecer")
    r = client.post("/api/auth/reset", json={"token": t, "password": "nueva123"})
    assert r.status_code == 200, r.text
    assert client.get("/api/me", headers={"Authorization": f"Bearer {r.json()['token']}"}).json()["username"] == "ana"
    assert client.post("/api/auth/login", json={"username": "ana", "password": "nueva123"}).status_code == 200
    assert client.post("/api/auth/login", json={"username": "ana", "password": "secreto1"}).status_code == 401
    assert client.post("/api/auth/reset", json={"token": t, "password": "otra1234"}).status_code == 400  # el enlace sirve una sola vez
    assert client.post("/api/auth/login", json={"username": "ana", "password": "otra1234"}).status_code == 401


def test_pedir_el_enlace_con_el_correo_en_vez_del_usuario(client, mails):
    verified(client, mails, "ana", "ana@correo.cl")
    n = len(mails)
    client.post("/api/auth/forgot", json={"login": "Ana@Correo.cl"})
    assert len(mails) == n + 1 and mails[-1][0] == "ana@correo.cl" and "@ana" in mails[-1][2]  # le recuerda su usuario


def test_pedir_el_enlace_no_delata_que_cuentas_existen(client, mails):
    register(client, "sincorreo")
    for login in ("sincorreo", "nadie", "nadie@correo.cl"):
        assert client.post("/api/auth/forgot", json={"login": login}).json() == {"ok": True}
    assert mails == []


def test_enlace_vencido_o_inventado(client, mails):
    h = verified(client, mails, "ana", "ana@correo.cl")
    uid = client.get("/api/me", headers=h).json()["id"]
    viejo = jwt.encode({"sub": str(uid), "use": "reset", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}, JWT_SECRET, algorithm="HS256")
    assert client.post("/api/auth/reset", json={"token": viejo, "password": "nueva123"}).status_code == 400
    assert client.post("/api/auth/reset", json={"token": "cualquier.cosa.aqui", "password": "nueva123"}).status_code == 400
    assert client.post("/api/auth/login", json={"username": "ana", "password": "secreto1"}).status_code == 200  # nada cambió


def test_maximo_tres_correos_por_hora_por_cuenta(client, mails):
    verified(client, mails, "ana", "ana@correo.cl")  # 1 correo (verificación)
    for _ in range(5):
        assert client.post("/api/auth/forgot", json={"login": "ana"}).json() == {"ok": True}  # responde igual: no delata el límite
    assert len(mails) == 3
    h = register(client, "beto")
    assert [client.put("/api/me/email", headers=h, json={"email": "b@correo.cl"}).status_code for _ in range(4)] == [200, 200, 200, 429]


def test_quitar_el_correo(client, mails):
    h = verified(client, mails, "ana", "ana@correo.cl")
    n = len(mails)
    assert client.delete("/api/me/email", headers=h).status_code == 204
    assert client.get("/api/me", headers=h).json()["email"] is None
    client.post("/api/auth/forgot", json={"login": "ana"})
    assert len(mails) == n


def test_si_el_envio_falla_se_avisa(client, mails, monkeypatch):
    def falla(*a):
        raise RuntimeError("Resend caído")
    monkeypatch.setattr("app.api.send_mail", falla)
    assert client.put("/api/me/email", headers=register(client), json={"email": "a@correo.cl"}).status_code == 502


def test_envio_por_resend(monkeypatch):
    from app import api
    calls = []
    ok = type("R", (), {"raise_for_status": lambda self: None})()
    monkeypatch.setenv("RESEND_API_KEY", "re_prueba")
    monkeypatch.setattr("app.api.httpx.post", lambda url, **kw: calls.append((url, kw)) or ok)
    api.send_mail("ana@correo.cl", "Asunto", "Texto con enlace")
    url, kw = calls[0]
    assert url == "https://api.resend.com/emails" and kw["headers"]["Authorization"] == "Bearer re_prueba"
    assert kw["json"]["to"] == ["ana@correo.cl"] and kw["json"]["subject"] == "Asunto" and kw["json"]["text"] == "Texto con enlace"
    assert "appscristianrojo.cl" in kw["json"]["from"]


def test_tope_diario_para_no_agotar_el_plan_gratis(client, mails, monkeypatch):
    from time import monotonic
    monkeypatch.setattr("app.api.SENT", {"*": [monotonic()] * 90})  # hoy ya salieron 90 correos entre todas las cuentas
    assert client.put("/api/me/email", headers=register(client), json={"email": "a@correo.cl"}).status_code == 429
    assert mails == []
