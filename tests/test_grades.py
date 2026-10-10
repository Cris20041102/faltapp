from tests.conftest import new_course, new_semester, register
from tests.test_absences import summary

NOTAS = {"meta": 4.0, "items": [{"name": "Certamen 1", "weight": 30, "grade": 5.5},
                                {"name": "Certamen 2", "weight": 30, "grade": None},
                                {"name": "Examen", "weight": 40, "grade": None}]}


def test_guardar_notas(client):
    h = register(client)
    s = new_semester(client, h)
    c = new_course(client, h, s["id"])
    url = f"/api/courses/{c['id']}/grades"
    r = client.put(url, headers=h, json=NOTAS)
    assert r.status_code == 200, r.text
    guardadas = {"meta": 4.0, "items": [{k: v for k, v in i.items() if v is not None} for i in NOTAS["items"]]}  # sin campos vacíos
    assert r.json()["grades"] == guardadas
    assert summary(client, h, s["id"])["courses"][0]["grades"] == guardadas
    assert client.put(url, headers=h, json={"items": []}).json()["grades"] is None  # vaciar


def test_notas_invalidas(client):
    h = register(client)
    c = new_course(client, h, new_semester(client, h)["id"])
    url = f"/api/courses/{c['id']}/grades"
    malas = [{**NOTAS, "items": [{"name": "C1", "weight": 70, "grade": 4}, {"name": "C2", "weight": 40}]},  # 110%
             {**NOTAS, "items": [{"name": "C1", "weight": 50, "grade": 7.5}]},  # escala 1,0–7,0
             {**NOTAS, "meta": 0.5}]
    for body in malas:
        assert client.put(url, headers=h, json=body).status_code == 422
    r = client.put(url, headers=h, json={"items": [{"name": "C1", "weight": 70}, {"name": "C2", "weight": 40}]})
    assert "más de 100%" in r.json()["detail"][0]["msg"]
    assert client.put(url, headers=register(client, "beto"), json=NOTAS).status_code == 404


def test_notas_desde_phoenix(client):
    """Lo que trae Phoenix: fecha, teoría/lab y evaluaciones con 0% (el profe aún no pone el porcentaje)."""
    h = register(client)
    c = new_course(client, h, new_semester(client, h)["id"])
    body = {"meta": 4.0, "shares": {"T": 60, "L": 40}, "items": [
        {"name": "1° Prueba Parcial", "weight": 33.3, "grade": 6.0, "date": "2026-09-24", "kind": "T"},
        {"name": "2° Prueba Parcial", "weight": 66.7, "date": "2026-10-22", "kind": "T"},
        {"name": "Lab 1", "weight": 100, "kind": "L"},  # con reparto, teoría y lab suman 100% cada uno
        {"name": "Hito 1", "weight": 0, "grade": None, "date": "2026-10-01", "kind": "L"}]}
    url = f"/api/courses/{c['id']}/grades"
    r = client.put(url, headers=h, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["grades"]["shares"] == {"T": 60, "L": 40}
    assert r.json()["grades"]["items"][3] == {"name": "Hito 1", "weight": 0, "date": "2026-10-01", "kind": "L"}
    body["items"].append({"name": "Lab 2", "weight": 10, "kind": "L"})  # el lab ya sumaba 100%
    assert client.put(url, headers=h, json=body).status_code == 422


def test_evaluaciones_van_a_la_agenda(client):
    """Las evaluaciones con fecha (de Phoenix) aparecen solas en la agenda, se mueven con la fecha y se van con el ramo."""
    h = register(client)
    s = new_semester(client, h)
    c = new_course(client, h, s["id"])
    url, ev = f"/api/courses/{c['id']}/grades", f"/api/semesters/{s['id']}/events"
    client.post(ev, headers=h, json={"kind": "entrega", "date": "2026-10-29", "title": "Informe", "course_id": c["id"]})
    items = [{"name": "Certamen 1", "weight": 50, "date": "2026-10-22"}, {"name": "Certamen 2", "weight": 50, "date": "2026-10-29"},
             {"name": "Taller", "weight": 0}]
    assert client.put(url, headers=h, json={"items": items}).status_code == 200
    auto = [e for e in client.get(ev, headers=h).json() if e["auto"]]
    assert [(e["title"], e["date"], e["kind"]) for e in auto] == [("Certamen 1", "2026-10-22", "prueba")]  # ese día ya tenía el Informe
    items[0]["date"] = "2026-10-23"  # Phoenix movió la fecha: misma entrada, no una nueva
    client.put(url, headers=h, json={"items": items})
    moved = [e for e in client.get(ev, headers=h).json() if e["auto"]]
    assert [(e["id"], e["date"]) for e in moved] == [(auto[0]["id"], "2026-10-23")]
    client.put(url, headers=h, json={"items": items[1:]})
    assert [e["title"] for e in client.get(ev, headers=h).json()] == ["Informe"]
    client.put(url, headers=h, json={"items": items})
    client.delete(f"/api/courses/{c['id']}", headers=h)
    assert [e["title"] for e in client.get(ev, headers=h).json()] == ["Informe"]  # lo anotado a mano queda
