"""E2E de la extensión de Chrome. Uso: python tests/e2e_extension.py  (no lo corre pytest).
Phoenix y Faltapp son simulados: se prueba que la extensión copie Phoenix, abra Faltapp de fondo y decida bien qué
hacer con la pestaña. Que Faltapp lea lo copiado se prueba con su lector real (readPhoenix de static/app.js)."""
import json
import tempfile
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PHX = "https://phoenix.cic.userena.cl/modulos/bitacora/alumnos/informacion/"
FALTAPP = "https://faltapp.appscristianrojo.cl"
APP = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
READER = APP[APP.index("const hasClass"):APP.index("const READERS")]


def reopen(sw, imp):
    """Las pestañas que abre una extensión no pasan por ctx.route en su primera carga (queda en error): se vuelve a
    cargar la misma dirección desde Playwright, que sí pasa por la Faltapp simulada. Es la misma pestaña de la extensión."""
    urls = sw.evaluate("chrome.tabs.query({}).then((ts) => ts.map((t) => t.url))")
    imp.goto(next(u for u in urls if u and u.startswith(FALTAPP)))


def main():
    ext = str(ROOT / "extension")
    mode = {"faltapp": "auto"}  # qué hace la Faltapp simulada: "auto" (importa sola) o "elegir" (pide emparejar ramos)

    def phoenix(route):
        name = route.request.url.split("/")[-1]
        files = {"fx_informacion_asistencia.php": "phoenix_demo.html", "fx_informacion_nota.php": "phoenix_notas_demo.html", "fx_informacion_hoja_vida.php": "phoenix_hoja_vida_demo.html"}
        html = (ROOT / "tests" / "fixtures" / files[name]).read_text(encoding="utf-8") if name in files else "<!doctype html><title>Phoenix</title><p>Inicio"
        route.fulfill(body=html.encode("cp1252", errors="replace"), headers={"content-type": "text/html; charset=iso8859-1"})

    def faltapp(route):
        then = 'location.hash = "#inicio"' if mode["faltapp"] == "auto" else 'document.title = "Elige tus ramos · Faltapp"'
        route.fulfill(content_type="text/html", body=f"""<!doctype html><title>Faltapp</title><script>{READER}
            window.read = readPhoenix(JSON.parse(decodeURIComponent(location.hash.slice("#importar/".length))).pages);
            setTimeout(() => {{ {then}; }}, 1500);</script>""")

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(tempfile.mkdtemp(), channel="chromium",
                                                    args=[f"--disable-extensions-except={ext}", f"--load-extension={ext}"])
        ctx.route("https://phoenix.cic.userena.cl/**", phoenix)
        ctx.route(FALTAPP + "/**", faltapp)
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
        page = ctx.new_page()

        # 1) ramos ya emparejados: abre Faltapp de fondo con lo copiado, se importa sola y la pestaña se cierra
        with ctx.expect_page() as opened:
            page.goto(PHX + "fx_informacion_principal.php")
        imp = opened.value
        reopen(sw, imp)
        sent = json.loads(urllib.parse.unquote(imp.url.split("#importar/", 1)[1]))
        assert sent["portal"] == "phoenix.cic.userena.cl" and sent["v"] == 4, sent.keys()
        read = imp.evaluate("window.read")
        lab = next(r for r in read["asistencia"] if r["section"] == "[L-1]" and r["name"] == "Bases de Datos I")
        assert lab["absent"] == ["2026-08-19", "2026-08-26"] and lab["justified"] == ["2026-09-02"], lab
        assert read["notas"], "no leyó las notas"
        assert read["carrera"] == "Ingeniería en Computación", read["carrera"]
        imp.wait_for_event("close", timeout=10000)
        assert sw.evaluate("chrome.action.getBadgeText({})") == "✓"

        # 2) otra página de Phoenix al rato: no vuelve a importar (como mucho cada 30 min)
        n = len(ctx.pages)
        page.goto(PHX + "fx_informacion_asistencia.php")
        page.wait_for_timeout(3000)
        assert len(ctx.pages) == n, [p.url for p in ctx.pages]

        # 3) ramo nuevo sin emparejar: la pestaña de Faltapp queda abierta y pasa adelante para elegir
        sw.evaluate("chrome.storage.local.clear()")
        mode["faltapp"] = "elegir"
        with ctx.expect_page() as opened:
            page.goto(PHX + "fx_informacion_principal.php")
        imp = opened.value
        reopen(sw, imp)
        imp.wait_for_function("document.title.startsWith('Elige')")
        active = None
        for _ in range(20):
            active = sw.evaluate("chrome.tabs.query({ active: true }).then((t) => t.map((x) => x.url))")
            if any(u and u.startswith(FALTAPP) for u in active):
                break
            page.wait_for_timeout(500)
        assert any(u and u.startswith(FALTAPP) for u in active), active
        assert not imp.is_closed()
        ctx.close()
    print("E2E EXTENSION PASS")


if __name__ == "__main__":
    main()
