"""Correo de recuperación: se verifica con un enlace y sirve para poner otra contraseña. No sale nada a internet."""
import re
from time import time
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
    assert client.delete("/api/me/email", headers=h).status_code == 204
    assert client.get("/api/me", headers=h).json()["email"] is None
    n = len(mails)  # después de quitarlo: al quitarlo sale un aviso al correo anterior
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
    from app.models import RateLimit
    with client.db() as db:  # hoy ya salieron 90 correos entre todas las cuentas
        db.add(RateLimit(key="mail:*", times=[time()] * 90)); db.commit()
    assert client.put("/api/me/email", headers=register(client), json={"email": "a@correo.cl"}).status_code == 429
    assert mails == []


def test_cambiar_la_clave_por_correo_cierra_las_otras_sesiones_y_avisa(client, mails):
    h = verified(client, mails, "ana", "ana@correo.cl")
    client.post("/api/auth/forgot", json={"login": "ana"})
    n = len(mails)
    r = client.post("/api/auth/reset", json={"token": token_in(mails[-1][2], "restablecer"), "password": "nueva123"})
    assert r.status_code == 200, r.text
    assert client.get("/api/me", headers=h).status_code == 401  # la sesión abierta con la contraseña anterior ya no vale
    assert client.get("/api/me", headers={"Authorization": f"Bearer {r.json()['token']}"}).status_code == 200
    assert len(mails) == n + 1  # el aviso: no trae otro enlace, solo cuenta lo que pasó
    assert mails[-1][0] == "ana@correo.cl" and "@ana" in mails[-1][2] and "#restablecer/" not in mails[-1][2]


def test_recuperar_con_codigo_avisa_al_correo(client, mails):
    r = client.post("/api/auth/register", json={"username": "ana", "password": "secreto1", "display_name": "Ana"}).json()
    client.put("/api/me/email", headers={"Authorization": f"Bearer {r['token']}"}, json={"email": "ana@correo.cl"})
    client.post("/api/auth/verify-email", json={"token": token_in(mails[-1][2], "verificar")})
    n = len(mails)
    assert client.post("/api/auth/recover", json={"username": "ana", "code": r["recovery_code"], "password": "nueva123"}).status_code == 200
    assert len(mails) == n + 1 and mails[-1][0] == "ana@correo.cl" and "@ana" in mails[-1][2]


def test_sin_correo_verificado_no_hay_a_quien_avisar(client, mails):
    r = client.post("/api/auth/register", json={"username": "ana", "password": "secreto1", "display_name": "Ana"}).json()
    assert client.post("/api/auth/recover", json={"username": "ana", "code": r["recovery_code"], "password": "nueva123"}).status_code == 200
    assert mails == []


def test_cambiar_o_quitar_el_correo_avisa_al_correo_anterior(client, mails):
    h = verified(client, mails, "ana", "viejo@correo.cl")
    assert len(mails) == 1  # el primer correo no reemplaza a ninguno: solo salió el enlace de verificación
    client.put("/api/me/email", headers=h, json={"email": "nuevo@correo.cl"})
    n = len(mails)
    client.post("/api/auth/verify-email", json={"token": token_in(mails[-1][2], "verificar")})
    assert len(mails) == n + 1 and mails[-1][0] == "viejo@correo.cl" and "nuevo@correo.cl" not in mails[-1][2]  # sin delatar el nuevo
    assert client.delete("/api/me/email", headers=h).status_code == 204
    assert len(mails) == n + 2 and mails[-1][0] == "nuevo@correo.cl"
