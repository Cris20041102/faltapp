from datetime import date

from tests.conftest import SEM, new_course, new_semester, register


def test_crear_semestre_con_feriados(client, monkeypatch):
    monkeypatch.setattr("app.api.fetch_holidays", lambda c, y: [(date(2026, 9, 18), "Independencia")])
    h = register(client)
    s = new_semester(client, h)
    assert s["holidays_loaded"] is True
    got = client.get(f"/api/semesters/{s['id']}", headers=h).json()
    assert [(d["date"], d["reason"]) for d in got["no_class_days"]] == [("2026-09-18", "Independencia")]


def test_feriados_fallan(client, monkeypatch):
    monkeypatch.setattr("app.api.fetch_holidays", lambda c, y: None)
    h = register(client)
    assert new_semester(client, h)["holidays_loaded"] is False


def test_fechas_invertidas(client):
    h = register(client)
    r = client.post("/api/semesters", headers=h, json={**SEM, "start_date": "2026-12-04", "end_date": "2026-08-10"})
    assert r.status_code == 422


def test_crear_ramo_con_slots(client):
    h = register(client)
    s = new_semester(client, h)
    c = new_course(client, h, s["id"])
    assert c["name"] == "BD Lab" and c["slots"][0]["id"] and c["slots"][0]["weekday"] == 2
    assert c["slots"][0]["start_time"] == "09:45"
    got = client.get(f"/api/semesters/{s['id']}", headers=h).json()
    assert got["courses"][0]["slots"][0]["end_time"] == "11:15"


def test_ramo_validaciones(client):
    h = register(client)
    sid = new_semester(client, h)["id"]
    base = {"name": "X", "kind": "T", "min_pct": 60, "slots": [{"weekday": 0, "start_time": "08:00", "end_time": "09:30"}]}
    url = f"/api/semesters/{sid}/courses"
    assert client.post(url, headers=h, json={**base, "min_pct": 0}).status_code == 422
    assert client.post(url, headers=h, json={**base, "kind": "X"}).status_code == 422
    bad = {**base, "slots": [{"weekday": 0, "start_time": "10:00", "end_time": "09:00"}]}
    assert client.post(url, headers=h, json=bad).status_code == 422
    assert client.post(url, headers=h, json={**base, "slots": [{"weekday": 6, "start_time": "08:00", "end_time": "09:00"}]}).status_code == 422


def test_aislamiento(client):
    ha, hb = register(client, "ana"), register(client, "beto")
    s = new_semester(client, ha)
    c = new_course(client, ha, s["id"])
    assert client.get(f"/api/semesters/{s['id']}", headers=hb).status_code == 404
    assert client.patch(f"/api/semesters/{s['id']}", headers=hb, json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/semesters/{s['id']}", headers=hb).status_code == 404
    assert client.post(f"/api/semesters/{s['id']}/courses", headers=hb, json={"name": "X", "kind": "T", "min_pct": 60, "slots": []}).status_code == 404
    assert client.patch(f"/api/courses/{c['id']}", headers=hb, json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/courses/{c['id']}", headers=hb).status_code == 404
    assert client.get("/api/semesters", headers=hb).json() == []


def test_patch_ramo_reemplaza_slots(client):
    h = register(client)
    s = new_semester(client, h)
    c = new_course(client, h, s["id"])
    r = client.patch(f"/api/courses/{c['id']}", headers=h, json={"min_pct": 75, "slots": [{"weekday": 3, "start_time": "16:15", "end_time": "17:45"}]})
    assert r.status_code == 200
    got = client.get(f"/api/semesters/{s['id']}", headers=h).json()["courses"][0]
    assert got["min_pct"] == 75 and [x["weekday"] for x in got["slots"]] == [3]


def test_borrar_ramo_y_semestre(client):
    h = register(client)
    s = new_semester(client, h)
    c = new_course(client, h, s["id"])
    assert client.delete(f"/api/courses/{c['id']}", headers=h).status_code == 204
    assert client.get(f"/api/semesters/{s['id']}", headers=h).json()["courses"] == []
    assert client.delete(f"/api/semesters/{s['id']}", headers=h).status_code == 204
    assert client.get("/api/semesters", headers=h).json() == []


def test_nuevo_semestre_queda_activo(client):
    h = register(client)
    a = new_semester(client, h, name="2026-1")
    b = new_semester(client, h, name="2026-2")
    act = {s["id"]: s["active"] for s in client.get("/api/semesters", headers=h).json()}
    assert act == {a["id"]: False, b["id"]: True}
    client.patch(f"/api/semesters/{a['id']}", headers=h, json={"active": True})
    act = {s["id"]: s["active"] for s in client.get("/api/semesters", headers=h).json()}
    assert act == {a["id"]: True, b["id"]: False}


def test_agregar_y_borrar_receso(client):
    h = register(client)
    sid = new_semester(client, h)["id"]
    r = client.post(f"/api/semesters/{sid}/no-class-days", headers=h, json={"date": "2026-09-14", "reason": "Receso"})
    assert r.status_code == 200
    assert client.post(f"/api/semesters/{sid}/no-class-days", headers=h, json={"date": "2026-09-14", "reason": "x"}).status_code == 409
    assert [d["date"] for d in client.get(f"/api/semesters/{sid}", headers=h).json()["no_class_days"]] == ["2026-09-14"]
    assert client.delete(f"/api/no-class-days/{r.json()['id']}", headers=h).status_code == 204
    assert client.get(f"/api/semesters/{sid}", headers=h).json()["no_class_days"] == []


class FakeResp:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("x", request=None, response=None)

    def json(self):
        return self.data


def test_fetch_holidays_parsea_nager(monkeypatch):
    from app import api
    monkeypatch.delenv("FALTAPP_NO_HOLIDAYS", raising=False)
    monkeypatch.setattr(api.httpx, "get", lambda url, timeout: FakeResp(
        [{"date": "2026-09-18", "localName": "Independencia Nacional", "name": "Independence Day", "countryCode": "CL"}]))
    assert api.fetch_holidays("CL", [2026]) == [(date(2026, 9, 18), "Independencia Nacional")]
    monkeypatch.setattr(api.httpx, "get", lambda url, timeout: FakeResp([], 404))
    assert api.fetch_holidays("XX", [2026]) is None
