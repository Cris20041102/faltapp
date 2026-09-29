from tests.conftest import new_course, new_semester, register
from tests.test_social import friends


def setup(client, h=None):
    h = h or register(client)
    s = new_semester(client, h)
    c = new_course(client, h, s["id"])  # miércoles
    return h, s, c


def add_event(client, h, sid, **kw):
    body = {"kind": "prueba", "date": "2026-10-07", "title": "Certamen 2"} | kw
    return client.post(f"/api/semesters/{sid}/events", headers=h, json=body)


def test_crear_y_listar_evento(client):
    h, s, c = setup(client)
    r = add_event(client, h, s["id"], course_id=c["id"], time="10:00")
    assert r.status_code == 200, r.text
    ev = client.get(f"/api/semesters/{s['id']}/events", headers=h).json()
    assert [(e["title"], e["course_id"], e["time"]) for e in ev] == [("Certamen 2", c["id"], "10:00")]
    summ = client.get(f"/api/semesters/{s['id']}/summary", headers=h).json()
    assert summ["events"][0]["title"] == "Certamen 2"
    assert client.delete(f"/api/events/{r.json()['id']}", headers=h).status_code == 204
    assert client.get(f"/api/semesters/{s['id']}/events", headers=h).json() == []


def test_warning_prueba(client):
    h, s, _ = setup(client)
    add_event(client, h, s["id"])
    add_event(client, h, s["id"], kind="reunion", title="Grupo")
    r = client.post("/api/absences", headers=h, json={"date": "2026-10-07"})
    assert r.json()["warnings"] == ["Tienes prueba ese día: Certamen 2"]


def test_warning_propuesta_miembro_rojo(client):
    ha, hb, ida, idb = friends(client)
    _, sa, _ = setup(client, ha)
    add_event(client, ha, sa["id"])
    _, sb, cb = setup(client, hb)
    client.patch(f"/api/courses/{cb['id']}", headers=hb, json={"min_pct": 100})  # beto no puede faltar
    r = client.post("/api/proposals", headers=ha, json={"date": "2026-10-07", "user_ids": [idb]},
                    params={"today": "2026-09-29"})
    assert r.json()["warnings"] == ["Tienes prueba ese día: Certamen 2", "beto está en rojo ese día"]


def test_evento_ramo_ajeno(client):
    _, _, c = setup(client)
    hb, sb, _ = setup(client, register(client, "beto"))
    r = add_event(client, hb, sb["id"], course_id=c["id"])
    assert r.status_code == 404 and r.json()["detail"] == "No encontrado"


def test_evento_semestre_ajeno(client):
    _, s, _ = setup(client)
    hb = register(client, "beto")
    assert add_event(client, hb, s["id"]).json()["detail"] == "No encontrado"
    assert client.get(f"/api/semesters/{s['id']}/events", headers=hb).json()["detail"] == "No encontrado"


def test_kind_invalido(client):
    h, s, _ = setup(client)
    assert add_event(client, h, s["id"], kind="fiesta").status_code == 422
