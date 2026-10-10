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
    assert r.json()["grades"] == NOTAS
    assert summary(client, h, s["id"])["courses"][0]["grades"] == NOTAS  # Inicio las trae
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
