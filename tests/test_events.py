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


def test_calendario_del_celular(client):
    """Enlace secreto .ics: sin sesión (las apps de calendario no la mandan), RFC 5545 y se puede cambiar."""
    h, s, c = setup(client)
    add_event(client, h, s["id"], course_id=c["id"], time="09:30")
    add_event(client, h, s["id"], kind="entrega", date="2026-10-14", title="Informe; parte 1, final " + "x" * 60)
    path = client.post("/api/me/calendar", headers=h).json()["path"]
    assert client.post("/api/me/calendar", headers=h).json()["path"] == path  # el mismo enlace cada vez
    r = client.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    raw = r.content.decode()
    assert raw.startswith("BEGIN:VCALENDAR\r\n") and raw.endswith("END:VCALENDAR\r\n")
    assert all(len(line.encode()) <= 75 for line in raw.split("\r\n"))
    ics = raw.replace("\r\n ", "")  # deshace el plegado de líneas largas
    assert "SUMMARY:Prueba · BD Lab · Certamen 2" in ics
    assert "DTSTART:20261007T093000" in ics and "DTEND:20261007T103000" in ics
    assert "DTSTART;VALUE=DATE:20261014" in ics and r"SUMMARY:Entrega · Informe\; parte 1\, final" in ics
    nuevo = client.post("/api/me/calendar", headers=h, params={"renew": True}).json()["path"]
    assert nuevo != path and client.get(path).status_code == 404 and client.get(nuevo).status_code == 200
    assert client.get("/api/calendar/inventado.ics").status_code == 404
