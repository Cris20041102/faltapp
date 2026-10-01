"""E2E con Playwright. Uso: python tests/e2e.py  (no lo corre pytest)."""
import base64
import urllib.parse
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
            page.get_by_label("Subir PDF de horario ULS").set_input_files(str(ROOT / "tests" / "fixtures" / "horario_uls_demo.pdf"))
            expect(page.get_by_text("Progr. Avanzada").first).to_be_visible()
            expect(page.locator("[data-slot]")).to_have_count(5)  # 4 ramos, Eva. de Proyec. con 2 bloques
            for _ in range(4):  # se borran para seguir con un horario conocido
                page.locator("[data-slot]").first.click()
                page.get_by_role("button", name="Eliminar el ramo completo").click()
                page.get_by_role("button", name="¿Seguro?").click()
            expect(page.locator("[data-slot]")).to_have_count(0)
            page.get_by_role("button", name="Agregar clase el Miércoles").click()
            page.get_by_label("Nombre del ramo").fill("Bases de Datos")
            page.get_by_label("Tipo").select_option("L")
            expect(page.get_by_label("% mínimo")).to_have_value("70")
            page.get_by_label("Desde").fill("09:45")
            page.get_by_label("Hasta").fill("11:15")
            page.get_by_role("button", name="Guardar").click()
            expect(page.get_by_text("Bases de Datos").first).to_be_visible()

            page.goto(URL + "/#inicio")
            card = page.locator("[data-course]").filter(has_text="Bases de Datos")
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

            # perfil: estado, descripción, color, foto
            page.locator("#hdr a").click()
            page.get_by_label("Estado").fill("Probando Faltapp")
            page.get_by_label("Descripción").fill("Hola, soy de prueba")
            page.get_by_label("Color #16a34a").check()
            page.get_by_role("button", name="Guardar perfil").click()
            expect(page.locator("[data-card]").get_by_text("Probando Faltapp")).to_be_visible()
            png = Path(tempfile.mkdtemp()) / "yo.png"
            png.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="))
            page.get_by_label("Cambiar foto").set_input_files(str(png))
            expect(page.locator("#hdr img")).to_be_visible()

            # importar desde Phoenix con el marcador; en los días que Phoenix registró, manda Phoenix
            page.goto(URL + "/#importar")
            expect(page.get_by_role("button", name="PC")).to_have_attribute("aria-pressed", "true")  # Linux = PC
            page.get_by_role("button", name="iPhone").click()
            expect(page.locator("[data-guide=iphone]").get_by_text("Agregar marcador")).to_be_visible()
            expect(page.locator("[data-bm]")).to_be_hidden()
            iphone = b.new_context(user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1").new_page()
            iphone.goto(URL)
            iphone.evaluate("t => localStorage.setItem('token', t)", page.evaluate("localStorage.getItem('token')"))
            iphone.goto(URL + "/?r=1#importar")
            expect(iphone.get_by_role("button", name="iPhone")).to_have_attribute("aria-pressed", "true")
            iphone.close()
            href = page.locator("[data-bm]").get_attribute("href")
            page.goto((ROOT / "tests" / "fixtures" / "phoenix_demo.html").as_uri())
            with page.expect_popup() as pop:
                page.evaluate(urllib.parse.unquote(href.removeprefix("javascript:")))
            imp = pop.value
            imp.on("pageerror", lambda e: errors.append(str(e)))
            expect(imp.get_by_label("Bases de Datos I [L-1]").locator("option:checked")).to_have_text("Bases de Datos (Lab)")
            expect(imp.get_by_label("Bases de Datos I [T-1]").locator("option:checked")).to_have_text("No importar")
            expect(imp.get_by_label("Ciberseguridad Avanzada [L-1]").locator("option:checked")).to_have_text("No importar")
            imp.get_by_role("button", name="Importar").click()
            imp.wait_for_url("**/#inicio")
            expect(imp.locator("[data-course]").filter(has_text="Bases de Datos").locator("[data-quedan]")).to_have_text("2")

            # marcar en 1 toque desde Inicio (últimas clases), sirve igual en PC, Android y iPhone
            q = imp.locator("[data-quick]").first
            was = q.get_attribute("aria-pressed") == "true"
            q.click()
            expect(imp.locator("[data-course]").filter(has_text="Bases de Datos").locator("[data-quedan]")).to_have_text("3" if was else "1")
            imp.close()

            # un diálogo abierto no debe quedar encima al cambiar de pantalla (ej: botón atrás)
            page.goto(URL + "/#inicio")
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
