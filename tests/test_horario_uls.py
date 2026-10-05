from pathlib import Path

from app.horario_uls import parse
from tests.conftest import new_semester, register

PDF = (Path(__file__).parent / "fixtures" / "horario_uls_demo.pdf").read_bytes()
EXPECTED = {  # jueves 11:30 y viernes 09:45 tienen tope de horario: van los dos ramos
    ("Eva. de Proyec.", "T"): [(0, "08:00", "09:30"), (4, "09:45", "11:15")],
    ("Bas. de Datos I", "L"): [(2, "09:45", "11:15"), (4, "09:45", "11:15")],
    ("Bas. de Datos I", "T"): [(3, "11:30", "13:00")],
    ("Inv. de Oper. I", "T"): [(3, "11:30", "13:00")],
    ("Progr. Avanzada", "L"): [(1, "14:30", "16:00")],
}


def as_dict(courses):
    return {(c["name"], c["kind"]): sorted((s["weekday"], s["start_time"], s["end_time"]) for s in c["slots"]) for c in courses}


def test_parse_pdf_uls():
    assert as_dict(parse(PDF)) == EXPECTED


def test_parse_no_pdf():
    assert parse(b"hola") == []


def test_importar_crea_ramos(client):
    h = register(client)
    sid = new_semester(client, h)["id"]
    r = client.post(f"/api/semesters/{sid}/import-uls", headers={**h, "Content-Type": "application/pdf"}, content=PDF)
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 5, "skipped": 0}
    courses = client.get(f"/api/semesters/{sid}", headers=h).json()["courses"]
    assert as_dict(courses) == EXPECTED
    assert {(c["kind"], c["min_pct"]) for c in courses} == {("T", 60), ("L", 70)}


def test_importar_dos_veces_no_duplica(client):
    h = register(client)
    sid = new_semester(client, h)["id"]
    url = f"/api/semesters/{sid}/import-uls"
    client.post(url, headers=h, content=PDF)
    assert client.post(url, headers=h, content=PDF).json() == {"created": 0, "skipped": 5}


def test_importar_archivo_invalido(client):
    h = register(client)
    sid = new_semester(client, h)["id"]
    r = client.post(f"/api/semesters/{sid}/import-uls", headers=h, content=b"no soy un pdf")
    assert r.status_code == 400 and "ULS" in r.json()["detail"]


def test_importar_semestre_ajeno(client):
    sid = new_semester(client, register(client, "ana"))["id"]
    r = client.post(f"/api/semesters/{sid}/import-uls", headers=register(client, "beto"), content=PDF)
    assert r.status_code == 404
