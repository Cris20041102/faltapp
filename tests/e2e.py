"""E2E con Playwright. Uso: python tests/e2e.py  (no lo corre pytest)."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 8765
URL = f"http://127.0.0.1:{PORT}"


def main():
    db = Path(tempfile.mkdtemp()) / "e2e.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}", "FALTAPP_NO_HOLIDAYS": "1"}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True, capture_output=True)
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                httpx.get(URL)
                break
            except httpx.HTTPError:
                time.sleep(0.1)
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            page = b.new_page(viewport={"width": 390, "height": 844})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(URL)

            page.get_by_role("button", name="Crear cuenta").first.click()
            page.get_by_label("Usuario").fill("cristian")
            page.get_by_label("Nombre").fill("Cristian")
            page.get_by_label("Contraseña").fill("secreto1")
            page.get_by_role("button", name="Crear cuenta").last.click()

            page.get_by_label("Calendario").select_option(label="Universidad de La Serena · 2º semestre 2026")
            expect(page.get_by_label("Inicio")).to_have_value("2026-08-10")
            expect(page.get_by_label("Término")).to_have_value("2026-12-04")
            page.get_by_role("button", name="Crear semestre").click()
            page.wait_for_url("**/#horario")
            page.goto(URL + "/#semestre")
            expect(page.get_by_text("Receso Fiestas Patrias")).to_have_count(4)  # 14 al 17/09

            page.goto(URL + "/#horario")
            page.get_by_role("button", name="Agregar clase el Miércoles").click()
            page.get_by_label("Nombre del ramo").fill("BD Lab")
            page.get_by_label("Tipo").select_option("L")
            expect(page.get_by_label("% mínimo")).to_have_value("70")
            page.get_by_label("Desde").fill("09:45")
            page.get_by_label("Hasta").fill("11:15")
            page.get_by_role("button", name="Guardar").click()
            expect(page.get_by_text("BD Lab").first).to_be_visible()

            page.goto(URL + "/#inicio")
            card = page.locator("[data-course]").filter(has_text="BD Lab")
            expect(card.locator("[data-quedan]")).to_have_text("4")
            day = page.locator('[data-date="2026-10-07"]')
            for _ in range(12):  # navegar hasta octubre, venga de donde venga "hoy"
                if day.count():
                    break
                page.locator("[data-month-next]" if page.locator("[data-date]").first.get_attribute("data-date") < "2026-10" else "[data-month-prev]").click()
            day.click()
            page.get_by_role("button", name="Faltar todo el día").click()
            expect(card.locator("[data-quedan]")).to_have_text("3")
            page.screenshot(path=str(ROOT / "e2e.png"), full_page=True)

            # un diálogo abierto no debe quedar encima al cambiar de pantalla (ej: botón atrás)
            day.click()
            page.evaluate("location.hash = '#agenda'")
            expect(page.locator("#dlg")).not_to_have_attribute("open", "")
            assert not errors, errors
            b.close()
        print("E2E PASS")
    finally:
        srv.terminate()


if __name__ == "__main__":
    main()
