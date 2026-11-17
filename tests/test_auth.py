import subprocess
import sys

from sqlalchemy import create_engine, inspect

from tests.conftest import register


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


def test_limite_de_intentos(client):
    register(client, "ana", "secreto1")
    malo = lambda: client.post("/api/auth/login", json={"username": "ana", "password": "otra-cosa"}).status_code
    assert [malo() for _ in range(5)] == [401] * 5
    r = client.post("/api/auth/login", json={"username": "ana", "password": "secreto1"})
    assert r.status_code == 429 and "Espera 15 min" in r.json()["detail"]  # ni con la buena: hay que esperar
    assert client.post("/api/auth/login", json={"username": "beto", "password": "x" * 6}).status_code == 401  # otros usuarios siguen igual


def test_recuperar_con_codigo(client):
    r = client.post("/api/auth/register", json={"username": "ana", "password": "secreto1", "display_name": "Ana"}).json()
    code = r["recovery_code"]
    assert len(code) == 14 and code.count("-") == 2
    assert client.get("/api/me", headers={"Authorization": f"Bearer {r['token']}"}).json()["has_recovery"] is True
    mal = client.post("/api/auth/recover", json={"username": "ana", "code": "AAAA-BBBB-CCCC", "password": "nueva123"})
    assert mal.status_code == 401
    ok = client.post("/api/auth/recover", json={"username": " Ana ", "code": code.lower().replace("-", " "), "password": "nueva123"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["recovery_code"] != code  # el usado ya no sirve
    assert client.post("/api/auth/recover", json={"username": "ana", "code": code, "password": "otra1234"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "ana", "password": "nueva123"}).status_code == 200
    assert client.post("/api/auth/login", json={"username": "ana", "password": "secreto1"}).status_code == 401


def test_codigo_para_cuentas_existentes(client):
    h = register(client)
    nuevo = client.post("/api/me/recovery", headers=h).json()["recovery_code"]
    otro = client.post("/api/me/recovery", headers=h).json()["recovery_code"]
    assert nuevo != otro
    assert client.post("/api/auth/recover", json={"username": "cristian", "code": nuevo, "password": "nueva123"}).status_code == 401
    assert client.post("/api/auth/recover", json={"username": "cristian", "code": otro, "password": "nueva123"}).status_code == 200


def test_codigo_obligatorio_no_pisa_uno_que_ya_existe(client, monkeypatch):
    """Cuenta de antes (sin código): el cuadro obligatorio lo crea. Si ya tiene uno (lo creó en otro aparato), no lo cambia."""
    with monkeypatch.context() as m:
        m.setattr("app.api.new_recovery", lambda u: None)  # como las cuentas creadas antes de que existieran los códigos
        h = register(client)
    assert client.get("/api/me", headers=h).json()["has_recovery"] is False
    code = client.post("/api/me/recovery", headers=h, params={"missing": True}).json()["recovery_code"]
    assert client.post("/api/me/recovery", headers=h, params={"missing": True}).json() == {"recovery_code": None}
    assert client.post("/api/auth/recover", json={"username": "cristian", "code": code, "password": "nueva123"}).status_code == 200


def test_cambiar_la_clave_cierra_las_otras_sesiones(client):
    """Quien recupera la cuenta queda dentro con una sesión nueva; las abiertas con la contraseña anterior dejan de valer."""
    r = client.post("/api/auth/register", json={"username": "ana", "password": "secreto1", "display_name": "Ana"}).json()
    sesion = lambda t: {"Authorization": f"Bearer {t}"}
    otra = client.post("/api/auth/login", json={"username": "ana", "password": "secreto1"}).json()["token"]
    assert client.get("/api/me", headers=sesion(r["token"])).status_code == 200
    assert client.get("/api/me", headers=sesion(otra)).status_code == 200
    ok = client.post("/api/auth/recover", json={"username": "ana", "code": r["recovery_code"], "password": "nueva123"})
    assert ok.status_code == 200, ok.text
    assert client.get("/api/me", headers=sesion(r["token"])).status_code == 401
    assert client.get("/api/me", headers=sesion(otra)).status_code == 401
    assert client.get("/api/me", headers=sesion(ok.json()["token"])).json()["username"] == "ana"  # quien la cambió sigue dentro
    nueva = client.post("/api/auth/login", json={"username": "ana", "password": "nueva123"}).json()["token"]
    assert client.get("/api/me", headers=sesion(nueva)).status_code == 200


def test_sesiones_de_antes_de_la_huella_siguen_valiendo(client):
    """Las sesiones abiertas antes de esta mejora no traen la huella de la contraseña: al publicar no se le cierra la sesión a nadie."""
    from datetime import datetime, timedelta, timezone

    import jwt

    from app.auth import JWT_SECRET
    uid = client.get("/api/me", headers=register(client, "ana")).json()["id"]
    antigua = jwt.encode({"sub": str(uid), "exp": datetime.now(timezone.utc) + timedelta(days=1)}, JWT_SECRET, algorithm="HS256")
    assert client.get("/api/me", headers={"Authorization": f"Bearer {antigua}"}).json()["username"] == "ana"


def test_los_intentos_quedan_en_la_bd_y_se_borran_al_entrar(client):
    from app.models import RateLimit
    register(client)
    for _ in range(4):
        client.post("/api/auth/login", json={"username": "cristian", "password": "mala"})
    with client.db() as db:
        assert len(db.get(RateLimit, "login:cristian").times) == 4
    assert client.post("/api/auth/login", json={"username": "cristian", "password": "secreto1"}).status_code == 200
    with client.db() as db:
        assert db.get(RateLimit, "login:cristian") is None  # entró: se limpia


def test_intentos_viejos_no_cuentan(client):
    from time import time
    from app.models import RateLimit
    register(client)
    with client.db() as db:
        db.add(RateLimit(key="login:cristian", times=[time() - 16 * 60] * 5)); db.commit()
    assert client.post("/api/auth/login", json={"username": "cristian", "password": "secreto1"}).status_code == 200


def test_usuario_larguisimo_no_rompe_el_limite(client):
    """El nombre llega sin validar: la llave se recorta a 80 (en Postgres una más larga no cabe en la columna y daría 500)."""
    from app.models import RateLimit
    largo = "x" * 300
    assert client.post("/api/auth/login", json={"username": largo, "password": "mala"}).status_code == 401
    with client.db() as db:
        assert [len(r.key) for r in db.query(RateLimit).all()] == [80]
