# Plan: límites de intentos en la base de datos + E2E de la extensión estable

> **Para el agente ejecutor:** ejecuta las tareas EN ORDEN, paso a paso, marcando los checkbox. No inventes pasos: si un comando da un resultado distinto al esperado, DETENTE y reporta qué viste, sin improvisar arreglos en otros archivos.

**Meta:** que el límite de intentos de login/recuperación y el tope de correos sobrevivan los reinicios de Render (hoy viven en memoria y se borran), y que el E2E de la extensión deje de fallar a veces.

**Arquitectura:** una tabla nueva `rate_limits` (llave → lista JSON de marcas de tiempo epoch) reemplaza los diccionarios en memoria `FAILS` y `SENT` de `app/api.py`. Nada cambia para el usuario; mismas respuestas 429 y mismos topes.

**Stack:** FastAPI + SQLAlchemy + Alembic, pruebas con pytest y Playwright. Todo ya está instalado.

**Spec:** este mismo documento (sección Contexto).

## Contexto

- Repo: `/home/claude/faltapp`, rama **proto** (quédate en ella). La rama ya trae implementados y verificados: deshacer faltas, cierre de sesiones al cambiar contraseña (claim `pw` del token), avisos de seguridad por correo y apertura instantánea con copia guardada. **No** los toques.
- Hoy: `python -m pytest -q` → `122 passed`. `python tests/e2e.py` → `E2E PASS`. `python tests/e2e_extension.py` → `E2E EXTENSION PASS` pero intermitente (carrera de tiempo en la insignia ✓).

## Restricciones globales

- NUNCA: `git push`, `git pull`, borrar ramas, tocar `main`, tocar `.git/config`, `pip install`. Publicar lo hace el humano después.
- Commits: `git -c user.name=Claude -c user.email=noreply@anthropic.com commit -m "..."` (un hook lo exige). Mensajes en español, una línea.
- Comentarios del código en español, estilo del archivo (líneas largas están bien). Sin abstracciones nuevas fuera de las que pide este plan.
- Este plan no toca CSS. (Si alguna vez tocas CSS: la regla va en `static/tailwind.css` Y en `static/app.css`, que es el compilado que se sirve.)
- Comando de pruebas unitarias: `python -m pytest -q` desde la raíz del repo. Debe terminar en `N passed` con N ≥ 124 y **cero** failed; si algo falla, arregla tu cambio, no la prueba (salvo las dos ediciones de pruebas que este plan pide).

---

### Task 1: estabilizar `tests/e2e_extension.py`

**Archivos:**
- Modificar: `tests/e2e_extension.py` (el arreglo de `reopen()` ya está commiteado; solo falta lo de la insignia)

**Interfaces:** no produce nada para otras tareas.

- [ ] **Paso 1:** en `tests/e2e_extension.py`, reemplaza la línea

```python
        assert sw.evaluate("chrome.action.getBadgeText({})") == "✓"
```

por (misma indentación, 8 espacios):

```python
        for _ in range(30):  # la insignia se pone justo después del cierre de la pestaña: puede tardar un instante
            if sw.evaluate("chrome.action.getBadgeText({})") == "✓":
                break
            page.wait_for_timeout(100)
        assert sw.evaluate("chrome.action.getBadgeText({})") == "✓"
```

- [ ] **Paso 2:** corre `python tests/e2e_extension.py` DOS veces. Esperado: `E2E EXTENSION PASS` ambas.
- [ ] **Paso 3:** `git add tests/e2e_extension.py` y commit: `E2E de la extensión sin carreras: espera la insignia`

### Task 2: tabla `rate_limits` (modelo + migración 0014)

**Archivos:**
- Modificar: `app/models.py` (al final, junto a `AppSetting`)
- Crear: `alembic/versions/0014_limites.py`

**Interfaces:**
- Produce: `RateLimit` con `key: str` (PK, String(80)) y `times: list` (JSON). La Tarea 3 lo importa como `from app.models import ..., RateLimit`.

- [ ] **Paso 1:** agrega al final de `app/models.py`:

```python
class RateLimit(Base):
    """Marcas de tiempo (epoch) de intentos fallidos y correos recientes, por llave; sobrevive reinicios de Render."""
    __tablename__ = "rate_limits"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    times: Mapped[list] = mapped_column(JSON)
```

(`JSON`, `String`, `Mapped` y `mapped_column` ya están importados en ese archivo.)

- [ ] **Paso 2:** crea `alembic/versions/0014_limites.py` copiando EXACTAMENTE la estructura de `alembic/versions/0013_correo.py` (mismos imports y variables), con: docstring `"""intentos y correos recientes en la BD: el límite sobrevive reinicios"""`, `revision = '0014'`, `down_revision = '0013'`, y

```python
def upgrade() -> None:
    op.create_table('rate_limits',
                    sa.Column('key', sa.String(length=80), nullable=False),
                    sa.Column('times', sa.JSON(), nullable=False),
                    sa.PrimaryKeyConstraint('key'))


def downgrade() -> None:
    op.drop_table('rate_limits')
```

- [ ] **Paso 3:** prueba la migración ida y vuelta:

```bash
cd /home/claude/faltapp && DATABASE_URL=sqlite:////tmp/mig14.db alembic upgrade head && DATABASE_URL=sqlite:////tmp/mig14.db alembic downgrade 0013 && DATABASE_URL=sqlite:////tmp/mig14.db alembic upgrade head && rm /tmp/mig14.db && echo MIGRACION-OK
```

Esperado: termina imprimiendo `MIGRACION-OK`.

- [ ] **Paso 4:** commit de ambos archivos: `Tabla rate_limits: intentos y correos recientes en la BD`

### Task 3: usar la BD en vez de `FAILS` y `SENT`

**Archivos:**
- Modificar: `app/api.py`, `tests/conftest.py`, `tests/test_mail.py`, `tests/test_auth.py`

**Interfaces:**
- Consume: `RateLimit` (Tarea 2).
- Produce (en `app/api.py`, reemplazando el bloque de `FAILS`/`check_attempts` y el de `SENT`/`allow_mail`):
  - `recent(db: Session, key: str, window: int) -> list[float]`
  - `record(db: Session, key: str, window: int) -> None`
  - `clear_limit(db: Session, key: str) -> None`
  - `check_attempts(db: Session, key: str) -> None`
  - `allow_mail(db: Session, key: str) -> bool`
  - `notify(tasks, db, u, to, subject, text)` y `notify_password(tasks, db, u)` (ganan el parámetro `db` en segunda posición)

- [ ] **Paso 1 (pruebas primero):** en `tests/conftest.py` borra la línea del monkeypatch de `FAILS` y expón la sesión: justo antes de `yield TestClient(app)` no hay nada que agregar; cambia esas dos líneas así:

```python
    c = TestClient(app)
    c.db = Session  # para que una prueba pueda mirar o sembrar filas directamente
    yield c
```

En `tests/test_mail.py`: borra la línea `monkeypatch.setattr("app.api.SENT", {})` del fixture `mails`, y en `test_tope_diario_para_no_agotar_el_plan_gratis` reemplaza sus DOS primeras líneas (`from time import monotonic` y el monkeypatch de `SENT`) por:

```python
    from app.models import RateLimit
    with client.db() as db:
        db.add(RateLimit(key="mail:*", times=[time()] * 90)); db.commit()
```

(usa `from time import time` arriba del archivo). En `tests/test_auth.py` agrega al final:

```python
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
```

- [ ] **Paso 2:** corre `python -m pytest -q tests/test_auth.py tests/test_mail.py`. Esperado: FALLAN `test_los_intentos_quedan_en_la_bd_y_se_borran_al_entrar` y `test_tope_diario_para_no_agotar_el_plan_gratis` (la lógica aún no existe); `test_intentos_viejos_no_cuentan` puede pasar ya (queda protegiendo para después); el resto pasa.
- [ ] **Paso 3:** en `app/api.py`:
  - cambia `from time import monotonic` por `from time import time`, importa `RateLimit` desde `app.models` (en el import que ya trae los modelos) y borra los diccionarios `FAILS` y `SENT` con sus comentarios "shortcut".
  - deja `FAIL_WINDOW, FAIL_MAX = 15 * 60, 5` donde está y define los helpers del bloque Interfaces:

```python
def recent(db: Session, key: str, window: int) -> list[float]:
    row = db.get(RateLimit, key)
    return [t for t in (row.times if row else []) if time() - t < window]


def record(db: Session, key: str, window: int) -> None:
    """Anota un intento o envío ahora y poda los vencidos. shortcut: si hay dos a la vez gana el último; con una sola instancia de Render basta."""
    db.merge(RateLimit(key=key, times=recent(db, key, window) + [time()]))
    db.commit()


def clear_limit(db: Session, key: str) -> None:
    if row := db.get(RateLimit, key):
        db.delete(row)
        db.commit()


def check_attempts(db: Session, key: str) -> None:
    t = recent(db, key, FAIL_WINDOW)
    if len(t) >= FAIL_MAX:
        raise HTTPException(429, f"Demasiados intentos. Espera {int(FAIL_WINDOW - (time() - t[0])) // 60 + 1} min y vuelve a probar")


def allow_mail(db: Session, key: str) -> bool:
    """Máximo 3 correos por hora por cuenta y 90 al día entre todas (el plan gratis de Resend da 100 al día)."""
    if len(recent(db, f"mail:{key}", 3600)) >= 3 or len(recent(db, "mail:*", 86400)) >= 90:
        return False
    record(db, f"mail:{key}", 3600)
    record(db, "mail:*", 86400)
    return True
```

  - actualiza TODOS los que los usaban; las llaves se recortan a 80 con `[:80]` solo donde el nombre viene del navegador sin validar (login y recover):
    - `login`: `check_attempts(db, f"login:{body.username}"[:80])`; en el fallo `record(db, f"login:{body.username}"[:80], FAIL_WINDOW)`; en el éxito `clear_limit(db, f"login:{body.username}"[:80])` (reemplaza el `FAILS.pop`).
    - `recover`: igual con `recover:`; su `FAILS.pop(f"login:...")` del éxito pasa a `clear_limit(db, f"login:{body.username}"[:80])`.
    - `reset`: `FAILS.pop(...)` → `clear_limit(db, f"login:{u.username}")`.
    - `put_email`: agrega `db: Session = Depends(get_db)` a la firma y llama `allow_mail(db, f"u{user.id}")`.
    - `forgot`: `allow_mail(db, f"u{u.id}")`.
    - `notify` y `notify_password`: agregan `db` (segundo parámetro) y `notify` llama `allow_mail(db, f"n{u.id}")`; corrige sus 4 llamadas (en `recover`, `reset`, `delete_email`, `verify_email`).
- [ ] **Paso 4:** `python -m pytest -q`. Esperado: `N passed` con N ≥ 124, cero failed.
- [ ] **Paso 5:** `python tests/e2e.py`. Esperado: `E2E PASS`.
- [ ] **Paso 6:** commit: `Los límites de intentos y de correos viven en la BD: sobreviven reinicios de Render`

### Task 4: verificación final

- [ ] **Paso 1:** `python -m pytest -q` → N ≥ 124 passed, 0 failed.
- [ ] **Paso 2:** `python tests/e2e.py` → `E2E PASS`.
- [ ] **Paso 3:** `python tests/e2e_extension.py` dos veces → `E2E EXTENSION PASS` ambas.
- [ ] **Paso 4:** `git status` limpio y `git log --oneline -4` muestra los 3 commits nuevos. Reporta eso tal cual. NO publiques ni subas nada: eso lo hace el humano.

## Puntos de revisión (los cubre el que revise al final)

1. Un username inventado y larguísimo en `/auth/login` → misma respuesta 401/429 de siempre y llave recortada a 80 (lo cubre `[:80]`; sin él, Postgres rechaza la fila y el login da 500).
2. Marcas viejas en la fila no bloquean (test `test_intentos_viejos_no_cuentan`).
3. Entrar con la contraseña correcta borra la fila (test `..._se_borran_al_entrar`).
4. El tope diario de correos lee la fila `mail:*` de la BD (test del tope diario, ya editado).
5. Si el reloj del servidor retrocede (NTP), como mucho se dejan pasar intentos de más un rato; nunca bloquea para siempre — aceptado, sin test.
