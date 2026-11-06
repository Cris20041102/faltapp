// Corre en cada página de Phoenix. Como el marcador, solo COPIA las páginas (filas de tablas: clases de la fila y por
// celda [texto, clases de la celda y sus íconos, colspan, 1 si trae otra tabla]); la lectura la hace Faltapp.
// Una página con etiqueta ([dirección, "Etiqueta"]) copia solo esa fila: nada más de la página.
const PAGES = { asistencia: "/modulos/bitacora/alumnos/informacion/fx_informacion_asistencia.php", notas: "/modulos/bitacora/alumnos/informacion/fx_informacion_nota.php",
  carrera: ["/modulos/bitacora/alumnos/informacion/fx_informacion_hoja_vida.php", "Año Ingreso - Carrera"] };

async function snap(url, label) {
  const r = await fetch(new URL(url, location.href));
  if (!r.ok || r.redirected) return []; // sin sesión Phoenix manda al login
  const doc = new DOMParser().parseFromString(new TextDecoder(/charset=([\w-]+)/i.exec(r.headers.get("content-type"))?.[1] || "utf-8").decode(await r.arrayBuffer()), "text/html");
  doc.querySelectorAll("br").forEach((b) => b.replaceWith("\n"));
  if (label) {
    const l = [...doc.querySelectorAll("label")].find((x) => x.textContent.trim().startsWith(label));
    return l ? [["", [[(l.closest(".row") || l.parentElement).textContent.replace(/\s+/g, " ").trim(), "", 1, 0]]]] : [];
  }
  return [...doc.querySelectorAll("tr")].map((tr) => [tr.className, [...tr.children].map((td) => td.querySelector("table") ? ["", "", td.colSpan, 1]
    : [td.textContent.trim(), [td, ...td.querySelectorAll("[class]")].map((e) => e.className).join(" ").trim(), td.colSpan, 0])]);
}

(async () => {
  if (!(await chrome.runtime.sendMessage({ type: "due" }))) return; // ya se importó hace poco
  const pages = {};
  for (const [k, page] of Object.entries(PAGES)) pages[k] = await snap(...[].concat(page)).catch(() => []);
  if (Object.values(pages).some((rows) => rows.length)) chrome.runtime.sendMessage({ type: "import", portal: location.host, pages });
})();
