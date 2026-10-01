from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import router

app = FastAPI(title="Faltapp")
app.include_router(router)


@app.middleware("http")
async def revalidate(request, call_next):
    """Sin esto el navegador guarda app.css/app.js a su criterio y tras un deploy mezcla versiones."""
    r = await call_next(request)
    r.headers.setdefault("Cache-Control", "no-cache")  # revalida con ETag (304 barato); las fotos traen el suyo
    return r


app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "static", html=True), name="static")
