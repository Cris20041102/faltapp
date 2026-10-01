from tests.conftest import new_course, new_semester, register


def me(client, h):
    return client.get("/api/me", headers=h).json()


def friends(client, a="ana", b="beto"):
    ha, hb = register(client, a), register(client, b)
    ida, idb = me(client, ha)["id"], me(client, hb)["id"]
    assert client.post("/api/friends", headers=ha, json={"username": b}).status_code == 200
    assert client.post(f"/api/friends/{ida}/accept", headers=hb).status_code == 200
    return ha, hb, ida, idb


def names(lst):
    return [u["username"] for u in lst]


def test_flujo_amistad(client):
    ha, hb = register(client, "ana"), register(client, "beto")
    ida = me(client, ha)["id"]
    client.post("/api/friends", headers=ha, json={"username": "Beto"})
    assert names(client.get("/api/friends", headers=ha).json()["outgoing"]) == ["beto"]
    assert names(client.get("/api/friends", headers=hb).json()["incoming"]) == ["ana"]
    client.post(f"/api/friends/{ida}/accept", headers=hb)
    assert names(client.get("/api/friends", headers=ha).json()["friends"]) == ["beto"]
    assert names(client.get("/api/friends", headers=hb).json()["friends"]) == ["ana"]
    assert client.delete(f"/api/friends/{ida}", headers=hb).status_code == 204
    assert client.get("/api/friends", headers=ha).json()["friends"] == []


def test_amistad_a_si_mismo(client):
    h = register(client, "ana")
    assert client.post("/api/friends", headers=h, json={"username": "ana"}).status_code == 400


def test_amistad_reciproca_auto(client):
    ha, hb = register(client, "ana"), register(client, "beto")
    client.post("/api/friends", headers=ha, json={"username": "beto"})
    assert client.post("/api/friends", headers=hb, json={"username": "ana"}).status_code == 200
    assert names(client.get("/api/friends", headers=ha).json()["friends"]) == ["beto"]


def test_usuario_inexistente(client):
    h = register(client, "ana")
    r = client.post("/api/friends", headers=h, json={"username": "nadie"})
    assert r.status_code == 404 and r.json()["detail"] == "Ese usuario no existe"


def test_solicitud_duplicada(client):
    ha, _ = register(client, "ana"), register(client, "beto")
    client.post("/api/friends", headers=ha, json={"username": "beto"})
    assert client.post("/api/friends", headers=ha, json={"username": "beto"}).status_code == 409


def test_aceptar_sin_solicitud(client):
    ha, hb = register(client, "ana"), register(client, "beto")
    r = client.post(f"/api/friends/{me(client, ha)['id']}/accept", headers=hb)
    assert r.status_code == 404 and r.json()["detail"] == "No encontrado"


def test_calendario_amigo(client):
    ha, hb = register(client, "ana"), register(client, "beto")
    ida = me(client, ha)["id"]
    new_course(client, ha, new_semester(client, ha)["id"])
    assert client.get(f"/api/friends/{ida}/calendar", headers=hb).status_code == 404
    client.post("/api/friends", headers=hb, json={"username": "ana"})
    assert client.get(f"/api/friends/{ida}/calendar", headers=hb).status_code == 404  # pendiente
    client.post(f"/api/friends/{me(client, hb)['id']}/accept", headers=ha)
    cal = client.get(f"/api/friends/{ida}/calendar", headers=hb, params={"today": "2026-09-29"}).json()
    assert cal["2026-10-07"] == "verde" and cal["2026-10-08"] == "gris" and "courses" not in cal


def test_calendario_amigo_sin_semestre(client):
    ha, hb, ida, _ = friends(client)
    assert client.get(f"/api/friends/{ida}/calendar", headers=hb).json() == {}


def test_propuesta(client):
    ha, hb, ida, idb = friends(client)
    for h in (ha, hb):
        new_course(client, h, new_semester(client, h)["id"])
    r = client.post("/api/proposals", headers=ha, json={"date": "2026-10-07", "note": "playa", "user_ids": [idb]})
    assert r.status_code == 200, r.text
    assert r.json()["warnings"] == []
    sa = client.get("/api/semesters", headers=ha).json()[0]["id"]
    assert client.get(f"/api/semesters/{sa}/summary", headers=ha).json()["absences"][0]["date"] == "2026-10-07"
    inbox = client.get("/api/proposals", headers=hb, params={"today": "2026-09-29"}).json()
    assert len(inbox) == 1 and inbox[0]["note"] == "playa" and inbox[0]["creator"]["username"] == "ana"
    st = {m["username"]: (m["status"], m["color"]) for m in inbox[0]["members"]}
    assert st == {"ana": ("accepted", "falta"), "beto": ("pending", "verde")}
    assert client.post(f"/api/proposals/{inbox[0]['id']}/respond", headers=hb, json={"accept": True}).status_code == 200
    sb = client.get("/api/semesters", headers=hb).json()[0]["id"]
    assert client.get(f"/api/semesters/{sb}/summary", headers=hb).json()["absences"][0]["date"] == "2026-10-07"


def test_rechazar_propuesta(client):
    ha, hb, ida, idb = friends(client)
    pid = client.post("/api/proposals", headers=ha, json={"date": "2026-10-07", "user_ids": [idb]}).json()["id"]
    client.post(f"/api/proposals/{pid}/respond", headers=hb, json={"accept": False})
    st = {m["username"]: m["status"] for m in client.get("/api/proposals", headers=ha).json()[0]["members"]}
    assert st == {"ana": "accepted", "beto": "rejected"}


def test_propuesta_a_no_amigo(client):
    ha, hb = register(client, "ana"), register(client, "beto")
    r = client.post("/api/proposals", headers=ha, json={"date": "2026-10-07", "user_ids": [me(client, hb)["id"]]})
    assert r.status_code == 404 and r.json()["detail"] == "Solo puedes invitar a tus amigos"


def test_responder_propuesta_ajena(client):
    ha, hb, ida, idb = friends(client)
    pid = client.post("/api/proposals", headers=ha, json={"date": "2026-10-07", "user_ids": [idb]}).json()["id"]
    hc = register(client, "carla")
    assert client.post(f"/api/proposals/{pid}/respond", headers=hc, json={"accept": True}).status_code == 404


def test_aceptar_sin_clases(client):
    ha, hb, ida, idb = friends(client)
    new_course(client, ha, new_semester(client, ha)["id"])
    pid = client.post("/api/proposals", headers=ha, json={"date": "2026-10-07", "user_ids": [idb]}).json()["id"]
    assert client.post(f"/api/proposals/{pid}/respond", headers=hb, json={"accept": True}).status_code == 200
    m = {m["username"]: m for m in client.get("/api/proposals", headers=hb).json()[0]["members"]}
    assert m["beto"]["status"] == "accepted" and m["beto"]["color"] == "gris"


def test_sugerencias_amigos_en_comun(client):
    ha, hb, ida, idb = friends(client)                 # ana - beto
    hc = register(client, "carla")
    client.post("/api/friends", headers=hc, json={"username": "beto"})
    client.post(f"/api/friends/{me(client, hc)['id']}/accept", headers=hb)  # beto - carla
    register(client, "dani")                            # sin amigos
    sug = client.get("/api/friends/suggestions", headers=ha).json()
    assert [(u["username"], u["mutual"]) for u in sug] == [("carla", 1), ("dani", 0)]


def test_sugerencias_excluye_pendientes(client):
    ha, hc = register(client, "ana"), register(client, "carla")
    hd = register(client, "dani")
    client.post("/api/friends", headers=ha, json={"username": "carla"})
    assert [u["username"] for u in client.get("/api/friends/suggestions", headers=ha).json()] == ["dani"]
    assert [u["username"] for u in client.get("/api/friends/suggestions", headers=hc).json()] == ["dani"]
    assert {u["username"] for u in client.get("/api/friends/suggestions", headers=hd).json()} == {"ana", "carla"}
