import subprocess
import sys

from sqlalchemy import create_engine, inspect


def test_registro_login_me(client):
    r = client.post("/api/auth/register", json={"username": "Cristian", "password": "secreto1", "display_name": "Cris"})
    assert r.status_code == 200 and r.json()["token"]
    r = client.post("/api/auth/login", json={"username": "cristian", "password": "secreto1"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    me = client.get("/api/me", headers=h).json()
    assert me["username"] == "cristian" and me["display_name"] == "Cris"


def test_usuario_duplicado_case_insensitive(client):
    body = {"username": "Ana", "password": "secreto1", "display_name": "Ana"}
    assert client.post("/api/auth/register", json=body).status_code == 200
    assert client.post("/api/auth/register", json={**body, "username": "ana"}).status_code == 409


def test_login_malo(client):
    client.post("/api/auth/register", json={"username": "ana", "password": "secreto1", "display_name": "Ana"})
    assert client.post("/api/auth/login", json={"username": "ana", "password": "otra123"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "nadie", "password": "otra123"}).status_code == 401


def test_sin_token(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer basura"}).status_code == 401


def test_validaciones_registro(client):
    assert client.post("/api/auth/register", json={"username": "a", "password": "secreto1", "display_name": "A"}).status_code == 422
    assert client.post("/api/auth/register", json={"username": "ana", "password": "123", "display_name": "A"}).status_code == 422


def test_migracion_sqlite(tmp_path):
    url = f"sqlite:///{tmp_path}/m.db"
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env={"DATABASE_URL": url, "PATH": ""},
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    tables = set(inspect(create_engine(url)).get_table_names())
    assert {"users", "friendships", "semesters", "no_class_days", "courses", "slots", "absences",
            "proposals", "proposal_members", "events"} <= tables


def test_jwt_secret_obligatorio_fuera_de_sqlite():
    env = {"DATABASE_URL": "postgresql://u:p@localhost/db", "PATH": ""}
    r = subprocess.run([sys.executable, "-c", "import app.auth"], env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "JWT_SECRET" in r.stderr


def test_errores_de_registro_en_espanol(client):
    r = client.post("/api/auth/register", json={"username": "ab", "password": "secreto1", "display_name": "A"})
    assert "usuario" in r.json()["detail"][0]["msg"]
    r = client.post("/api/auth/register", json={"username": "ana", "password": "123", "display_name": "A"})
    assert "contraseña" in r.json()["detail"][0]["msg"]
