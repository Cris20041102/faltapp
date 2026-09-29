from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import router

app = FastAPI(title="Faltapp")
app.include_router(router)
app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "static", html=True), name="static")
