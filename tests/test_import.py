from tests.conftest import new_course, new_semester, register
from tests.test_absences import summary


def test_importar_desde_phoenix(client):
    h = register(client)
    s = new_semester(client, h)
    c = new_course(client, h, s["id"])  # miércoles
    client.post("/api/absences", headers=h, json={"date": "2026-08-12"})  # marcada a mano, Phoenix dice que fue
    client.post("/api/absences", headers=h, json={"date": "2026-10-07"})  # Phoenix aún no la registra: se queda
    body = {"items": [{"course_id": c["id"],
                       "absent": ["2026-08-19", "2026-08-26", "2026-08-27"],  # 27 es jueves: no calza con el horario
                       "present": ["2026-08-12", "2026-09-02"]}]}
    r = client.post("/api/absences/import", headers=h, json=body)
    assert r.status_code == 200, r.text
    assert r.json() == {"added": 2, "removed": 1, "skipped": [{"course": "BD Lab", "date": "2026-08-27"}]}
    got = sorted(a["date"] for a in summary(client, h, s["id"])["absences"])
    assert got == ["2026-08-19", "2026-08-26", "2026-10-07"]
    again = client.post("/api/absences/import", headers=h, json=body).json()
    assert (again["added"], again["removed"]) == (0, 0)


def test_importar_ramo_ajeno(client):
    h = register(client, "ana")
    c = new_course(client, h, new_semester(client, h)["id"])
    hb = register(client, "beto")
    r = client.post("/api/absences/import", headers=hb, json={"items": [{"course_id": c["id"], "absent": ["2026-08-19"]}]})
    assert r.status_code == 404
