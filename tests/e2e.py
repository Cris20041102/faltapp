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


def wait_notification(pg, title, seconds=5):
    """Espera a que el service worker muestre un aviso con ese título (evaluate sí espera promesas; wait_for_function no)."""
    for _ in range(seconds * 4):
        if title in pg.evaluate("navigator.serviceWorker.ready.then((r) => r.getNotifications()).then((n) => n.map((x) => x.title))"):
            return
        pg.wait_for_timeout(250)
    raise AssertionError(f"No se mostró el aviso {title!r}")


def sw_takeover(browser):
    """Con la app abierta y una versión vieja del service worker (sin avisos), la nueva debe tomar el control sola.
    Antes quedaba "esperando" y los avisos llegaban a la vieja, que no los mostraba."""
    import functools
    import http.server
    import shutil
    import threading
    root = Path(tempfile.mkdtemp())
    for f in (ROOT / "static").iterdir():
        shutil.copy(f, root)
    (root / "index.html").write_text('<!doctype html><script>navigator.serviceWorker.register("/sw.js")</script>')
    (root / "sw.js").write_text("self.addEventListener('fetch', () => {});")  # la "versión vieja"
    os.utime(root / "sw.js", (time.time() - 3600,) * 2)  # fecha anterior: si no, el servidor responde 304 y no ve el cambio
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8766), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:8766"
    try:
        ctx = browser.new_context()
        ctx.grant_permissions(["notifications"], origin=url)
        pg = ctx.new_page()
        pg.goto(url)
        pg.evaluate("navigator.serviceWorker.ready.then(() => 1)")
        pg.reload()
        pg.wait_for_function("navigator.serviceWorker.controller !== null")
        shutil.copy(ROOT / "static" / "sw.js", root / "sw.js")  # se publica la versión nueva
        pg.reload()
        pg.evaluate("navigator.serviceWorker.getRegistration().then((r) => r.update())")
        pg.wait_for_timeout(2000)
        cdp = ctx.new_cdp_session(pg)
        regs = []
        cdp.on("ServiceWorker.workerRegistrationUpdated", lambda e: regs.extend(e["registrations"]))
        cdp.send("ServiceWorker.enable")
        pg.wait_for_timeout(500)
        cdp.send("ServiceWorker.deliverPushMessage", {"origin": url, "registrationId": regs[0]["registrationId"], "data": '{"title": "Hola"}'})
        wait_notification(pg, "Hola")
        ctx.close()
    finally:
        srv.shutdown()


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
            b = pw.chromium.launch(channel="chromium")  # Chromium completo: el "headless shell" no soporta notificaciones
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
            expect(page.locator("[data-slot]")).to_have_count(7)  # 5 ramos; Eva. de Proyec. y BD Lab con 2 bloques
            expect(page.get_by_text("Choca con")).to_have_count(4)  # 2 topes: jueves 11:30 y viernes 09:45

            # topes en Inicio (1 de octubre): elegir a cuál ir, cambiar, deshacer, o turnarse
            tc = b.new_context(viewport={"width": 390, "height": 844})
            tc.clock.set_fixed_time("2026-10-01T12:00:00")
            tp = tc.new_page()
            tp.on("pageerror", lambda e: errors.append(str(e)))
            tp.goto(URL)
            tp.evaluate("t => localStorage.setItem('token', t)", page.evaluate("localStorage.getItem('token')"))
            tp.goto(URL + "/?r=1#inicio")
            jue = tp.locator("[data-tope]").filter(has_text="Jueves 11:30")
            expect(tp.locator("[data-tope]")).to_have_count(2)
            expect(jue).to_contain_text("¿A cuál vas?")
            expect(jue.get_by_role("button", name="Voy a Inv. de Oper. I")).to_contain_text("Reprobarías Bas. de Datos I")  # su único bloque
            jue.get_by_role("button", name="Voy a Inv. de Oper. I").click()
            expect(jue).to_contain_text("Vas a Inv. de Oper. I; Bas. de Datos I cuenta como falta")
            expect(jue.get_by_role("button", name="Voy a Inv. de Oper. I")).to_have_attribute("aria-pressed", "true")
            tp.screenshot(path=str(ROOT / "e2e-tope.png"))
            jue.get_by_role("button", name="Voy a Bas. de Datos I").click()  # cambia de opinión
            expect(jue).to_contain_text("Vas a Bas. de Datos I; Inv. de Oper. I cuenta como falta")
            jue.get_by_role("button", name="Voy a Bas. de Datos I").click()  # tocar la elegida la deshace
            expect(jue).to_contain_text("¿A cuál vas?")
            expect(tp.locator("[data-course]").filter(has_text="Inv. de Oper. I")).not_to_contain_text("planeas")
            vie = tp.locator("[data-tope]").filter(has_text="Viernes 09:45")
            vie.get_by_role("button", name="Me turno entre los dos").click()
            expect(vie).to_contain_text("Te turnas")
            tc.close()

            for _ in range(5):  # se borran para seguir con un horario conocido
                n = page.locator("[data-slot]").count()
                page.locator("[data-slot]").first.click()
                page.get_by_role("button", name="Eliminar el ramo completo").click()
                page.get_by_role("button", name="¿Seguro?").click()
                expect(page.locator("#dlg")).not_to_have_attribute("open", "")
                expect(page.locator("[data-slot]")).not_to_have_count(n)  # esperar que se refresque: si no, se toca el ramo recién borrado
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

            # apariencia: sigue el modo del dispositivo y se puede fijar a mano (queda guardado)
            bg = lambda c: page.wait_for_function(f"getComputedStyle(document.documentElement).backgroundColor === '{c}'", timeout=3000)
            noche, claro = "rgb(10, 1, 24)", "rgb(246, 244, 251)"
            expect(page.get_by_role("button", name="Automático")).to_have_attribute("aria-pressed", "true")
            page.emulate_media(color_scheme="dark")
            bg(noche)
            page.emulate_media(color_scheme="light")
            bg(claro)
            page.get_by_role("button", name="Oscuro").click()
            bg(noche)  # elegido a mano manda sobre el dispositivo
            page.reload()
            expect(page.get_by_role("button", name="Oscuro")).to_have_attribute("aria-pressed", "true")
            bg(noche)
            page.get_by_role("button", name="Automático").click()
            bg(claro)
            expect(page.locator("html")).not_to_have_attribute("data-theme", "dark")

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

            # progreso del semestre y aviso de "ya puedes faltar a todo" (fecha fija: 1 dic, queda solo el miércoles 2)
            token = imp.evaluate("localStorage.getItem('token')")
            imp.close()
            dic = b.new_context(viewport={"width": 390, "height": 844})  # contexto aparte: el reloj falso es por contexto
            dic.clock.set_fixed_time("2026-12-01T12:00:00")
            dp = dic.new_page()
            dp.goto(URL)
            dp.evaluate("t => localStorage.setItem('token', t)", token)
            dp.goto(URL + "/?r=1#inicio")
            bd = dp.locator("[data-course]").filter(has_text="Bases de Datos")
            expect(dp.locator("[data-progress]")).to_contain_text("Llevas 15 de 16 días de clases")
            expect(bd).to_contain_text("Van 15 de 16 clases")
            expect(bd.get_by_text("Ya puedes faltar a todas las que quedan")).to_be_visible()
            expect(dp.get_by_text("Ya puedes faltar a todo lo que queda del semestre")).to_be_visible()
            dic.close()
            # 1 de octubre: aún no puede faltar a todo, pero sí si va seguido unas semanas
            octc = b.new_context(viewport={"width": 390, "height": 844})
            octc.clock.set_fixed_time("2026-10-01T12:00:00")
            op = octc.new_page()
            op.goto(URL)
            op.evaluate("t => localStorage.setItem('token', t)", token)
            op.goto(URL + "/?r=1#inicio")
            expect(op.locator("[data-course]").filter(has_text="Bases de Datos").get_by_text("Ve a las próximas")).to_be_visible()
            expect(op.locator("[data-ir]")).to_contain_text("después puedes faltar a todo lo que queda del semestre")
            octc.close()

            # notificaciones: aviso en Inicio (se puede cerrar), tarjeta en el perfil y el service worker muestra el push
            page.goto(URL + "/#inicio")
            expect(page.get_by_text("Activa las notificaciones")).to_be_visible()
            page.goto(URL + "/#perfil")
            expect(page.get_by_role("button", name="Activar notificaciones")).to_be_visible()
            page.goto(URL + "/#inicio")
            page.get_by_role("button", name="Cerrar aviso").click()
            expect(page.get_by_text("Activa las notificaciones")).to_be_hidden()
            page.reload()
            expect(page.locator("[data-progress]")).to_be_visible()
            expect(page.get_by_text("Activa las notificaciones")).to_be_hidden()
            page.context.grant_permissions(["notifications"])
            reg = page.evaluate("navigator.serviceWorker.ready.then((r) => r.scope)")
            cdp = page.context.new_cdp_session(page)
            regs = []  # escuchar antes de activar: el evento puede llegar durante el enable
            cdp.on("ServiceWorker.workerRegistrationUpdated", lambda e: regs.extend(e["registrations"]))
            cdp.send("ServiceWorker.enable")
            for _ in range(50):  # el evento de registro llega cuando llega: esperar hasta 5 s, no un tiempo fijo
                rid = next((r["registrationId"] for r in regs if r["scopeURL"] == reg), None)
                if rid:
                    break
                page.wait_for_timeout(100)
            cdp.send("ServiceWorker.deliverPushMessage", {"origin": URL, "registrationId": rid,
                                                          "data": '{"title": "📝 Mañana: Certamen 2", "body": "BD", "url": "/#agenda"}'})
            wait_notification(page, "📝 Mañana: Certamen 2")

            # un diálogo abierto no debe quedar encima al cambiar de pantalla (ej: botón atrás)
            page.goto(URL + "/#inicio")
            day.click()
            page.evaluate("location.hash = '#agenda'")
            expect(page.locator("#dlg")).not_to_have_attribute("open", "")

            # recuperación: Phoenix trae el sábado 26/9 y no el miércoles 23/9 → esa clase se hizo el sábado
            r = page.evaluate("""async () => {
              const h = { "Content-Type": "application/json", Authorization: "Bearer " + localStorage.getItem("token") };
              const sems = await fetch("/api/semesters", { headers: h }).then((r) => r.json());
              const full = await fetch(`/api/semesters/${sems.find((s) => s.active).id}`, { headers: h }).then((r) => r.json());
              const id = full.courses.find((c) => c.name === "Bases de Datos").id;
              const items = [{ course_id: id, absent: ["2026-09-26"], present: ["2026-09-09", "2026-09-30"] }];
              return fetch("/api/absences/import", { method: "POST", headers: h, body: JSON.stringify({ items }) }).then((r) => r.json());
            }""")
            assert r["makeups"] == [{"course": "Bases de Datos", "original": "2026-09-23", "date": "2026-09-26"}], r
            page.goto(URL + "/#inicio")
            page.reload()
            expect(page.locator("[data-course]").filter(has_text="Bases de Datos")).to_contain_text("Clase del 23/09 recuperada el sábado 26 de septiembre")
            sab = page.locator('[data-date="2026-09-26"]')
            for _ in range(12):
                if sab.count():
                    break
                page.locator("[data-month-next]" if page.locator("[data-date]").first.get_attribute("data-date") < "2026-09" else "[data-month-prev]").click()
            sab.click()
            expect(page.locator("#dlg [data-slot]")).to_have_count(1)
            expect(page.locator("#dlg [data-slot]")).to_be_checked()  # faltó a la recuperación
            # quitarla y anotarla a mano desde el mismo día
            page.locator("#dlg [data-close]").click()
            bd = page.locator("[data-course]").filter(has_text="Bases de Datos")
            page.get_by_role("button", name="Quitar recuperación del 26/09").click()
            expect(bd).not_to_contain_text("recuperada")
            sab.click()
            expect(page.locator("#dlg [data-slot]")).to_have_count(0)
            page.get_by_text("¿Hubo clase recuperativa este día?").click()
            expect(page.locator("#dlg select[name=original] option").first).to_have_text("Miércoles 23 de septiembre")  # la más cercana
            page.get_by_role("button", name="Guardar recuperación").click()
            expect(bd).to_contain_text("Clase del 23/09 recuperada el sábado 26 de septiembre")
            assert not errors, errors
            sw_takeover(b)
            b.close()
        print("E2E PASS")
    finally:
        srv.terminate()


if __name__ == "__main__":
    main()
