from tests.conftest import new_course, new_semester, register


def setup(client):
    h = register(client)
    s = new_semester(client, h)  # sin feriados: 17 miércoles → mínimo 12 al 70% → 5 faltas
    c = new_course(client, h, s["id"])
    return h, s, c


def summary(client, h, sid, today="2026-09-29"):
    r = client.get(f"/api/semesters/{sid}/summary", headers=h, params={"today": today})
    assert r.status_code == 200, r.text
    return r.json()


def test_marcar_dia_baja_contador(client):
    h, s, c = setup(client)
    assert summary(client, h, s["id"])["courses"][0]["quedan"] == 5
    r = client.post("/api/absences", headers=h, json={"date": "2026-10-07"})
    assert r.status_code == 200 and r.json() == {"warnings": []}
    got = summary(client, h, s["id"])
    assert got["courses"][0]["quedan"] == 4
    assert got["absences"] == [{"slot_id": c["slots"][0]["id"], "date": "2026-10-07"}]
    assert got["calendar"]["2026-10-07"] == "falta" and got["weekdays"]["2"] == 4


def test_marcar_dos_veces_es_idempotente(client):
    h, s, _ = setup(client)
    client.post("/api/absences", headers=h, json={"date": "2026-10-07"})
    assert client.post("/api/absences", headers=h, json={"date": "2026-10-07"}).status_code == 200
    assert summary(client, h, s["id"])["courses"][0]["quedan"] == 4


def test_desmarcar(client):
    h, s, _ = setup(client)
    client.post("/api/absences", headers=h, json={"date": "2026-10-07"})
    assert client.request("DELETE", "/api/absences", headers=h, json={"date": "2026-10-07"}).status_code == 204
    assert summary(client, h, s["id"])["courses"][0]["quedan"] == 5


def test_dia_sin_clases(client):
    h, _, _ = setup(client)
    r = client.post("/api/absences", headers=h, json={"date": "2026-10-03"})
    assert r.status_code == 400 and r.json()["detail"] == "No tienes clases ese día"
    assert client.post("/api/absences", headers=h, json={"date": "2027-01-06"}).status_code == 400


def test_slot_no_calza(client):
    h, _, c = setup(client)
    r = client.post("/api/absences", headers=h, json={"date": "2026-10-08", "slot_ids": [c["slots"][0]["id"]]})
    assert r.status_code == 400 and r.json()["detail"] == "Ese bloque no tiene clases ese día"


def test_slot_ajeno(client):
    _, _, c = setup(client)
    hb = register(client, "beto")
    new_semester(client, hb)
    r = client.post("/api/absences", headers=hb, json={"date": "2026-10-07", "slot_ids": [c["slots"][0]["id"]]})
    assert r.status_code == 400


def test_today_param(client):
    h, s, _ = setup(client)
    client.post("/api/absences", headers=h, json={"date": "2026-10-07"})
    c = summary(client, h, s["id"], "2026-10-06")["courses"][0]
    assert (c["reales"], c["planeadas"]) == (0, 1)
    c = summary(client, h, s["id"], "2026-10-07")["courses"][0]
    assert (c["reales"], c["planeadas"]) == (1, 0)


def test_borrar_ramo_con_faltas(client):
    h, s, c = setup(client)
    client.post("/api/absences", headers=h, json={"date": "2026-10-07"})
    client.delete(f"/api/courses/{c['id']}", headers=h)
    got = summary(client, h, s["id"])
    assert got["courses"] == [] and got["absences"] == []


def test_summary_ajeno(client):
    h, s, _ = setup(client)
    assert client.get(f"/api/semesters/{s['id']}/summary", headers=h).status_code == 200
    assert client.get(f"/api/semesters/{s['id']}/summary", headers=register(client, "beto")).status_code == 404


def test_patch_ramo_conserva_faltas(client):
    h, s, c = setup(client)
    client.post("/api/absences", headers=h, json={"date": "2026-10-07"})
    sl = c["slots"][0]
    r = client.patch(f"/api/courses/{c['id']}", headers=h, json={
        "name": "BD Lab 2", "slots": [sl, {"weekday": 3, "start_time": "16:15", "end_time": "17:45"}]})
    assert r.status_code == 200 and len(r.json()["slots"]) == 2
    assert summary(client, h, s["id"])["absences"] == [{"slot_id": sl["id"], "date": "2026-10-07"}]
