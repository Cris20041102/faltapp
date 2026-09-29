# Faltapp — Diseño v1

## Objetivo

PWA multiusuario para estudiantes de cualquier universidad. Con el horario y el % mínimo de asistencia de cada ramo:

- calcula cuántas veces puede faltar el estudiante a cada ramo y cada día de la semana;
- registra faltas reales y planeadas, y recalcula al instante;
- permite coordinar con amigos qué días faltar (propuestas + semáforo);
- lleva una agenda de pruebas, entregas y reuniones.

Criterio de éxito: Cristian carga su horario del 2º semestre 2026 ULS y la app entrega los mismos números que el cálculo manual (ver Pruebas).

## Stack

Es el mismo stack que tesorapp.

| Capa | Elección |
|---|---|
| Backend | FastAPI, SQLAlchemy 2, Alembic, PostgreSQL |
| Auth | JWT (PyJWT). Contraseñas con `hashlib.pbkdf2_hmac` de la stdlib, más salt |
| Frontend | PWA en JS puro + Tailwind (CDN), servida como estáticos por FastAPI (un solo servicio, sin CORS) |
| Feriados | API Nager.Date (`/api/v3/PublicHolidays/{año}/{país}`), gratis y sin clave |
| Deploy | Render (web service gratis) + Postgres externo gratis (Neon), porque el Postgres gratis de Render se borra a los 30 días. Dominio vía Cloudflare (p. ej. `faltapp.appscristianrojo.cl`) |

Los modelos solo usan tipos portables, para que los tests corran en SQLite.

## Modelo de datos

```
users            id, username (único), display_name, password_hash, created_at
friendships      id, requester_id, addressee_id, status [pending|accepted]   único(requester, addressee)
semesters        id, user_id, name, start_date, end_date, country_code, active
no_class_days    id, semester_id, date, reason                                único(semester_id, date)
courses          id, semester_id, name, kind [T|L], min_pct (entero, 1-100)
slots            id, course_id, weekday (0=lun..5=sáb), start_time, end_time
absences         id, slot_id, date                                           único(slot_id, date)
proposals        id, creator_id, date, note, created_at
proposal_members proposal_id, user_id, status [pending|accepted|rejected]
events           id, user_id, semester_id, course_id (nullable), kind [prueba|entrega|reunion|otro], date, time (nullable), title
```

- Una falta con `date <= hoy` es **real** y una con `date > hoy` es **planeada**. No se guarda un flag: si al final fue a clases, borra la falta.
- Cada usuario tiene como máximo 1 semestre `active`, que es el que ven sus amigos y el que usan las propuestas.
- Al crear un semestre se importan los feriados nacionales de cada año del rango como `no_class_days` con reason = nombre del feriado. Los recesos de la universidad se agregan a mano.

## Cálculo (`app/calc.py`, funciones puras sin DB)

Entradas: start, end, set de días sin clase, ramos con sus slots y `min_pct`, set de faltas `(slot_id, date)` y hoy.

- `sesiones(slot)`: fechas en [start, end] con `weekday == slot.weekday` y fuera de los días sin clase.
- `total(ramo) = Σ sesiones de sus slots`. Cada bloque cuenta 1 sesión.
- `minimo = ceil(min_pct · total / 100)`, calculado con enteros: `(min_pct*total + 99)//100`.
- `permitidas = total − minimo`.
- `usadas = reales + planeadas`.
- `quedan = permitidas − usadas`. Si es negativo, el ramo queda reprobado por asistencia y se muestra en rojo.
- **Por día de semana w**: `puede_faltar(w) = min` sobre los ramos con clases en w de `floor(quedan(c) / bloques_de_c_en_w)`. Se acota por las fechas de w desde hoy (incluido) que tienen clases y no tienen falta marcada. Cada día de la semana se calcula por separado.
- **Semáforo(fecha)**:
  - sin clases → `gris`;
  - fecha pasada sin falta → `asistio`;
  - todos los bloques de ese día ya marcados como falta → `falta`;
  - si no, por cada ramo con clases ese día, `r = quedan(c) − bloques de c no marcados ese día`. El color se decide con el mínimo de r: `< 0` → `rojo`, `== 0` → `amarillo`, `> 0` → `verde`.

Chequeo con el caso real: con el calendario ULS 2026-2 (inicio 10/08, término 04/12, receso 14–17/09, feriados 18/09 y 12/10, receso estudiantil 09/10) resultan Lun 15, Mar 16, Mié 16, Jue 16 y Vie 15 sesiones. Eva. de Proyectos (Lun+Vie, 60%) da total 30 y mínimo 18. Sin faltas, `puede_faltar(lunes) = 4`, porque lo limita el lab de Sis. de Información: 15 sesiones al 70% → 4 faltas.

## API (JSON bajo `/api`, `Authorization: Bearer <jwt>`)

| Método y ruta | Qué hace |
|---|---|
| `POST /auth/register` `{username, password, display_name}` | crea el usuario → `{token}` |
| `POST /auth/login` `{username, password}` | → `{token}` |
| `GET /me` | usuario actual |
| `GET/POST /semesters`, `GET/PATCH/DELETE /semesters/{id}` | CRUD. Al hacer POST se importan los feriados y la respuesta incluye `holidays_loaded` |
| `POST /semesters/{id}/no-class-days`, `DELETE /no-class-days/{id}` | recesos y feriados |
| `POST /semesters/{id}/courses` `{name, kind, min_pct, slots:[{weekday,start_time,end_time}]}` | crea un ramo con sus bloques |
| `PATCH/DELETE /courses/{id}` | edita o borra (en PATCH, `slots` reemplaza la lista completa) |
| `POST /absences` `{date, slot_ids?}` | marca faltas; sin `slot_ids` marca todos los bloques de ese día. Responde `warnings` si hay prueba ese día |
| `DELETE /absences` `{date, slot_ids?}` | desmarca |
| `GET /semesters/{id}/summary` | stats por ramo, `puede_faltar` por día de semana, calendario día→color y eventos |
| `GET /friends` | amigos aceptados + solicitudes recibidas y enviadas |
| `POST /friends` `{username}` | envía solicitud |
| `POST /friends/{id}/accept`, `DELETE /friends/{id}` | acepta, rechaza o elimina |
| `GET /friends/{user_id}/calendar` | solo día→color del semestre activo del amigo (no expone ramos) |
| `GET /proposals` | bandeja: propuestas donde participo, con el estado y el color de cada miembro ese día |
| `POST /proposals` `{date, note, user_ids}` | solo a amigos aceptados. El creador queda `accepted` y se le marcan las faltas. Responde `warnings` (pruebas, miembros en rojo) |
| `POST /proposals/{id}/respond` `{accept}` | al aceptar se marcan todos los bloques de ese día en el semestre activo |
| `GET/POST /semesters/{id}/events`, `DELETE /events/{id}` | agenda |

**Autorización:** todo recurso se valida contra el usuario actual. Si no es suyo, responde 404 (no se revela que existe). El calendario de un amigo exige una amistad `accepted`.

## Frontend (PWA)

Archivos en `static/`: `index.html`, `app.js`, `manifest.json`, `sw.js` (cachea solo el shell) e `icon.svg`. El diseño es mobile-first y la navegación usa rutas hash:

| Ruta | Pantalla |
|---|---|
| `#login` | login y registro |
| `#semestre` | nombre, fechas y país; lista de días sin clase con botón para agregar recesos |
| `#horario` | grilla semanal Lun–Sáb con los bloques. Un "+" por día abre un formulario (ramo nuevo o existente, T/L, hora inicio/fin, % mínimo con default 60 T / 70 L) |
| `#inicio` | tarjetas por ramo (quedan X faltas), "puedes faltar N lunes más…" y calendario mensual con semáforo. Tocar un día abre: marcar o desmarcar falta (día completo o por ramo) y ver los eventos |
| `#amigos` | lista, solicitudes, agregar por usuario y ver el calendario de un amigo |
| `#propuestas` | bandeja con badge de pendientes y botón para crear propuesta (fecha, nota, amigos) |
| `#agenda` | eventos por fecha y crear evento |

`fetch` pasa por un wrapper: un 401 manda a `#login` y cualquier otro error se muestra como toast con el `detail`.

## Errores

- 422 validación (Pydantic), 401 token inválido o vencido, 404 recurso ajeno o inexistente, 409 usuario ya existe o solicitud de amistad duplicada.
- Si Nager.Date falla o no conoce el país, el semestre se crea igual con `holidays_loaded: false` y la UI avisa que hay que agregar los feriados a mano.
- Validaciones: `start_date < end_date`, `min_pct` entre 1 y 100, `start_time < end_time`, y la fecha de una falta debe estar dentro del semestre y caer en un día de clases de ese slot.

## Pruebas

- `tests/test_calc.py`: el caso real ULS de arriba (totales, mínimos, `puede_faltar` por día) y los 4 colores del semáforo.
- `tests/test_api.py` (TestClient + SQLite): registro y login, CRUD con aislamiento entre usuarios, faltas → summary, amistad → calendario del amigo, flujo de propuesta, warning por prueba. Los feriados externos se mockean.
- `tests/e2e.py` (Playwright, Chromium preinstalado): registro → semestre → ramo → marcar falta → el contador baja.

## Estructura

```
faltapp/
  app/main.py      app FastAPI, monta /api y static/
  app/db.py        engine y sesión (DATABASE_URL)
  app/models.py
  app/auth.py      hash, JWT, dependencia current_user
  app/calc.py      cálculo puro
  app/api.py       todas las rutas y schemas Pydantic
  alembic/, alembic.ini
  static/          PWA
  tests/
  requirements.txt, render.yaml, README.md (pasos de deploy)
```

Deploy en Render: build `pip install -r requirements.txt`; start `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`; variables de entorno `DATABASE_URL` y `JWT_SECRET`. El plan gratis duerme tras ~15 min sin uso, así que la primera carga tarda.

## Fuera de v1

Notificaciones push, sugerencia automática de qué días faltar, eventos compartidos con amigos, lectura de PDF o IA, recuperar contraseña por correo y editar propuestas ya enviadas.
