# Faltapp

Calcula cuántas clases puedes faltar por ramo y por día, anota tus faltas, coordina con amigos y lleva tu agenda de pruebas.

FastAPI + PostgreSQL + Alembic + JWT · PWA en JS puro + Tailwind.

## Local

```bash
pip install -r requirements.txt
alembic upgrade head          # crea faltapp.db (SQLite) si no hay DATABASE_URL
uvicorn app.main:app --reload # http://localhost:8000
```

## Tests

```bash
pytest               # API y cálculo
python tests/e2e.py  # navegador (Playwright + Chromium)
```

## Estilos

`static/app.css` se genera desde `static/tailwind.css`. Si cambias clases en `index.html` o `app.js`:

```bash
npx tailwindcss@3 -c tailwind.config.js -i static/tailwind.css -o static/app.css --minify
```

## Deploy (gratis)

1. **Base de datos:** crea un proyecto en [Neon](https://neon.tech) y copia la connection string (`postgresql://…?sslmode=require`).
   El Postgres gratis de Render se borra a los 30 días, por eso va afuera.
2. **Render:** sube este repo a GitHub → Render → *New → Blueprint* → elige el repo. Usa `render.yaml`; pega la URL de Neon en `DATABASE_URL`. `JWT_SECRET` se genera solo.
3. **Dominio (Cloudflare):** en Render → *Settings → Custom Domain* agrega `faltapp.appscristianrojo.cl`; en Cloudflare crea un `CNAME faltapp → <tu-servicio>.onrender.com`.

El plan gratis de Render duerme tras ~15 min sin uso: la primera carga tarda unos segundos.

## Variables

| Variable | Qué es |
|---|---|
| `DATABASE_URL` | Postgres (`postgres://` y `postgresql://` se aceptan) |
| `JWT_SECRET` | secreto para firmar sesiones (obligatorio en producción) |
| `FALTAPP_NO_HOLIDAYS` | si existe, no consulta la API de feriados (tests) |
