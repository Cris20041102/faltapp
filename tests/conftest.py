import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine)

    def override():
        with Session() as db:
            yield db

    app.dependency_overrides[get_db] = override
    monkeypatch.setattr("app.api.fetch_holidays", lambda country, years: [], raising=False)
    yield TestClient(app)
    app.dependency_overrides.clear()


def register(client, username="cristian", password="secreto1"):
    r = client.post("/api/auth/register", json={"username": username, "password": password, "display_name": username})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


SEM = {"name": "2026-2", "start_date": "2026-08-10", "end_date": "2026-12-04", "country_code": "CL"}


def new_semester(client, h, **kw):
    r = client.post("/api/semesters", headers=h, json={**SEM, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def new_course(client, h, sem_id, name="BD Lab", kind="L", min_pct=70, slots=((2, "09:45", "11:15"),)):
    r = client.post(f"/api/semesters/{sem_id}/courses", headers=h, json={
        "name": name, "kind": kind, "min_pct": min_pct,
        "slots": [{"weekday": w, "start_time": a, "end_time": b} for w, a, b in slots]})
    assert r.status_code == 200, r.text
    return r.json()
