from datetime import datetime, timedelta, timezone

from tests.conftest import new_course, new_semester, register
from tests.test_social import friends, me

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
GIF = b"GIF89a" + b"\x00" * 64


def later(monkeypatch, days):
    monkeypatch.setattr("app.api.now", lambda: datetime.now(timezone.utc) + timedelta(days=days))


def test_editar_perfil(client):
    h = register(client)
    body = {"bio": "Ingeniero en proceso", "career": "Ing. en Computación", "year": 3,
            "status": "En la biblioteca", "banner_color": "#16a34a"}
    r = client.patch("/api/me", headers=h, json=body)
    assert r.status_code == 200, r.text
    got = client.get("/api/me", headers=h).json()
    assert {k: got[k] for k in body} == body
    assert got["avatar_url"] is None and got["username_next_change"] is None


def test_validaciones_perfil(client):
    h = register(client)
    assert client.patch("/api/me", headers=h, json={"bio": "x" * 161}).status_code == 422
    assert client.patch("/api/me", headers=h, json={"banner_color": "rojo"}).status_code == 422
    assert client.patch("/api/me", headers=h, json={"year": 9}).status_code == 422
    assert client.patch("/api/me", headers=h, json={"username": "a b"}).status_code == 422


def test_cambiar_usuario_cada_30_dias(client, monkeypatch):
    h = register(client, "cristian")
    assert client.patch("/api/me", headers=h, json={"username": "Cris.Rojo"}).json()["username"] == "cris.rojo"
    r = client.patch("/api/me", headers=h, json={"username": "otro"})
    assert r.status_code == 400 and "Podrás cambiar tu @" in r.json()["detail"]
    assert client.get("/api/me", headers=h).json()["username_next_change"]
    later(monkeypatch, 29)
    assert client.patch("/api/me", headers=h, json={"username": "otro"}).status_code == 400
    later(monkeypatch, 31)
    assert client.patch("/api/me", headers=h, json={"username": "otro"}).json()["username"] == "otro"


def test_cambiar_nombre_cada_14_dias(client, monkeypatch):
    h = register(client)
    assert client.patch("/api/me", headers=h, json={"display_name": "Cris"}).status_code == 200
    assert client.patch("/api/me", headers=h, json={"display_name": "Cristian R."}).status_code == 400
    later(monkeypatch, 15)
    assert client.patch("/api/me", headers=h, json={"display_name": "Cristian R."}).status_code == 200


def test_mismo_valor_no_gasta_el_cambio(client):
    h = register(client, "cristian")
    client.patch("/api/me", headers=h, json={"username": "cristian", "bio": "hola"})
    assert client.patch("/api/me", headers=h, json={"username": "cris"}).status_code == 200


def test_usuario_ocupado(client):
    h = register(client, "ana")
    register(client, "beto")
    assert client.patch("/api/me", headers=h, json={"username": "beto"}).status_code == 409


def test_foto_de_perfil(client):
    h = register(client)
    r = client.put("/api/me/avatar", headers=h, content=GIF)
    assert r.status_code == 200, r.text
    url = r.json()["avatar_url"]
    img = client.get(url)  # público: las etiquetas <img> no mandan token
    assert img.content == GIF and img.headers["content-type"] == "image/gif"
    assert img.headers["x-content-type-options"] == "nosniff"
    url2 = client.put("/api/me/avatar", headers=h, content=PNG).json()["avatar_url"]
    assert url2 != url and client.get(url2).headers["content-type"] == "image/png"
    assert client.delete("/api/me/avatar", headers=h).status_code == 204
    assert client.get("/api/me", headers=h).json()["avatar_url"] is None


def test_foto_invalida(client):
    h = register(client)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    assert client.put("/api/me/avatar", headers=h, content=svg).status_code == 400
    assert client.put("/api/me/avatar", headers=h, content=PNG + b"\x00" * 2_000_000).status_code == 413


def test_ver_perfil_de_otro(client):
    ha, hb, ida, idb = friends(client)
    hc = register(client, "carla")
    client.post("/api/friends", headers=hc, json={"username": "beto"})
    client.post(f"/api/friends/{me(client, hc)['id']}/accept", headers=hb)
    client.patch("/api/me", headers=hb, json={"bio": "hola", "status": "Hoy no voy"})
    p = client.get(f"/api/users/{idb}/profile", headers=hc).json()
    assert (p["username"], p["bio"], p["status"], p["friends"], p["is_friend"]) == ("beto", "hola", "Hoy no voy", 2, True)
    p = client.get(f"/api/users/{ida}/profile", headers=hc).json()
    assert (p["mutual"], p["is_friend"]) == (1, False)
    assert "password_hash" not in p
    assert client.get("/api/users/999/profile", headers=ha).status_code == 404


def test_insignias(client):
    ha, hb, ida, idb = friends(client)
    s = new_semester(client, ha)
    new_course(client, ha, s["id"])
    for d in ("2026-10-14", "2026-10-21", "2026-10-28"):
        client.post(f"/api/semesters/{s['id']}/events", headers=ha, json={"kind": "prueba", "date": d, "title": "Control"})
    pid = client.post("/api/proposals", headers=ha, json={"date": "2026-10-07", "user_ids": [idb]}).json()["id"]
    client.post(f"/api/proposals/{pid}/respond", headers=hb, json={"accept": True})
    ids = lambda t: {b["id"] for b in client.get(f"/api/users/{ida}/profile", headers=hb, params={"today": t}).json()["badges"]}
    assert ids("2026-09-29") == {"fundador", "perfecta", "verde", "planificador", "organizador"}
    client.post("/api/absences", headers=ha, json={"date": "2026-09-23"})
    assert "perfecta" not in ids("2026-09-29")


def test_estaticos_se_revalidan(client):
    assert client.get("/app.css").headers["cache-control"] == "no-cache"
    h = register(client)
    url = client.put("/api/me/avatar", headers=h, content=PNG).json()["avatar_url"]
    assert "immutable" in client.get(url).headers["cache-control"]
