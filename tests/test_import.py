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
    assert r.json() == {"added": 2, "removed": 1, "skipped": [{"course": "BD Lab", "date": "2026-08-27"}], "makeups": []}  # sin clase que Phoenix no traiga
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


def test_importar_recuperacion(client):
    """La clase del miércoles 9/9 se recuperó el sábado 12/9: Phoenix trae el 12 y no el 9 (ni el 19/8, sin registro)."""
    h = register(client)
    s = new_semester(client, h)
    c = new_course(client, h, s["id"])  # miércoles: 17 clases
    body = {"items": [{"course_id": c["id"], "absent": ["2026-09-12"],
                       "present": ["2026-08-12", "2026-08-26", "2026-09-02", "2026-09-16"]}]}
    r = client.post("/api/absences/import", headers=h, json=body).json()
    assert r == {"added": 1, "removed": 0, "skipped": [],
                 "makeups": [{"course": "BD Lab", "original": "2026-09-09", "date": "2026-09-12"}]}  # la más cercana
    sm = summary(client, h, s["id"])
    c0 = sm["courses"][0]
    assert (c0["total"], c0["reales"]) == (17, 1)
    assert [(m["original"], m["date"]) for m in c0["makeups"]] == [("2026-09-09", "2026-09-12")]
    assert (sm["calendar"]["2026-09-12"], sm["calendar"]["2026-09-09"]) == ("falta", "gris")
    again = client.post("/api/absences/import", headers=h, json=body).json()
    assert (again["added"], again["makeups"]) == (0, [])  # importar de nuevo no duplica
    assert client.request("DELETE", "/api/absences", headers=h, json={"date": "2026-09-12"}).status_code == 204
    assert client.post("/api/absences", headers=h, json={"date": "2026-09-09"}).status_code == 400  # ya no hay clase
    assert summary(client, h, s["id"])["courses"][0]["reales"] == 0
