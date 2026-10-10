"use strict";

// ---------- utilidades ----------
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const iso = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
const today = () => iso(new Date());
const parse = (s) => new Date(s + "T12:00:00");
const weekdayOf = (s) => (parse(s).getDay() + 6) % 7; // 0 = lunes, como en el backend

const DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];
const SHORT = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];
const MONTHS = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];
const KINDS = { prueba: "Prueba", entrega: "Entrega", reunion: "Reunión", otro: "Otro" };
const COUNTRIES = { CL: "Chile", AR: "Argentina", BO: "Bolivia", BR: "Brasil", CO: "Colombia", EC: "Ecuador", ES: "España", US: "Estados Unidos", MX: "México", PY: "Paraguay", PE: "Perú", UY: "Uruguay", VE: "Venezuela" };
// Calendarios académicos precargados (fuente: calendario oficial de cada U). Agregar uno por semestre.
const CALENDARS = [
  { label: "Universidad de La Serena · 2º semestre 2026", name: "ULS 2026-2", start: "2026-08-10", end: "2026-12-04", country: "CL",
    off: [["2026-09-14", "Receso Fiestas Patrias"], ["2026-09-15", "Receso Fiestas Patrias"], ["2026-09-16", "Receso Fiestas Patrias"],
      ["2026-09-17", "Receso Fiestas Patrias"], ["2026-09-18", "Independencia Nacional"],
      ["2026-10-09", "Día del funcionario y receso estudiantil"], ["2026-10-12", "Encuentro de Dos Mundos"]] },
];
const COLOR = {
  verde: { cls: "bg-green-500 text-white", dot: "bg-green-500", label: "Puedes faltar" },
  amarillo: { cls: "bg-yellow-400 text-night", dot: "bg-yellow-400", label: "Justo en el límite" },
  rojo: { cls: "bg-red-500 text-white", dot: "bg-red-500", label: "No puedes faltar" },
  falta: { cls: "bg-fg text-canvas", dot: "bg-fg", label: "Falta marcada" },
  asistio: { cls: "bg-slate-200 text-slate-600", dot: "bg-slate-300", label: "Fuiste" },
  gris: { cls: "text-slate-400", dot: "bg-slate-100 border border-slate-300", label: "Sin clases" },
};
const longDate = (s) => { const d = parse(s); return `${DAYS[(d.getDay() + 6) % 7] || "Domingo"} ${d.getDate()} de ${MONTHS[d.getMonth()].toLowerCase()}`; };
const shortDate = (s) => { const d = parse(s); return `${d.getDate()}/${String(d.getMonth() + 1).padStart(2, "0")}`; };
const shiftMonth = (m, n) => { const [y, mo] = m.split("-").map(Number); const d = new Date(y, mo - 1 + n, 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };

const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* sin storage */ } },
};
let token = store.get("token");
let ME = null;

function toast(msg, bad = false) {
  const el = document.createElement("div");
  el.className = `pointer-events-auto max-w-sm rounded-xl px-4 py-2 text-sm font-medium shadow-lg ${bad ? "bg-red-600 text-white" : "border border-white/10 bg-[#1a1030] text-white"}`;
  el.textContent = msg;
  el.classList.add("toast-in");
  $("#toast").append(el);
  setTimeout(() => { el.classList.add("toast-out"); setTimeout(() => el.remove(), 250); }, 3500);
}

// Render gratis se duerme tras 15 min: si el servidor tarda, se muestran los datos guardados de la última vez,
// un aviso de que está despertando, y la pantalla se refresca sola cuando llegan los datos nuevos.
const SLOW_MS = 2000;
let pending = 0, slow = false, refreshTimer;
function waking(p) {
  pending++;
  const t = setTimeout(() => { slow = true; $("#waking").classList.remove("hidden"); }, SLOW_MS);
  return p.finally(() => {
    clearTimeout(t);
    if (!--pending) { slow = false; $("#waking").classList.add("hidden"); }
  });
}
const clearSaved = () => { try { Object.keys(localStorage).filter((k) => k.startsWith("api:")).forEach((k) => localStorage.removeItem(k)); } catch { /* sin storage */ } };

async function api(method, path, body, opts) {
  const net = waking(request(method, path, body, opts));
  const key = method === "GET" && token ? "api:" + path.replace(/[?&]today=[^&]*/, "") : null; // "today" cambia a diario
  if (key) net.then((d) => store.set(key, JSON.stringify(d)), () => {});
  const saved = key && store.get(key);
  if (!saved) return net;
  const late = Symbol();
  const first = slow ? late : await Promise.race([net, new Promise((r) => setTimeout(r, SLOW_MS, late))]);
  if (first !== late) return first;
  net.then(() => { clearTimeout(refreshTimer); refreshTimer = setTimeout(render, 100); }, () => {});
  return JSON.parse(saved);
}

async function request(method, path, body, { quiet = false } = {}) {
  const r = await fetch("/api" + path, {
    method,
    headers: { ...(body instanceof Blob ? {} : { "Content-Type": "application/json" }), ...(token ? { Authorization: "Bearer " + token } : {}) },
    body: body instanceof Blob ? body : body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 401 && !path.startsWith("/auth")) { logout(); throw new Error("Sesión expirada"); }
  if (r.status === 204) return null;
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data.detail;
    const msg = typeof d === "string" ? d : (d?.[0]?.msg || "Algo salió mal").replace(/^Value error, /, "");
    if (!quiet) toast(msg, true);
    throw Object.assign(new Error(msg), { status: r.status });
  }
  return data;
}

function logout() {
  const t = token;
  navigator.serviceWorker?.getRegistration().then((r) => r?.pushManager?.getSubscription()).then((sub) => sub && fetch("/api/push/subscribe", {
    method: "DELETE", headers: { "Content-Type": "application/json", Authorization: "Bearer " + t }, body: JSON.stringify({ endpoint: sub.endpoint }),
  })).catch(() => {});
  token = null; ME = null; store.set("token", null);
  clearSaved();
  location.hash = "#login";
}

async function activeSemester() {
  return (await api("GET", "/semesters")).find((s) => s.active) || null;
}

// ---------- diálogo ----------
function openDialog(html, onMount) {
  $("#dlg-body").innerHTML = html;
  const d = $("#dlg");
  if (!d.open) d.showModal();
  $$("[data-close]", d).forEach((b) => (b.onclick = () => d.close()));
  onMount?.(d);
}
const closeDialog = () => $("#dlg").close();
$("#dlg").addEventListener("click", (e) => { if (e.target.id === "dlg") closeDialog(); });

const formData = (f) => Object.fromEntries(new FormData(f));

// ---------- calendario ----------
const calMonths = {};
function calendar(el, key, colors, range, onPick, marks = new Set()) {
  const first = range.start.slice(0, 7), last = range.end.slice(0, 7);
  let m = calMonths[key] || today().slice(0, 7);
  if (m < first) m = first;
  if (m > last) m = last;
  calMonths[key] = m;
  const [y, mo] = m.split("-").map(Number);
  const pad = (new Date(y, mo - 1, 1).getDay() + 6) % 7;
  const n = new Date(y, mo, 0).getDate();
  const cells = Array(pad).fill("<div></div>");
  for (let d = 1; d <= n; d++) {
    const k = `${m}-${String(d).padStart(2, "0")}`;
    const c = colors[k];
    const ring = (k === today() ? " ring-2 ring-indigo-500 ring-offset-1" : "") + (marks.has(k) ? " relative after:absolute after:right-1 after:top-1 after:h-2 after:w-2 after:rounded-full after:bg-red-600 after:ring-2 after:ring-white" : "");
    cells.push(c && onPick // también los días sin clases: ahí se anota una clase recuperativa
      ? `<button data-date="${k}" title="${COLOR[c].label}" class="aspect-square rounded-lg text-sm ${c === "gris" ? "" : "font-semibold"} ${COLOR[c].cls}${ring}">${d}</button>`
      : `<div ${c ? `data-date="${k}"` : ""} title="${c ? COLOR[c].label : ""}" class="grid aspect-square place-items-center rounded-lg text-sm ${c ? COLOR[c].cls : "text-slate-300"}${ring}">${d}</div>`);
  }
  el.innerHTML = `
    <div class="mb-3 flex items-center justify-between">
      <button data-month-prev class="btn h-9 w-9 !p-0" ${m <= first ? "disabled" : ""} aria-label="Mes anterior">&#8249;</button>
      <h3 class="font-semibold">${MONTHS[mo - 1]} ${y}</h3>
      <button data-month-next class="btn h-9 w-9 !p-0" ${m >= last ? "disabled" : ""} aria-label="Mes siguiente">&#8250;</button>
    </div>
    <div class="mb-1 grid grid-cols-7 gap-1 text-center text-xs font-medium text-slate-400">${["L", "M", "M", "J", "V", "S", "D"].map((d) => `<div>${d}</div>`).join("")}</div>
    <div class="grid grid-cols-7 gap-1">${cells.join("")}</div>`;
  $("[data-month-prev]", el).onclick = () => { calMonths[key] = shiftMonth(m, -1); calendar(el, key, colors, range, onPick, marks); };
  $("[data-month-next]", el).onclick = () => { calMonths[key] = shiftMonth(m, 1); calendar(el, key, colors, range, onPick, marks); };
  if (onPick) $$("button[data-date]", el).forEach((b) => (b.onclick = () => onPick(b.dataset.date)));
}

const legend = (keys = ["verde", "amarillo", "rojo", "falta", "asistio"], withTests = false) =>
  `<div class="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">${withTests ? `<span class="flex items-center gap-1.5"><span class="h-2 w-2 rounded-full bg-red-600"></span>Prueba</span>` : ""}${keys.map((k) => `<span class="flex items-center gap-1.5"><span class="h-3 w-3 rounded ${COLOR[k].dot}"></span>${COLOR[k].label}</span>`).join("")}</div>`;

// ---------- login ----------
let loginMode = "login";
function login(v) {
  const reg = loginMode === "register";
  v.innerHTML = `
    <div class="mx-auto max-w-sm pt-6">
      <h1 class="h1 text-center text-4xl">Falta con <span class="bg-gradient-to-b from-indigo-700 to-indigo-500 bg-clip-text text-transparent">cabeza</span></h1>
      <p class="muted mt-1 text-center">Calcula cuántas clases puedes faltar y ponte de acuerdo con tus amigos.</p>
      <div class="mt-6 grid grid-cols-2 rounded-full border border-fg/10 bg-surface p-1 text-sm font-medium text-fg">
        <button data-mode="login" class="rounded-full py-2 ${reg ? "" : "bg-indigo-500 text-white"}">Entrar</button>
        <button data-mode="register" class="rounded-full py-2 ${reg ? "bg-indigo-500 text-white" : ""}">Crear cuenta</button>
      </div>
      <form class="card mt-4 space-y-3">
        <label class="field">Usuario<input class="input" name="username" autocomplete="username" required autocapitalize="none"></label>
        ${reg ? `<label class="field">Nombre<input class="input" name="display_name" required maxlength="60"></label>` : ""}
        <label class="field">Contraseña<input class="input" name="password" type="password" autocomplete="${reg ? "new-password" : "current-password"}" required minlength="6"></label>
        <button class="btn-primary w-full py-3">${reg ? "Crear cuenta" : "Entrar"}</button>
      </form>
    </div>`;
  $$("[data-mode]", v).forEach((b) => (b.onclick = () => { loginMode = b.dataset.mode; login(v); }));
  $("form", v).onsubmit = async (e) => {
    e.preventDefault();
    const { token: t } = await api("POST", reg ? "/auth/register" : "/auth/login", formData(e.target));
    token = t; store.set("token", t);
    clearSaved();
    location.hash = "#inicio";
  };
}

// ---------- inicio ----------
// tope de horario: pares de clases de ramos distintos que se pisan el mismo día
const clashes = (courses) => {
  const xs = courses.flatMap((c) => c.slots.map((x) => ({ ...x, c })));
  return xs.flatMap((a, i) => xs.slice(i + 1)
    .filter((b) => b.weekday === a.weekday && b.c.id !== a.c.id && a.start_time < b.end_time && b.start_time < a.end_time).map((b) => [a, b]));
};

// clases de un día: la clase recuperada sale de su día original y aparece el día en que se hizo
const slotsOn = (courses, d) => courses.flatMap((c) => c.slots
  .filter((x) => (x.weekday === weekdayOf(d) && !c.makeups.some((m) => m.original === d)) || c.makeups.some((m) => m.date === d && weekdayOf(m.original) === x.weekday))
  .map((x) => ({ ...x, c }))).sort((a, b) => a.start_time.localeCompare(b.start_time));

// ---------- notas: ¿cuánto necesito? (escala chilena 1,0–7,0) ----------
const nota = (n) => (Math.round(n * 10 + 1e-9) / 10).toFixed(1).replace(".", ","); // 4,35 → 4,4 (no 4,3 por el redondeo binario)
const num = (v) => { const t = String(v ?? "").trim().replace(",", "."); return t === "" || isNaN(t) ? null : Number(t); };
const junto = (xs) => (xs.length > 2 ? `${xs.slice(0, -1).join(", ")} y ${xs.at(-1)}` : xs.join(" y "));
function gradeCalc(g) { // → nota final si ya rindió todo, o la nota que necesita en lo que queda para llegar a la meta
  const items = (g?.items || []).filter((i) => i.weight > 0), meta = g?.meta ?? 4;
  const total = items.reduce((a, i) => a + i.weight, 0);
  if (!total) return null;
  const done = items.filter((i) => i.grade != null), rest = items.filter((i) => i.grade == null);
  const sum = done.reduce((a, i) => a + i.weight * i.grade, 0), wRest = rest.reduce((a, i) => a + i.weight, 0);
  const prom = done.length ? sum / (total - wRest) : null;
  if (!wRest) return { meta, total, prom, final: Math.round((sum / total) * 10 + 1e-9) / 10 }; // 3,95 → 4,0
  // sin contar el redondeo a favor (3,95 → 4,0): mejor que sobre a que falte
  return { meta, total, prom, rest: rest.map((i) => i.name), need: Math.ceil(((meta * total - sum) / wRest) * 10 - 1e-9) / 10, max: (sum + 7 * wRest) / total };
}
const gradeText = (r) => !r ? ""
  : r.final != null ? `${r.final >= r.meta ? "✅" : "❌"} Nota final ${nota(r.final)}`
  : r.need <= 1 ? `🎉 Ya tienes el ${nota(r.meta)} asegurado`
  : r.need > 7 ? `😬 No alcanza: con 7,0 en todo llegarías a ${nota(r.max)}`
  : `Necesitas ${nota(r.need)} en ${junto(r.rest)}`;

function openGrades(c) {
  const g = c.grades || { meta: 4, items: [{ name: "Certamen 1", weight: 30 }, { name: "Certamen 2", weight: 30 }, { name: "Examen", weight: 40 }] };
  const row = (i = {}) => `
    <div data-row class="grid grid-cols-[1fr_4rem_4rem_2rem] items-center gap-2">
      <input class="input !mt-0" name="name" maxlength="40" placeholder="Evaluación" value="${esc(i.name ?? "")}" aria-label="Evaluación">
      <input class="input !mt-0 text-center" name="weight" inputmode="decimal" placeholder="%" value="${i.weight ?? ""}" aria-label="Porcentaje de ${esc(i.name ?? "la evaluación")}">
      <input class="input !mt-0 text-center" name="grade" inputmode="decimal" placeholder="—" value="${i.grade != null ? nota(i.grade) : ""}" aria-label="Nota de ${esc(i.name ?? "la evaluación")}">
      <button type="button" data-del-row class="h-8 w-8 rounded-full" aria-label="Quitar evaluación">&#10005;</button>
    </div>`;
  openDialog(`
    <form data-grades-form class="p-5">
      <div class="flex items-start justify-between gap-2">
        <div><h2 class="h2">📝 Notas · ${esc(c.name)}</h2><p class="muted">Pon el % de cada evaluación y las notas que ya tienes. Deja vacía la nota de lo que falta.</p></div>
        <button type="button" data-close class="btn h-9 w-9 shrink-0 !p-0" aria-label="Cerrar">&#10005;</button>
      </div>
      <div class="mt-4 grid grid-cols-[1fr_4rem_4rem_2rem] gap-2 px-1 text-xs font-medium text-slate-500"><span>Evaluación</span><span class="text-center">%</span><span class="text-center">Nota</span><span></span></div>
      <div data-rows class="mt-1 space-y-2">${g.items.map(row).join("")}</div>
      <button type="button" data-add-row class="mt-2 text-sm font-medium text-indigo-600">+ Agregar evaluación</button>
      <label class="field mt-3">Nota que quieres sacar<input name="meta" class="input" inputmode="decimal" value="${nota(g.meta)}"></label>
      <div data-result class="mt-4 rounded-xl bg-indigo-50 p-3 text-sm text-indigo-900" aria-live="polite"></div>
      <button class="btn-primary mt-4 w-full">Guardar</button>
    </form>`, (d) => {
    const f = $("[data-grades-form]", d);
    const read = () => ({
      meta: num(f.meta.value) ?? 4,
      items: $$("[data-row]", f).map((r, n) => ({ name: r.querySelector("[name=name]").value.trim() || `Evaluación ${n + 1}`, weight: num(r.querySelector("[name=weight]").value), grade: num(r.querySelector("[name=grade]").value) }))
        .filter((i) => i.weight != null || i.grade != null),
    });
    const show = () => {
      const x = read(), r = gradeCalc(x), total = x.items.reduce((a, i) => a + (i.weight || 0), 0);
      const bad = x.items.some((i) => i.grade != null && (i.grade < 1 || i.grade > 7)) || x.meta < 1 || x.meta > 7;
      $("[data-result]", f).innerHTML = bad ? "Las notas van de 1,0 a 7,0."
        : total > 100 ? `Los porcentajes suman ${total}%: no pueden pasar de 100%.`
        : !r ? "Pon el porcentaje de cada evaluación."
        : `<p class="font-semibold">${gradeText(r)}</p>${r.prom != null && r.final == null ? `<p class="mt-1">Llevas un ${nota(r.prom)} en lo rendido.</p>` : ""}${total !== 100 ? `<p class="mt-1 opacity-80">Los porcentajes suman ${total}% (calculado sobre ese total).</p>` : ""}`;
    };
    const bindRows = () => $$("[data-del-row]", f).forEach((b) => (b.onclick = () => { b.closest("[data-row]").remove(); show(); }));
    $("[data-add-row]", f).onclick = () => { $("[data-rows]", f).insertAdjacentHTML("beforeend", row()); bindRows(); };
    bindRows();
    f.oninput = show;
    show();
    f.onsubmit = async (e) => {
      e.preventDefault();
      await api("PUT", `/courses/${c.id}/grades`, read());
      toast("Notas guardadas");
      closeDialog(); render();
    };
  });
}

function courseCard(c) {
  const tone = c.quedan < 0 ? "text-red-600" : c.quedan === 0 ? "text-yellow-600" : "text-green-600";
  const msg = c.quedan < 0 ? "Reprobado por asistencia" : c.quedan === 0 ? "Sin margen: no faltes más" : c.quedan === 1 ? "falta disponible" : "faltas disponibles";
  return `
    <article data-course="${c.id}" class="card">
      <div class="flex items-start justify-between gap-2">
        <h3 class="font-semibold leading-tight">${esc(c.name)}</h3>
        <span class="shrink-0 rounded-full ${c.kind === "L" ? "bg-amber-100 text-amber-800" : "bg-indigo-100 text-indigo-800"} px-2 py-0.5 text-xs font-medium">${c.kind === "L" ? "Lab" : "Teoría"} · ${c.min_pct}%</span>
      </div>
      <div class="mt-2 flex items-baseline gap-2"><span data-quedan class="text-4xl font-bold ${tone}">${c.quedan}</span><span class="text-sm text-slate-600">${msg}</span></div>
      <p class="mt-1 text-xs text-slate-500">Van ${c.dictadas} de ${c.total} clases · mínimo ${c.minimo} · faltaste ${c.reales}${c.planeadas ? ` · planeas ${c.planeadas}` : ""}</p>
      ${c.faltar_todo ? `<p class="mt-2 rounded-lg bg-green-50 px-2 py-1 text-xs font-medium text-green-700">🎉 Ya puedes faltar a todas las que quedan (${c.restantes - c.planeadas})</p>` : ""}
      ${c.makeups.map((m) => `<p class="mt-2 flex items-center gap-2 text-xs text-slate-500"><span class="flex-1">🔁 Clase del ${shortDate(m.original)} recuperada el ${longDate(m.date).toLowerCase()}</span><button data-unmakeup="${m.id}" class="h-7 w-7 shrink-0 rounded-full" aria-label="Quitar recuperación del ${shortDate(m.date)}">&#10005;</button></p>`).join("")}
      <button data-grades="${c.id}" class="mt-2 block text-left text-sm font-medium text-indigo-600">📝 ${gradeText(gradeCalc(c.grades)) || "¿Cuánto necesito en el examen?"}</button>
      ${c.ir_seguido ? `<p class="mt-2 rounded-lg bg-indigo-50 px-2 py-1 text-xs font-medium text-indigo-700">💪 Ve a ${c.ir_seguido.clases === 1 ? "la próxima clase" : `las próximas ${c.ir_seguido.clases} clases`} (hasta el ${shortDate(c.ir_seguido.hasta)}) y después puedes faltar a ${c.ir_seguido.luego === 1 ? "la que queda" : `las ${c.ir_seguido.luego} que quedan`}</p>` : ""}
    </article>`;
}

async function inicio(v) {
  const sem = await activeSemester();
  if (!sem) { location.hash = "#semestre"; return; }
  const [s, pstate] = await Promise.all([api("GET", `/semesters/${sem.id}/summary?today=${today()}`), pushState()]);
  const pushBanner = ["off", "ios"].includes(pstate) && !store.get("push-banner-off");
  const wd = Object.entries(s.weekdays);
  // las 2 últimas jornadas con clases (hasta hoy): marcar una falta es 1 toque, sin buscar en el calendario
  const recent = Object.keys(s.calendar).filter((d) => d <= today() && s.calendar[d] !== "gris").sort().slice(-2).reverse();
  const dayLabel = (d) => (d === today() ? "Hoy" : d === iso(new Date(Date.now() - 864e5)) ? "Ayer" : longDate(d));
  // topes: en ese bloque va a un ramo y el otro queda como falta desde hoy (o se turna y marca día a día)
  const absent = new Set(s.absences.map((a) => `${a.slot_id}|${a.date}`));
  const ahead = (x) => Object.keys(s.calendar).filter((d) => d >= today() && s.calendar[d] !== "gris" && weekdayOf(d) === x.weekday);
  const pending = (x) => ahead(x).filter((d) => !absent.has(`${x.id}|${d}`)).length;
  const after = (x) => { // cómo queda el ramo de x si deja de ir a ese bloque
    const n = x.c.quedan - pending(x);
    return n < 0 ? `Reprobarías ${esc(x.c.name)}` : n === 0 ? `${esc(x.c.name)} queda sin margen` : `${esc(x.c.name)}: te quedarían ${n} falta${n > 1 ? "s" : ""}`;
  };
  const tope = ([a, b]) => {
    const key = `tope-${a.id}-${b.id}`, goA = !pending(b) && pending(a) > 0, goB = !pending(a) && pending(b) > 0;
    const turno = !goA && !goB && store.get(key) === "turno", calm = goA || goB || turno;
    const opt = (go, skip, on) => `
      <button data-tope-go="${go.id}" data-tope-skip="${skip.id}" data-switch="${pending(go) ? "" : 1}" aria-pressed="${on}" class="rounded-xl border p-3 text-left ${on ? "border-indigo-500 bg-indigo-500 text-white" : "border-fg/10 bg-surface text-fg"}">
        <span class="block font-medium">Voy a ${esc(go.c.name)}</span><span class="block text-xs opacity-80">${after(skip)}</span></button>`;
    return `
      <section data-tope class="mt-4 rounded-2xl p-4 ${calm ? "border border-fg/10 bg-surface" : "border border-amber-500/30 bg-amber-50 text-amber-900"}">
        <h2 class="font-semibold">⚠️ Tope de horario · ${DAYS[a.weekday]} ${[a.start_time, b.start_time].sort()[0]}</h2>
        <p class="mt-1 text-sm">${goA || goB ? `Vas a ${esc((goA ? a : b).c.name)}; ${esc((goA ? b : a).c.name)} cuenta como falta en ese bloque.`
          : turno ? "Te turnas: cada semana marca en «¿Fuiste a clases?» a cuál faltaste."
          : `${esc(a.c.name)} y ${esc(b.c.name)} son a la misma hora. ¿A cuál vas? El otro queda como falta en ese bloque desde hoy.`}</p>
        <div class="mt-3 grid grid-cols-2 gap-2">${opt(a, b, goA)}${opt(b, a, goB)}</div>
        ${calm ? "" : `<button data-tope-turno="${key}" class="mt-2 text-sm font-medium underline">Me turno entre los dos</button>`}
      </section>`;
  };
  const topes = clashes(s.courses).filter(([a]) => ahead(a).length).sort(([a], [b]) => a.weekday - b.weekday || a.start_time.localeCompare(b.start_time));
  v.innerHTML = `
    <div class="flex items-end justify-between">
      <div><p class="muted">Semestre</p><h1 class="h1">${esc(sem.name)}</h1></div>
      <div class="flex flex-col items-end gap-1 text-sm font-medium text-indigo-600"><a href="#importar">Importar de Phoenix</a><a href="#semestre">Fechas y feriados</a></div>
    </div>
    ${pushBanner ? `
      <section class="mt-4 flex items-start gap-3 rounded-2xl bg-amber-50 p-4 text-amber-900">
        <span class="text-2xl" aria-hidden="true">🔔</span>
        <div class="flex-1"><p class="font-semibold">Activa las notificaciones</p>
          <p class="text-sm">Te avisamos de pruebas, de cuando te quedan pocas faltas y de tus amigos.</p>
          ${pstate === "ios" ? `<a href="#perfil" class="btn mt-2">Cómo activarlas en iPhone</a>` : `<button data-push-on class="btn-primary mt-2">Activar</button>`}</div>
        <button data-push-dismiss class="h-8 w-8 shrink-0 text-amber-700" aria-label="Cerrar aviso">&#10005;</button>
      </section>` : ""}
    ${topes.map(tope).join("")}
    ${s.days.total ? `
      <section data-progress class="card mt-4">
        <h2 class="h2">Llevas ${s.days.done} de ${s.days.total} días de clases</h2>
        <div class="mt-2 h-2 overflow-hidden rounded-full bg-fg/10"><div class="h-2 rounded-full bg-gradient-to-r from-indigo-500 to-indigo-700" style="width:${Math.round((100 * s.days.done) / s.days.total)}%"></div></div>
        <p class="mt-1 text-xs text-slate-500">${s.days.total - s.days.done ? `Quedan ${s.days.total - s.days.done} días de clases` : "Se terminaron las clases del semestre"}</p>
      </section>` : ""}
    ${s.ir_seguido ? `
      <section data-ir class="mt-4 rounded-2xl bg-indigo-50 p-4 text-indigo-900">
        <p class="font-semibold">💪 Si vas seguido ${s.ir_seguido.dias === 1 ? "el próximo día de clases" : `los próximos ${s.ir_seguido.dias} días de clases`} (hasta el ${longDate(s.ir_seguido.hasta).toLowerCase()}), después puedes faltar a todo lo que queda del semestre.</p>
      </section>` : ""}
    ${s.courses.length && s.courses.every((c) => c.faltar_todo) ? `
      <section class="mt-4 rounded-2xl bg-green-600 p-4 text-white">
        <p class="font-semibold">🎉 Ya puedes faltar a todo lo que queda del semestre</p>
        <p class="mt-1 text-sm opacity-90">Por asistencia ya cumples en todos tus ramos. Ojo con las pruebas: revisa tu <a href="#agenda" class="underline">Agenda</a>.</p>
      </section>` : ""}
    ${s.courses.length && recent.length ? `
      <section class="card mt-4">
        <h2 class="h2">¿Fuiste a clases?</h2>
        <p class="muted">Toca la clase a la que faltaste.</p>${recent.map((d) => {
          const marked = new Set(s.absences.filter((a) => a.date === d).map((a) => a.slot_id));
          return `
        <h3 class="mt-3 text-sm font-semibold text-slate-600">${dayLabel(d)}</h3>
        <ul class="mt-1 space-y-2">${slotsOn(s.courses, d).map((x) => `
          <li><button data-quick="${d}" data-slot-id="${x.id}" aria-pressed="${marked.has(x.id)}" class="flex w-full items-center gap-3 rounded-xl border p-3 text-left ${marked.has(x.id) ? "border-indigo-500 bg-indigo-500 text-white" : "border-fg/10 bg-surface"}">
            <span class="flex-1"><span class="font-medium">${esc(x.c.name)}</span> <span class="text-xs opacity-70">${x.c.kind === "L" ? "Lab" : "Teoría"} · ${x.start_time.slice(0, 5)}</span></span>
            <span class="text-sm font-semibold">${marked.has(x.id) ? "Faltaste · deshacer" : "Falté"}</span></button></li>`).join("")}
        </ul>`;
        }).join("")}
      </section>` : ""}
    ${s.courses.length ? `
      <section class="card mt-4">
        <h2 class="h2">Días completos que aún puedes faltar</h2>
        <div class="mt-3 grid ${["grid-cols-1", "grid-cols-2", "grid-cols-3", "grid-cols-4", "grid-cols-5", "grid-cols-6"][Math.min(wd.length, 6) - 1]} gap-2">${wd.map(([w, n]) => `
          <div class="rounded-xl ${n > 0 ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"} py-2 text-center" title="Puedes faltar ${n} ${DAYS[w].toLowerCase()} más">
            <div class="text-xs font-medium">${SHORT[w]}</div><div class="text-2xl font-bold">${n}</div></div>`).join("")}
        </div>
      </section>` : `
      <section class="card mt-4 text-center">
        <p class="font-medium">Aún no cargas tu horario.</p>
        <a href="#horario" class="btn-primary mt-3">Cargar horario</a>
      </section>`}
    <section class="card mt-4"><div id="cal"></div>${legend(undefined, true)}</section>
    <section class="mt-4 grid gap-3 sm:grid-cols-2">${s.courses.map(courseCard).join("")}</section>`;
  const tests = new Set(s.events.filter((e) => e.kind === "prueba").map((e) => e.date));
  bindPush(v);
  const dismiss = $("[data-push-dismiss]", v);
  if (dismiss) dismiss.onclick = () => { store.set("push-banner-off", "1"); render(); };
  $$("[data-quick]", v).forEach((b) => (b.onclick = async () => {
    const r = await api(b.getAttribute("aria-pressed") === "true" ? "DELETE" : "POST", "/absences", { date: b.dataset.quick, slot_ids: [Number(b.dataset.slotId)] });
    r?.warnings?.forEach((m) => toast("⚠ " + m));
    render();
  }));
  $$("[data-tope-go]", v).forEach((b) => (b.onclick = async () => {
    const on = b.getAttribute("aria-pressed") !== "true"; // tocar la opción elegida la deshace
    if (on && b.dataset.switch) await api("POST", `/slots/${b.dataset.topeGo}/rest`, { since: today(), absent: false });
    await api("POST", `/slots/${b.dataset.topeSkip}/rest`, { since: today(), absent: on });
    render();
  }));
  $$("[data-tope-turno]", v).forEach((b) => (b.onclick = () => { store.set(b.dataset.topeTurno, "turno"); render(); }));
  $$("[data-unmakeup]", v).forEach((b) => (b.onclick = async () => { await api("DELETE", `/makeups/${b.dataset.unmakeup}`); render(); }));
  $$("[data-grades]", v).forEach((b) => (b.onclick = () => openGrades(s.courses.find((c) => c.id === Number(b.dataset.grades)))));
  calendar($("#cal", v), "home", s.calendar, { start: s.semester.start_date, end: s.semester.end_date }, (d) => openDay(s, d), tests);
}

function openDay(s, day) {
  const slots = slotsOn(s.courses, day);
  const marked = new Set(s.absences.filter((a) => a.date === day).map((a) => a.slot_id));
  const events = s.events.filter((e) => e.date === day);
  const past = day < today();
  openDialog(`
    <div class="p-5">
      <div class="flex items-start justify-between">
        <div><h2 class="h2">${longDate(day)}</h2><p class="muted">${COLOR[s.calendar[day]].label}${past || !slots.length ? "" : " · futura: queda como falta planeada"}</p></div>
        <button data-close class="btn h-9 w-9 !p-0" aria-label="Cerrar">&#10005;</button>
      </div>
      ${events.map((e) => `<div class="mt-3 rounded-xl ${e.kind === "prueba" ? "bg-red-50 text-red-800" : "bg-sky-50 text-sky-800"} px-3 py-2 text-sm"><b>${KINDS[e.kind]}</b> · ${esc(e.title)}${e.time ? ` · ${e.time}` : ""}</div>`).join("")}
      ${slots.length ? `
      <p class="mt-4 text-sm font-medium text-slate-600">Marca las clases a las que ${past ? "faltaste" : "vas a faltar"}:</p>
      <ul class="mt-2 space-y-2">${slots.map((x) => `
        <li><label class="flex cursor-pointer items-center gap-3 rounded-xl border border-slate-200 p-3">
          <input type="checkbox" data-slot="${x.id}" ${marked.has(x.id) ? "checked" : ""} class="h-5 w-5 accent-indigo-600">
          <span class="flex-1"><span class="font-medium">${esc(x.c.name)}</span> <span class="text-xs text-slate-500">${x.c.kind === "L" ? "Lab" : "Teoría"}</span></span>
          <span class="text-xs text-slate-500">${x.start_time}–${x.end_time}</span></label></li>`).join("")}
      </ul>
      <div class="mt-4 grid grid-cols-2 gap-2">
        <button data-all class="btn-primary">Faltar todo el día</button>
        <button data-none class="btn">Quitar faltas</button>
      </div>` : ""}
      <a href="#agenda/${day}" class="mt-4 block text-center text-sm font-medium text-indigo-600">+ Agregar prueba o evento este día</a>
      ${s.courses.length ? `
      <details class="mt-4 rounded-xl border border-fg/10 p-3">
        <summary class="cursor-pointer text-sm font-medium text-fg">🔁 ¿Hubo clase recuperativa este día?</summary>
        <form data-makeup class="mt-3 space-y-3">
          <label class="field">Ramo<select class="input" name="course">${s.courses.map((c) => `<option value="${c.id}">${esc(c.name)} (${c.kind === "L" ? "Lab" : "Teoría"})</option>`).join("")}</select></label>
          <label class="field">Recupera la clase del<select class="input" name="original"></select></label>
          <button class="btn-primary w-full">Guardar recuperación</button>
        </form>
      </details>` : ""}
    </div>`, (d) => {
    const warn = (r) => r?.warnings?.forEach((m) => toast("⚠ " + m));
    $$("[data-slot]", d).forEach((cb) => (cb.onchange = async () => {
      try {
        warn(await api(cb.checked ? "POST" : "DELETE", "/absences", { date: day, slot_ids: [Number(cb.dataset.slot)] }));
      } catch { cb.checked = !cb.checked; }
      render();
    }));
    if (slots.length) {
      $("[data-all]", d).onclick = async () => { warn(await api("POST", "/absences", { date: day })); closeDialog(); render(); };
      $("[data-none]", d).onclick = async () => { await api("DELETE", "/absences", { date: day }); closeDialog(); render(); };
    }
    const f = $("[data-makeup]", d);
    if (f) { // clases de ese ramo que se pudieron mover a este día, la más cercana primero
      const fill = () => (f.original.innerHTML = Object.keys(s.calendar)
        .filter((x) => x !== day && slotsOn(s.courses, x).some((y) => y.c.id === Number(f.course.value)))
        .sort((a, b) => Math.abs(parse(a) - parse(day)) - Math.abs(parse(b) - parse(day)) || a.localeCompare(b))
        .map((x) => `<option value="${x}">${longDate(x)}</option>`).join(""));
      f.course.onchange = fill;
      fill();
      f.onsubmit = async (e) => {
        e.preventDefault();
        await api("POST", `/courses/${f.course.value}/makeups`, { original: f.original.value, date: day });
        toast("Recuperación guardada");
        closeDialog(); render();
      };
    }
    $$("a", d).forEach((a) => a.addEventListener("click", closeDialog));
  });
}

// ---------- horario ----------
async function horario(v) {
  const sem = await activeSemester();
  if (!sem) { location.hash = "#semestre"; return; }
  const full = await api("GET", `/semesters/${sem.id}`);
  const byDay = DAYS.map((_, w) => full.courses
    .flatMap((c) => c.slots.filter((x) => x.weekday === w).map((x) => ({ ...x, course: c })))
    .sort((a, b) => a.start_time.localeCompare(b.start_time)));
  const topes = clashes(full.courses);
  const choca = (x) => topes.flatMap(([a, b]) => (a.id === x.id ? [b] : b.id === x.id ? [a] : []));
  v.innerHTML = `
    <h1 class="h1">Horario</h1>
    <p class="muted">Toca + para agregar una clase, o una clase para editarla. Teoría y laboratorio van como ramos separados.</p>
    <label class="card mt-4 flex cursor-pointer items-center gap-3 border-dashed">
      <span class="flex-1"><span class="font-medium">¿Eres de la ULS?</span><span class="block text-sm text-slate-500">Sube el PDF de tu horario y se cargan solos tus ramos.</span></span>
      <span class="btn-primary shrink-0">Subir PDF</span>
      <input type="file" accept="application/pdf" class="sr-only" aria-label="Subir PDF de horario ULS" data-pdf>
    </label>
    <div class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">${DAYS.map((d, w) => `
      <section class="card !p-3">
        <div class="flex items-center justify-between">
          <h2 class="font-semibold">${d}</h2>
          <button data-add="${w}" aria-label="Agregar clase el ${d}" class="grid h-8 w-8 place-items-center rounded-full bg-indigo-600 text-lg leading-none text-white">+</button>
        </div>
        <ul class="mt-2 space-y-2">${byDay[w].map((x) => `
          <li><button data-slot="${x.id}" class="w-full rounded-xl border px-3 py-2 text-left ${x.course.kind === "L" ? "border-amber-200 bg-amber-50" : "border-indigo-200 bg-indigo-50"}">
            <div class="text-xs text-slate-500">${x.start_time}–${x.end_time}</div>
            <div class="font-medium leading-tight">${esc(x.course.name)}</div>
            <div class="text-xs text-slate-500">${x.course.kind === "L" ? "Laboratorio" : "Teoría"} · mín. ${x.course.min_pct}%</div>
            ${choca(x).map((o) => `<div class="mt-1 text-xs font-medium text-red-600">⚠️ Choca con ${esc(o.c.name)}</div>`).join("")}
          </button></li>`).join("") || `<li class="text-sm text-slate-400">Sin clases</li>`}
        </ul>
      </section>`).join("")}
    </div>`;
  $("[data-pdf]", v).onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const r = await api("POST", `/semesters/${full.id}/import-uls`, file);
    toast(r.created ? `${r.created} ramo${r.created > 1 ? "s" : ""} cargado${r.created > 1 ? "s" : ""}. Revisa el % mínimo de cada uno.` : "Esos ramos ya estaban cargados");
    const n = clashes((await api("GET", `/semesters/${full.id}`)).courses).length;
    if (n) toast(`Tienes ${n === 1 ? "un tope" : `${n} topes`} de horario: en Inicio eliges a cuál vas.`);
    render();
  };
  $$("[data-add]", v).forEach((b) => (b.onclick = () => slotDialog(full, Number(b.dataset.add))));
  $$("[data-slot]", v).forEach((b) => (b.onclick = () => {
    const course = full.courses.find((c) => c.slots.some((x) => x.id === Number(b.dataset.slot)));
    slotDialog(full, null, course, course.slots.find((x) => x.id === Number(b.dataset.slot)));
  }));
}

const slotsBody = (slots) => slots.map(({ id, weekday, start_time, end_time }) => ({ id, weekday, start_time, end_time }));

function slotDialog(full, weekday, course = null, slot = null) {
  const w = slot ? slot.weekday : weekday;
  openDialog(`
    <form class="space-y-3 p-5">
      <h2 class="h2">${slot ? "Editar clase" : "Nueva clase"} · ${DAYS[w]}</h2>
      ${course ? "" : `<label class="field">Ramo<select name="course" class="input"><option value="">Ramo nuevo…</option>${full.courses.map((c) => `<option value="${c.id}">${esc(c.name)} (${c.kind === "L" ? "Lab" : "Teoría"})</option>`).join("")}</select></label>`}
      <div data-new class="space-y-3">
        <label class="field">Nombre del ramo<input class="input" name="name" maxlength="80" value="${esc(course?.name)}"></label>
        <div class="grid grid-cols-2 gap-3">
          <label class="field">Tipo<select class="input" name="kind"><option value="T">Teoría</option><option value="L" ${course?.kind === "L" ? "selected" : ""}>Laboratorio</option></select></label>
          <label class="field">% mínimo<input class="input" name="min_pct" type="number" min="1" max="100" value="${course?.min_pct ?? 60}"></label>
        </div>
      </div>
      <div class="grid grid-cols-2 gap-3">
        <label class="field">Desde<input class="input" name="start_time" type="time" required value="${slot?.start_time ?? ""}"></label>
        <label class="field">Hasta<input class="input" name="end_time" type="time" required value="${slot?.end_time ?? ""}"></label>
      </div>
      <div class="flex flex-wrap justify-end gap-2 pt-2">
        ${slot ? `<button type="button" data-del-slot class="btn-danger mr-auto">Quitar clase</button>` : ""}
        <button type="button" data-close class="btn">Cancelar</button>
        <button class="btn-primary">Guardar</button>
      </div>
      ${slot ? `<button type="button" data-del-course class="w-full text-center text-xs text-red-600">Eliminar el ramo completo</button>` : ""}
    </form>`, (d) => {
    const f = $("form", d);
    let pctTouched = !!course;
    f.min_pct.oninput = () => (pctTouched = true);
    f.kind.onchange = () => { if (!pctTouched) f.min_pct.value = f.kind.value === "L" ? 70 : 60; };
    if (f.course) f.course.onchange = () => ($("[data-new]", d).hidden = !!f.course.value);
    f.onsubmit = async (e) => {
      e.preventDefault();
      const x = formData(f);
      const newSlot = { weekday: w, start_time: x.start_time, end_time: x.end_time };
      const target = course || full.courses.find((c) => c.id === Number(x.course));
      if (target) {
        const slots = slotsBody(target.slots).map((s) => (slot && s.id === slot.id ? { ...s, ...newSlot } : s));
        await api("PATCH", `/courses/${target.id}`, {
          ...(course ? { name: x.name, kind: x.kind, min_pct: Number(x.min_pct) } : {}),
          slots: slot ? slots : [...slots, newSlot],
        });
      } else {
        if (!x.name?.trim()) { toast("Ponle nombre al ramo", true); return; }
        await api("POST", `/semesters/${full.id}/courses`, { name: x.name.trim(), kind: x.kind, min_pct: Number(x.min_pct), slots: [newSlot] });
      }
      closeDialog(); render();
    };
    const del = $("[data-del-slot]", d);
    if (del) del.onclick = async () => {
      if (course.slots.length === 1) await api("DELETE", `/courses/${course.id}`);
      else await api("PATCH", `/courses/${course.id}`, { slots: slotsBody(course.slots).filter((s) => s.id !== slot.id) });
      closeDialog(); render();
    };
    const delC = $("[data-del-course]", d);
    if (delC) delC.onclick = async () => {
      if (!delC.dataset.sure) { delC.dataset.sure = 1; delC.textContent = "¿Seguro? Se borran también sus faltas. Toca de nuevo."; return; }
      await api("DELETE", `/courses/${course.id}`); closeDialog(); render();
    };
  });
}

// ---------- semestre ----------
async function semestre(v) {
  const list = await api("GET", "/semesters");
  const act = list.find((s) => s.active);
  const full = act && (await api("GET", `/semesters/${act.id}`));
  const countryOpts = Object.entries(COUNTRIES).map(([k, n]) => `<option value="${k}">${n}</option>`).join("");
  const newForm = `
    <form data-new class="grid gap-3 sm:grid-cols-2">
      <label class="field sm:col-span-2">Calendario<select class="input" name="preset"><option value="">Otro (lo ingreso a mano)</option>${CALENDARS.map((c, i) => `<option value="${i}">${esc(c.label)}</option>`).join("")}</select></label>
      <label class="field sm:col-span-2">Nombre del semestre<input class="input" name="name" required maxlength="60" placeholder="Ej: 2026-2"></label>
      <label class="field">Inicio<input class="input" name="start_date" type="date" required></label>
      <label class="field">Término<input class="input" name="end_date" type="date" required></label>
      <label class="field sm:col-span-2">País (para cargar feriados)<select class="input" name="country_code">${countryOpts}</select></label>
      <button class="btn-primary sm:col-span-2">Crear semestre</button>
    </form>`;
  v.innerHTML = act ? `
    <h1 class="h1">Semestre</h1>
    <section class="card mt-4">
      <h2 class="h2">${esc(act.name)}</h2>
      <form data-edit class="mt-3 grid grid-cols-2 gap-3">
        <label class="field col-span-2">Nombre<input class="input" name="name" required value="${esc(act.name)}"></label>
        <label class="field">Primer día de clases<input class="input" name="start_date" type="date" required value="${act.start_date}"></label>
        <label class="field">Último día de clases<input class="input" name="end_date" type="date" required value="${act.end_date}"></label>
        <button class="btn col-span-2">Guardar cambios</button>
      </form>
    </section>
    <section class="card mt-4">
      <h2 class="h2">Días sin clases</h2>
      <p class="muted">Feriados y recesos: no cuentan como clase ni como falta.</p>
      <ul class="mt-3 divide-y divide-slate-100">${full.no_class_days.map((d) => `
        <li class="flex items-center justify-between py-2 text-sm"><span><b>${shortDate(d.date)}</b> · ${esc(d.reason) || "Sin clases"}</span>
        <button data-del-off="${d.id}" class="btn h-8 w-8 !p-0" aria-label="Quitar ${shortDate(d.date)}">&#10005;</button></li>`).join("") || `<li class="py-2 text-sm text-slate-400">Ninguno todavía</li>`}
      </ul>
      <form data-off class="mt-3 grid grid-cols-2 gap-2">
        <label class="field">Desde<input class="input" name="from" type="date" required min="${act.start_date}" max="${act.end_date}"></label>
        <label class="field">Hasta (opcional)<input class="input" name="to" type="date" min="${act.start_date}" max="${act.end_date}"></label>
        <label class="field col-span-2">Motivo<input class="input" name="reason" maxlength="100" placeholder="Ej: Receso Fiestas Patrias"></label>
        <button class="btn-primary col-span-2">Agregar días sin clases</button>
      </form>
    </section>
    ${list.length > 1 ? `<section class="card mt-4"><h2 class="h2">Otros semestres</h2><ul class="mt-2 divide-y divide-slate-100">${list.filter((s) => !s.active).map((s) => `
      <li class="flex items-center justify-between gap-2 py-2 text-sm"><span>${esc(s.name)}</span><span class="flex gap-2">
      <button data-activate="${s.id}" class="btn">Activar</button><button data-del-sem="${s.id}" class="btn-danger">Eliminar</button></span></li>`).join("")}</ul></section>` : ""}
    <details class="card mt-4"><summary class="cursor-pointer font-semibold">Nuevo semestre</summary><div class="mt-3">${newForm}</div></details>` : `
    <h1 class="h1">Crea tu semestre</h1>
    <p class="muted">Con las fechas y el país calculamos cuántas clases tendrás y cargamos los feriados.</p>
    <section class="card mt-4">${newForm}</section>`;

  const nf = $("[data-new]", v);
  nf.preset.onchange = () => {
    const c = CALENDARS[nf.preset.value];
    if (c) Object.entries({ name: c.name, start_date: c.start, end_date: c.end, country_code: c.country }).forEach(([k, val]) => (nf.elements[k].value = val));
  };
  nf.onsubmit = async (e) => {
    e.preventDefault();
    const { preset, ...body } = formData(nf);
    const cal = CALENDARS[preset];
    const s = await api("POST", "/semesters", body);
    for (const [date, reason] of cal?.off || []) {
      await api("POST", `/semesters/${s.id}/no-class-days`, { date, reason }, { quiet: true }).catch(() => {}); // 409 = ya venía como feriado
    }
    const ok = cal || s.holidays_loaded;
    toast(ok ? "Semestre creado con feriados y recesos" : "Semestre creado. No pudimos cargar los feriados: agrégalos a mano.", !ok);
    location.hash = "#horario";
  };
  const edit = $("[data-edit]", v);
  if (edit) edit.onsubmit = async (e) => { e.preventDefault(); await api("PATCH", `/semesters/${act.id}`, formData(e.target)); toast("Guardado"); render(); };
  const off = $("[data-off]", v);
  if (off) off.onsubmit = async (e) => {
    e.preventDefault();
    const { from, to, reason } = formData(e.target);
    const end = to && to > from ? to : from;
    let added = 0;
    for (let d = parse(from); iso(d) <= end; d.setDate(d.getDate() + 1)) {
      if (d.getDay() === 0) continue; // domingo nunca tiene clases
      try { await api("POST", `/semesters/${act.id}/no-class-days`, { date: iso(d), reason }, { quiet: true }); added++; } catch (err) { if (err.status !== 409) { toast(err.message, true); break; } }
    }
    toast(added === 1 ? "Día agregado" : `${added} días agregados`);
    render();
  };
  $$("[data-del-off]", v).forEach((b) => (b.onclick = async () => { await api("DELETE", `/no-class-days/${b.dataset.delOff}`); render(); }));
  $$("[data-activate]", v).forEach((b) => (b.onclick = async () => { await api("PATCH", `/semesters/${b.dataset.activate}`, { active: true }); render(); }));
  $$("[data-del-sem]", v).forEach((b) => (b.onclick = async () => {
    if (!b.dataset.sure) { b.dataset.sure = 1; b.textContent = "¿Seguro?"; return; }
    await api("DELETE", `/semesters/${b.dataset.delSem}`); render();
  }));
}

// ---------- perfil ----------
const AV = { sm: "h-7 w-7 text-xs", md: "h-10 w-10 text-base", lg: "h-24 w-24 text-3xl ring-4 ring-white" };
const avatar = (u, size = "md") => u.avatar_url
  ? `<img src="${esc(u.avatar_url)}" alt="" class="${AV[size]} shrink-0 rounded-full bg-white object-cover">`
  : `<span class="grid ${AV[size]} shrink-0 place-items-center rounded-full bg-indigo-100 font-bold text-indigo-700">${esc(u.display_name[0]?.toUpperCase())}</span>`;
const BANNERS = ["#713dff", "#0ea5e9", "#16a34a", "#f59e0b", "#ef4444", "#db2777", "#7c3aed", "#334155"];

const profileCardHtml = (p) => `
  <div data-card>
    <div class="h-20" style="background:${esc(p.banner_color)}"></div>
    <div class="px-4 pb-4">
      <div class="-mt-12">${avatar(p, "lg")}</div>
      <h2 class="mt-2 text-xl font-bold leading-tight">${esc(p.display_name)}</h2>
      <p class="text-sm text-slate-500">@${esc(p.username)}</p>
      ${p.status ? `<p class="mt-2 inline-block rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-700">💬 ${esc(p.status)}</p>` : ""}
      ${p.career || p.year ? `<p class="mt-2 text-sm">🎓 ${esc([p.career, p.year && `${p.year}º año`].filter(Boolean).join(" · "))}</p>` : ""}
      ${p.bio ? `<p class="mt-2 whitespace-pre-line break-words text-sm">${esc(p.bio)}</p>` : ""}
      <p class="mt-3 text-xs text-slate-500"><b>${p.friends}</b> amigo${p.friends === 1 ? "" : "s"}${p.mutual ? ` · <b>${p.mutual}</b> en común` : ""}</p>
      ${p.badges.length ? `<div class="mt-3 flex flex-wrap gap-1.5">${p.badges.map((b) => `<span title="${esc(b.desc)}" class="rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-700">${b.emoji} ${esc(b.label)}</span>`).join("")}</div>` : ""}
    </div>
  </div>`;

async function profileCard(id) {
  const p = await api("GET", `/users/${id}/profile?today=${today()}`);
  const action = id === ME.id ? `<a href="#perfil" class="btn-primary">Editar perfil</a>`
    : p.is_friend ? `<button data-fcal class="btn-primary">Ver días</button>` : `<button data-fadd class="btn-primary">Agregar</button>`;
  openDialog(`<div class="relative">${profileCardHtml(p)}
    <button data-close class="btn absolute right-3 top-3 h-9 w-9 !p-0" aria-label="Cerrar">&#10005;</button>
    <div class="grid px-4 pb-4">${action}</div></div>`, (d) => {
    const cal = $("[data-fcal]", d), add = $("[data-fadd]", d);
    if (cal) cal.onclick = () => friendCalendar(p);
    if (add) add.onclick = async () => {
      const r = await api("POST", "/friends", { username: p.username });
      toast(r.status === "accepted" ? "¡Ahora son amigos!" : "Solicitud enviada");
      closeDialog(); render();
    };
  });
}

// Recorta al centro y achica a 256px (los GIF se suben tal cual para no perder la animación)
async function squareAvatar(file) {
  if (file.type === "image/gif") return file;
  try {
    const bmp = await createImageBitmap(file);
    const side = Math.min(bmp.width, bmp.height), out = Math.min(256, side);
    const c = Object.assign(document.createElement("canvas"), { width: out, height: out });
    c.getContext("2d").drawImage(bmp, (bmp.width - side) / 2, (bmp.height - side) / 2, side, side, 0, 0, out, out);
    return (await new Promise((r) => c.toBlob(r, "image/webp", 0.85))) || file;
  } catch { return file; } // el servidor valida el formato igual
}

async function perfil(v) {
  const [p, pstate] = await Promise.all([api("GET", `/users/${ME.id}/profile?today=${today()}`), pushState()]);
  const hint = (next, days) => `<small class="mt-1 block text-xs font-normal text-slate-400">${next ? `Podrás cambiarlo el ${shortDate(next.slice(0, 10))}` : `Se puede cambiar cada ${days} días`}</small>`;
  v.innerHTML = `
    <h1 class="h1">Tu perfil</h1>
    <section class="card mt-4 overflow-hidden !p-0">${profileCardHtml(p)}</section>
    <section class="card mt-4 flex flex-wrap items-center gap-3">
      <label class="btn-primary cursor-pointer">Cambiar foto<input data-avatar type="file" accept="image/png,image/jpeg,image/webp,image/gif" class="sr-only" aria-label="Cambiar foto"></label>
      ${ME.avatar_url ? `<button data-noavatar class="btn">Quitar foto</button>` : ""}
      <span class="muted">PNG, JPG, WEBP o GIF animado, hasta 2 MB.</span>
    </section>
    <form data-profile class="card mt-4 grid grid-cols-2 gap-3">
      <label class="field col-span-2">Nombre público<input class="input" name="display_name" required maxlength="60" value="${esc(ME.display_name)}" ${ME.display_name_next_change ? "disabled" : ""}>${hint(ME.display_name_next_change, 14)}</label>
      <label class="field col-span-2">Usuario (@)<input class="input" name="username" required pattern="[a-z0-9_.]{3,30}" autocapitalize="none" value="${esc(ME.username)}" ${ME.username_next_change ? "disabled" : ""}>${hint(ME.username_next_change, 30)}</label>
      <label class="field col-span-2">Estado<input class="input" name="status" maxlength="60" value="${esc(ME.status)}" placeholder="Ej: Sobreviviendo a certámenes"></label>
      <label class="field">Carrera<input class="input" name="career" maxlength="60" value="${esc(ME.career)}" placeholder="Ej: Ing. Civil Industrial"></label>
      <label class="field">Año<select class="input" name="year"><option value="">—</option>${[1, 2, 3, 4, 5, 6, 7].map((y) => `<option value="${y}" ${ME.year === y ? "selected" : ""}>${y}º año</option>`).join("")}</select></label>
      <label class="field col-span-2">Descripción<textarea class="input" name="bio" rows="3" maxlength="160">${esc(ME.bio)}</textarea></label>
      <fieldset class="col-span-2"><legend class="field">Color del banner</legend><div class="mt-2 flex flex-wrap gap-3">${BANNERS.map((c) => `
        <input type="radio" name="banner_color" value="${c}" aria-label="Color ${c}" ${ME.banner_color === c ? "checked" : ""} class="h-8 w-8 cursor-pointer appearance-none rounded-full ring-slate-900 ring-offset-2 checked:ring-2" style="background:${c}">`).join("")}</div></fieldset>
      <button class="btn-primary col-span-2">Guardar perfil</button>
    </form>
    <section class="card mt-4"><h2 class="h2">🔔 Notificaciones</h2><div class="mt-2">${PUSH_CARD[pstate]}</div></section>
    ${themeCard()}
    <a href="#semestre" class="btn mt-4 w-full">Semestre, fechas y feriados</a>
    <button data-logout class="mt-6 w-full text-center text-sm text-slate-500">Cerrar sesión</button>`;
  $("[data-profile]", v).onsubmit = async (e) => {
    e.preventDefault();
    const x = formData(e.target);
    ME = await api("PATCH", "/me", { ...x, year: x.year ? Number(x.year) : null });
    toast("Perfil guardado");
    render();
  };
  $("[data-avatar]", v).onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    ME = await api("PUT", "/me/avatar", await squareAvatar(f));
    toast("Foto actualizada");
    render();
  };
  const del = $("[data-noavatar]", v);
  if (del) del.onclick = async () => { await api("DELETE", "/me/avatar"); ME = await api("GET", "/me"); render(); };
  $("[data-logout]", v).onclick = logout;
  bindPush(v);
  bindTheme(v);
}

// ---------- amigos ----------
const person = (u, actions, extra = "") => `
  <li class="flex items-center justify-between gap-2 py-3">
    <button data-profile="${u.id}" class="flex items-center gap-3 text-left">${avatar(u)}
    <div><div class="font-medium leading-tight">${esc(u.display_name)}</div><div class="text-xs text-slate-500">@${esc(u.username)}</div>${extra ? `<div class="text-xs text-indigo-600">${extra}</div>` : ""}</div></button>
    <div class="flex gap-2">${actions}</div></li>`;

async function amigos(v) {
  const [f, sug] = await Promise.all([api("GET", "/friends"), api("GET", "/friends/suggestions")]);
  const common = (n) => (n ? `${n} amigo${n > 1 ? "s" : ""} en común` : "Nuevo en Faltapp");
  v.innerHTML = `
    <h1 class="h1">Amigos</h1>
    <p class="muted">Tu usuario es <b>@${esc(ME.username)}</b>. Compártelo para que te agreguen.</p>
    <form data-add class="mt-4 flex gap-2">
      <input class="input !mt-0" name="username" required placeholder="Usuario de tu amigo" aria-label="Usuario de tu amigo" autocapitalize="none">
      <button class="btn-primary shrink-0">Agregar</button>
    </form>
    ${f.incoming.length ? `<section class="card mt-4"><h2 class="h2">Solicitudes</h2><ul class="divide-y divide-slate-100">${f.incoming.map((u) => person(u, `<button data-accept="${u.id}" class="btn-primary">Aceptar</button><button data-remove="${u.id}" class="btn">Rechazar</button>`)).join("")}</ul></section>` : ""}
    ${sug.length ? `<section class="card mt-4"><h2 class="h2">Personas que quizás conozcas</h2><ul class="divide-y divide-slate-100">${sug.map((u) => person(u, `<button data-suggest="${esc(u.username)}" class="btn-primary">Agregar</button>`, common(u.mutual))).join("")}</ul></section>` : ""}
    <section class="card mt-4"><h2 class="h2">Tus amigos</h2>
      <ul class="divide-y divide-slate-100">${f.friends.map((u) => person(u, `<button data-cal="${u.id}" class="btn">Ver días</button>`)).join("") || `<li class="py-3 text-sm text-slate-400">Todavía no agregas a nadie.</li>`}</ul>
    </section>
    ${f.outgoing.length ? `<section class="card mt-4"><h2 class="h2">Enviadas</h2><ul class="divide-y divide-slate-100">${f.outgoing.map((u) => person(u, `<button data-remove="${u.id}" class="btn">Cancelar</button>`)).join("")}</ul></section>` : ""}`;
  $("[data-add]", v).onsubmit = async (e) => {
    e.preventDefault();
    const r = await api("POST", "/friends", formData(e.target));
    toast(r.status === "accepted" ? "¡Ahora son amigos!" : "Solicitud enviada");
    render();
  };
  $$("[data-suggest]", v).forEach((b) => (b.onclick = async () => {
    const r = await api("POST", "/friends", { username: b.dataset.suggest });
    toast(r.status === "accepted" ? "¡Ahora son amigos!" : "Solicitud enviada");
    render();
  }));
  $$("[data-accept]", v).forEach((b) => (b.onclick = async () => { await api("POST", `/friends/${b.dataset.accept}/accept`); render(); }));
  $$("[data-remove]", v).forEach((b) => (b.onclick = async () => { await api("DELETE", `/friends/${b.dataset.remove}`); render(); }));
  $$("[data-cal]", v).forEach((b) => (b.onclick = () => friendCalendar(f.friends.find((u) => u.id === Number(b.dataset.cal)))));
  $$("[data-profile]", v).forEach((b) => (b.onclick = () => profileCard(Number(b.dataset.profile))));
}

async function friendCalendar(u) {
  const colors = await api("GET", `/friends/${u.id}/calendar?today=${today()}`);
  const days = Object.keys(colors).sort();
  openDialog(`
    <div class="p-5">
      <div class="flex items-start justify-between"><h2 class="h2">Días de ${esc(u.display_name)}</h2><button data-close class="btn h-9 w-9 !p-0" aria-label="Cerrar">&#10005;</button></div>
      ${days.length ? `<div id="fcal" class="mt-3"></div>${legend()}` : `<p class="muted mt-3">Todavía no crea su semestre.</p>`}
      <a href="#propuestas/${u.id}" class="btn-primary mt-4 w-full">Proponer un día para faltar</a>
    </div>`, (d) => {
    if (days.length) calendar($("#fcal", d), "f" + u.id, colors, { start: days[0], end: days.at(-1) }, null);
    $("a", d).addEventListener("click", closeDialog);
  });
}

// ---------- propuestas ----------
const STATUS = { accepted: "Se suma", rejected: "No se suma", pending: "Pendiente" };
async function propuestas(v, arg) {
  const [props, f] = await Promise.all([api("GET", `/proposals?today=${today()}`), api("GET", "/friends")]);
  v.innerHTML = `
    <h1 class="h1">Propuestas</h1>
    <section class="mt-4 space-y-3">${props.map((p) => {
      const mine = p.members.find((m) => m.id === ME.id);
      return `
      <article class="card">
        <div class="flex items-start justify-between gap-2">
          <div><h3 class="font-semibold">${longDate(p.date)}</h3><p class="text-xs text-slate-500">Propuesta de @${esc(p.creator.username)}${p.note ? ` · “${esc(p.note)}”` : ""}</p></div>
          ${p.date < today() ? `<span class="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">Pasada</span>` : ""}
        </div>
        <ul class="mt-3 space-y-1.5">${p.members.map((m) => `
          <li class="flex items-center justify-between text-sm"><span class="flex items-center gap-2"><span class="h-3 w-3 rounded-full ${COLOR[m.color].dot}" title="${COLOR[m.color].label}"></span>${esc(m.display_name)}</span>
          <span class="text-xs text-slate-500">${COLOR[m.color].label} · ${STATUS[m.status]}</span></li>`).join("")}
        </ul>
        ${mine?.status === "pending" ? `<div class="mt-3 grid grid-cols-2 gap-2"><button data-respond="${p.id}" data-accept="1" class="btn-primary">Me sumo</button><button data-respond="${p.id}" class="btn">No puedo</button></div>` : ""}
      </article>`;
    }).join("") || `<p class="muted text-center">No hay propuestas todavía.</p>`}</section>
    <section class="card mt-4">
      <h2 class="h2">Proponer faltar</h2>
      ${f.friends.length ? `
      <form data-new class="mt-3 space-y-3">
        <div class="grid grid-cols-2 gap-3">
          <label class="field">Fecha<input class="input" name="date" type="date" required min="${today()}"></label>
          <label class="field">Nota<input class="input" name="note" maxlength="200" placeholder="¿Qué harán?"></label>
        </div>
        <fieldset><legend class="field">Invitar</legend><div class="mt-1 flex flex-wrap gap-2">${f.friends.map((u) => `
          <label class="flex items-center gap-2 rounded-full border border-slate-300 px-3 py-1.5 text-sm has-[:checked]:border-indigo-600 has-[:checked]:bg-indigo-50">
          <input type="checkbox" name="u" value="${u.id}" ${String(u.id) === arg ? "checked" : ""} class="accent-indigo-600">${esc(u.display_name)}</label>`).join("")}</div></fieldset>
        <button class="btn-primary w-full">Enviar propuesta</button>
      </form>` : `<p class="muted mt-2">Primero <a href="#amigos" class="font-medium text-indigo-600">agrega amigos</a>.</p>`}
    </section>`;
  const form = $("[data-new]", v);
  if (form) form.onsubmit = async (e) => {
    e.preventDefault();
    const user_ids = $$("input[name=u]:checked", form).map((i) => Number(i.value));
    if (!user_ids.length) { toast("Elige al menos un amigo", true); return; }
    const r = await api("POST", `/proposals?today=${today()}`, { date: form.date.value, note: form.note.value, user_ids });
    r.warnings.forEach((m) => toast("⚠ " + m));
    toast("Propuesta enviada");
    location.hash = "#propuestas";
    render();
  };
  $$("[data-respond]", v).forEach((b) => (b.onclick = async () => {
    const r = await api("POST", `/proposals/${b.dataset.respond}/respond`, { accept: !!b.dataset.accept });
    r.warnings.forEach((m) => toast("⚠ " + m));
    render();
  }));
}

async function refreshBadge() {
  try {
    const props = await api("GET", `/proposals?today=${today()}`, null, { quiet: true });
    const n = props.filter((p) => p.members.some((m) => m.id === ME.id && m.status === "pending")).length;
    $("#badge").textContent = n;
    $("#badge").classList.toggle("hidden", !n);
  } catch { /* no es crítico */ }
}

// ---------- agenda ----------
async function agenda(v, arg) {
  const sem = await activeSemester();
  if (!sem) { location.hash = "#semestre"; return; }
  const full = await api("GET", `/semesters/${sem.id}`);
  const events = (await api("GET", `/semesters/${sem.id}/events`)).sort((a, b) => (a.date + (a.time || "")).localeCompare(b.date + (b.time || "")));
  const courseName = (id) => full.courses.find((c) => c.id === id)?.name;
  const item = (e) => `
    <li class="flex items-center gap-3 py-3">
      <div class="w-12 shrink-0 text-center"><div class="text-lg font-bold leading-none">${parse(e.date).getDate()}</div><div class="text-[11px] uppercase text-slate-500">${MONTHS[parse(e.date).getMonth()].slice(0, 3)}</div></div>
      <div class="flex-1"><div class="font-medium leading-tight">${esc(e.title)}</div>
      <div class="text-xs text-slate-500"><span class="${e.kind === "prueba" ? "font-semibold text-red-600" : ""}">${KINDS[e.kind]}</span>${e.course_id ? ` · ${esc(courseName(e.course_id))}` : ""}${e.time ? ` · ${e.time}` : ""}</div></div>
      <button data-del="${e.id}" class="btn h-8 w-8 !p-0" aria-label="Borrar ${esc(e.title)}">&#10005;</button></li>`;
  const upcoming = events.filter((e) => e.date >= today()), past = events.filter((e) => e.date < today());
  v.innerHTML = `
    <h1 class="h1">Agenda</h1>
    <section class="card mt-4">
      <form class="grid grid-cols-2 gap-3">
        <label class="field">Tipo<select class="input" name="kind">${Object.entries(KINDS).map(([k, n]) => `<option value="${k}">${n}</option>`).join("")}</select></label>
        <label class="field">Ramo (opcional)<select class="input" name="course_id"><option value="">—</option>${full.courses.map((c) => `<option value="${c.id}">${esc(c.name)} (${c.kind === "L" ? "Lab" : "Teoría"})</option>`).join("")}</select></label>
        <label class="field col-span-2">Título<input class="input" name="title" required maxlength="120" placeholder="Ej: Certamen 2"></label>
        <label class="field">Fecha<input class="input" name="date" type="date" required value="${/^\d{4}-\d{2}-\d{2}$/.test(arg || "") ? arg : ""}"></label>
        <label class="field">Hora (opcional)<input class="input" name="time" type="time"></label>
        <button class="btn-primary col-span-2">Agregar</button>
      </form>
    </section>
    <section class="card mt-4"><h2 class="h2">Próximos</h2><ul class="divide-y divide-slate-100">${upcoming.map(item).join("") || `<li class="py-3 text-sm text-slate-400">Nada por ahora.</li>`}</ul></section>
    ${past.length ? `<details class="card mt-4"><summary class="cursor-pointer font-semibold">Pasados (${past.length})</summary><ul class="divide-y divide-slate-100 opacity-70">${past.reverse().map(item).join("")}</ul></details>` : ""}`;
  $("form", v).onsubmit = async (e) => {
    e.preventDefault();
    const x = formData(e.target);
    await api("POST", `/semesters/${sem.id}/events`, { ...x, course_id: x.course_id ? Number(x.course_id) : null, time: x.time || null });
    toast("Agregado");
    location.hash = "#agenda";
    render();
  };
  $$("[data-del]", v).forEach((b) => (b.onclick = async () => { await api("DELETE", `/events/${b.dataset.del}`); render(); }));
}

// ---------- importar desde Phoenix (ULS) ----------
const PHOENIX = "https://phoenix.cic.userena.cl/modulos/bitacora/alumnos/informacion/fx_informacion_asistencia.php";

// Corre DENTRO de Phoenix como marcador: lee las tablas (fecha + ✔/✖ por ramo y sección) y abre Faltapp
// con los datos en el # (no viajan al servidor hasta confirmar). Sin comentarios // adentro: va en una URL.
function phoenixGrab(origin) {
  const rows = [];
  let name = "", dates = [];
  for (const tr of document.querySelectorAll("tr")) {
    const tds = [...tr.children], first = tds[0]?.textContent.trim() || "";
    if (tr.classList.contains("bg-primary")) name = first;
    else if (tr.classList.contains("bg-secondary")) dates = tds.map((td) => td.textContent.trim().replace(/^(\d\d)-(\d\d)-(\d{4})[\s\S]*/, "$3-$2-$1"));
    else if (/^\[[TL]-\d+\]$/.test(first)) {
      const pick = (sel) => dates.filter((d, i) => /^\d{4}-/.test(d) && tds[i]?.querySelector(sel));
      rows.push({ name, section: first, absent: pick(".fa-close,.fa-times"), present: pick(".fa-check") });
    }
  }
  if (!rows.length) return alert("Abre Asignaturas → Registro de Asistencia en Phoenix y vuelve a tocar el marcador.");
  const url = origin + "/#importar/" + encodeURIComponent(JSON.stringify(rows));
  open(url) || (location.href = url);
}

// "Progr. Avanzada" ≈ "Programación Avanzada": proporción de palabras donde una es el inicio de la otra
const words = (s) => String(s).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().match(/[a-z0-9]+/g) || [];
function similar(a, b) {
  const x = words(a), y = words(b);
  return x.filter((w) => y.some((z) => z.startsWith(w) || w.startsWith(z))).length / Math.max(x.length, y.length, 1);
}

const DEVICE = /iPhone|iPad|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1) ? "iphone"
  : /Android/.test(navigator.userAgent) ? "android" : "pc";
const step = (n, html) => `<li class="flex gap-3"><span class="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-indigo-600 text-sm font-bold text-white">${n}</span><div class="pt-0.5 text-sm leading-relaxed">${html}</div></li>`;
const steps = (title, list) => `<h3 class="mt-5 font-semibold text-slate-900">${title}</h3><ol class="mt-3 space-y-4">${list.map((h, i) => step(i + 1, h)).join("")}</ol>`;
const COPY = `<button data-copy class="btn-primary mt-2">Copiar código</button>`;
const GO_PHOENIX = `<a href="${PHOENIX}" target="_blank" rel="noopener" class="btn mt-2">Abrir Phoenix</a>`;
const IN_PHOENIX = "Entra a Phoenix con tu cuenta y ve a <b>Asignaturas → Registro de Asistencia</b>.";
const CONFIRM = "Se abre Faltapp con tus faltas. Revisa que cada ramo esté bien elegido y toca <b>Importar</b>. ¡Listo!";

function importHelp(v) {
  const bm = "javascript:" + encodeURIComponent(`(${phoenixGrab})(${JSON.stringify(location.origin)})`);
  const guides = {
    pc: steps("Primera vez: guarda el botón", [
      "Muestra la barra de marcadores de tu navegador: presiona <b>Ctrl + Shift + B</b> (en Mac: <b>Cmd + Shift + B</b>). Aparece una barra debajo de la dirección.",
      `Mantén apretado este botón con el mouse, arrástralo hasta esa barra y suéltalo ahí:<br><a data-bm href="${esc(bm)}" class="btn-primary mt-2">⤓ Importar a Faltapp</a>
      <p class="mt-3 text-xs text-slate-500">¿No te deja arrastrarlo? Haz clic derecho en la barra → <b>Agregar página</b> (o <b>Agregar marcador</b>). Como nombre escribe <b>Faltapp</b> y en la dirección (URL) pega el código que copias aquí:</p>${COPY}`,
    ]) + steps("Cada vez que quieras actualizar tus faltas", [
      `${IN_PHOENIX}<br>${GO_PHOENIX}`,
      "Haz clic en <b>Importar a Faltapp</b> en la barra de marcadores.",
      CONFIRM,
    ]),
    android: steps("Primera vez: guarda el botón (en Chrome)", [
      `Toca este botón para copiar el código:<br>${COPY}`,
      "En Chrome toca los <b>tres puntos ⋮</b> (arriba a la derecha) y luego la <b>estrella ☆</b>. Abajo aparece el aviso “Se agregó a favoritos”: toca <b>Editar</b>.<br><span class=\"text-xs text-slate-500\">Si el aviso se fue: ⋮ → Favoritos → toca ⋮ al lado del favorito → Editar.</span>",
      "En <b>Nombre</b> escribe <b>Faltapp</b>. En <b>URL</b> borra todo, mantén el dedo presionado y toca <b>Pegar</b>. Vuelve atrás con la flecha ←: se guarda solo.",
    ]) + steps("Cada vez que quieras actualizar tus faltas", [
      `En Chrome, ${IN_PHOENIX.charAt(0).toLowerCase() + IN_PHOENIX.slice(1)}<br>${GO_PHOENIX}`,
      "Toca la barra de direcciones (donde va la página web), escribe <b>Faltapp</b> y toca el favorito con la estrella ☆ que aparece en la lista.<br><span class=\"text-xs text-slate-500\">Ojo: tiene que ser escribiéndolo en la barra. Si lo abres desde la lista de favoritos no funciona.</span>",
      CONFIRM,
    ]),
    iphone: steps("Primera vez: guarda el botón (en Safari)", [
      `Toca este botón para copiar el código:<br>${COPY}`,
      "Toca el botón <b>Compartir</b> (el cuadrado con una flecha hacia arriba) → <b>Agregar marcador</b> → <b>Guardar</b>.",
      "Toca el ícono de <b>marcadores</b> (el libro abierto) → <b>Editar</b> (abajo a la derecha) → toca el marcador que acabas de guardar.",
      "Cambia el nombre por <b>Faltapp</b>. Toca la dirección de abajo, bórrala completa, mantén el dedo presionado y toca <b>Pegar</b>. Toca <b>OK</b>.",
    ]) + steps("Cada vez que quieras actualizar tus faltas", [
      `En Safari, ${IN_PHOENIX.charAt(0).toLowerCase() + IN_PHOENIX.slice(1)}<br>${GO_PHOENIX}`,
      "Toca la barra de direcciones (donde va la página web), escribe <b>Faltapp</b> y toca el marcador que aparece en la lista.",
      CONFIRM,
    ]),
  };
  const tabs = { pc: "PC", android: "Android", iphone: "iPhone" };
  v.innerHTML = `
    <h1 class="h1">Importar desde Phoenix</h1>
    <p class="muted">Trae tus faltas del registro oficial de la ULS sin anotarlas una por una. La primera vez guardas un botón en tu navegador (toma 1 minuto) y después basta con tocarlo estando en Phoenix.</p>
    <section class="card mt-4">
      <p class="text-sm font-medium text-slate-600">¿Desde dónde lo vas a usar?</p>
      <div class="mt-2 grid grid-cols-3 gap-2">${Object.entries(tabs).map(([k, n]) => `
        <button data-dev="${k}" aria-pressed="${k === DEVICE}" class="btn aria-pressed:border-indigo-600 aria-pressed:bg-indigo-50 aria-pressed:text-indigo-700">${n}</button>`).join("")}</div>
      ${Object.entries(guides).map(([k, html]) => `<div data-guide="${k}" class="${k === DEVICE ? "" : "hidden"}">${html}</div>`).join("")}
    </section>
    <details class="card mt-4">
      <summary class="cursor-pointer font-semibold">¿No funciona?</summary>
      <ul class="mt-3 list-disc space-y-2 pl-5 text-sm">
        <li>Tócalo estando en la página de <b>Registro de Asistencia</b> de Phoenix, con tu sesión iniciada.</li>
        <li>Si no pasa nada, el código no quedó pegado completo: repite el paso de pegar. Debe empezar con <b>javascript:</b></li>
        <li>En celular usa <b>Chrome</b> (Android) o <b>Safari</b> (iPhone). En otros navegadores puede no funcionar.</li>
        <li>Si Faltapp cambió de dirección, borra el botón y guárdalo de nuevo.</li>
      </ul>
      <label class="field mt-3">Código del botón (por si el botón Copiar no funciona)<textarea readonly rows="3" class="input font-mono text-xs">${esc(bm)}</textarea></label>
    </details>
    <p class="muted mt-4 text-center">¿Prefieres no hacerlo? En <a href="#inicio" class="font-medium text-indigo-600">Inicio</a> marcas tus faltas con un toque.</p>`;
  $$("[data-dev]", v).forEach((b) => (b.onclick = () => {
    $$("[data-dev]", v).forEach((x) => x.setAttribute("aria-pressed", x === b));
    $$("[data-guide]", v).forEach((g) => g.classList.toggle("hidden", g.dataset.guide !== b.dataset.dev));
  }));
  $("[data-bm]", v).onclick = (e) => { e.preventDefault(); toast("Arrástralo a la barra de marcadores: se usa estando en Phoenix"); };
  $$("[data-copy]", v).forEach((b) => (b.onclick = async () => {
    try { await navigator.clipboard.writeText(bm); toast("Código copiado ✓"); } catch {
      $("details", v).open = true; $("textarea", v).select(); toast("No se pudo copiar: mantén presionado el código de abajo y cópialo", true);
    }
  }));
}

async function importar(v, arg) {
  let rows = null;
  try { rows = arg && JSON.parse(decodeURIComponent(arg)).filter((r) => Array.isArray(r.absent) && Array.isArray(r.present)); } catch { toast("No pude leer los datos de Phoenix: vuelve a tocar el marcador", true); }
  if (!rows?.length) return importHelp(v);
  const sem = await activeSemester();
  if (!sem) { location.hash = "#semestre"; return; }
  const { courses } = await api("GET", `/semesters/${sem.id}`);
  const best = (r) => courses.filter((c) => c.kind === r.section[1]).map((c) => [similar(c.name, r.name), c]).sort((a, b) => b[0] - a[0]).find(([n]) => n > 0.5)?.[1];
  v.innerHTML = `
    <h1 class="h1">Importar desde Phoenix</h1>
    <p class="muted">Revisa a qué ramo corresponde cada uno. En los días que Phoenix ya registró, manda Phoenix.</p>
    <ul class="card mt-4 divide-y divide-slate-100 !py-0">${rows.map((r, i) => `
      <li class="py-3">
        <div class="font-medium leading-tight">${esc(r.name)} <span class="text-xs text-slate-500">${esc(r.section)}</span></div>
        <div class="text-xs ${r.absent.length ? "text-red-600" : "text-slate-500"}">${r.absent.length ? `Faltas: ${esc(r.absent.map(shortDate).join(", "))}` : "Sin faltas"} · ${r.present.length} asistencia${r.present.length === 1 ? "" : "s"}</div>
        <select class="input" data-row="${i}" aria-label="${esc(r.name)} ${esc(r.section)}"><option value="">No importar</option>${courses.map((c) => `
          <option value="${c.id}" ${best(r)?.id === c.id ? "selected" : ""}>${esc(c.name)} (${c.kind === "L" ? "Lab" : "Teoría"})</option>`).join("")}</select>
      </li>`).join("")}</ul>
    <button data-import class="btn-primary mt-4 w-full">Importar</button>`;
  $("[data-import]", v).onclick = async () => {
    const items = $$("select[data-row]", v).filter((s) => s.value).map((s) => ({ course_id: Number(s.value), absent: rows[s.dataset.row].absent, present: rows[s.dataset.row].present }));
    if (!items.length) { toast("Elige al menos un ramo", true); return; }
    const r = await api("POST", "/absences/import", { items });
    toast(`Listo: ${r.added} falta${r.added === 1 ? "" : "s"} nueva${r.added === 1 ? "" : "s"}${r.removed ? `, ${r.removed} corregida${r.removed === 1 ? "" : "s"}` : ""}`);
    if (r.makeups.length) toast(`Recuperaciones: ${r.makeups.map((x) => `${x.course} del ${shortDate(x.original)} al ${shortDate(x.date)}`).join(", ")}`);
    if (r.skipped.length) toast(`No calzan con tu horario: ${r.skipped.map((x) => `${x.course} ${shortDate(x.date)}`).join(", ")}`, true);
    location.hash = "#inicio";
  };
}

// ---------- notificaciones ----------
const PUSH_OK = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
const STANDALONE = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const b64ToBytes = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4)), (c) => c.charCodeAt(0));

// on | off | denied | ios (iPhone sin instalar: Apple solo permite avisos a apps agregadas al inicio) | no
async function pushState() {
  if (!PUSH_OK) return DEVICE === "iphone" && !STANDALONE ? "ios" : "no";
  if (Notification.permission === "denied") return "denied";
  const reg = await navigator.serviceWorker.getRegistration();
  return (await reg?.pushManager.getSubscription()) && Notification.permission === "granted" ? "on" : "off";
}

async function enablePush() {
  try {
    if ((await Notification.requestPermission()) !== "granted") { toast("Sin permiso no podemos avisarte. Puedes activarlas después en tu perfil.", true); return; }
    const reg = await navigator.serviceWorker.ready;
    const { key } = await api("GET", "/push/key");
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(key) });
    await api("POST", "/push/subscribe", sub.toJSON());
    await api("POST", "/push/test");
    toast("🔔 Notificaciones activadas");
  } catch (e) {
    console.warn(e);
    toast("No se pudieron activar en este navegador. Prueba con Chrome (o Safari en iPhone).", true);
  }
  render();
}

async function disablePush() {
  const sub = await (await navigator.serviceWorker.ready).pushManager.getSubscription();
  if (sub) {
    await api("DELETE", "/push/subscribe", { endpoint: sub.endpoint }, { quiet: true }).catch(() => {});
    await sub.unsubscribe();
  }
  toast("Notificaciones desactivadas en este dispositivo");
  render();
}

// Si el dispositivo ya tenía permiso, lo vuelve a asociar a la cuenta con la que se entró
let pushSynced = false;
async function syncPush() {
  if (pushSynced || !PUSH_OK || Notification.permission !== "granted") return;
  pushSynced = true;
  const sub = await (await navigator.serviceWorker.getRegistration())?.pushManager.getSubscription();
  if (sub) await api("POST", "/push/subscribe", sub.toJSON(), { quiet: true }).catch(() => {});
}

const PUSH_CARD = {
  on: `<p class="text-sm">✅ Activadas en este dispositivo.</p>
    <div class="mt-3 flex flex-wrap gap-2"><button data-push-test class="btn">Enviar una de prueba</button><button data-push-off class="btn">Desactivar</button></div>`,
  off: `<p class="muted">Te avisamos de pruebas, de cuando te quedan pocas faltas y de tus amigos, y cada tarde con clases te preguntamos si faltaste.</p>
    <button data-push-on class="btn-primary mt-3">Activar notificaciones</button>`,
  denied: `<p class="text-sm text-red-600">Las bloqueaste para Faltapp. Para activarlas: toca el candado 🔒 junto a la dirección → <b>Notificaciones</b> → <b>Permitir</b>, y recarga la página.</p>`,
  ios: `<p class="text-sm">En iPhone los avisos solo funcionan si agregas Faltapp a tu pantalla de inicio:</p>
    <ol class="mt-2 list-decimal space-y-1 pl-5 text-sm"><li>En Safari toca <b>Compartir</b> (el cuadrado con una flecha hacia arriba).</li>
    <li>Toca <b>Agregar a inicio</b> y luego <b>Agregar</b>.</li><li>Abre Faltapp desde el ícono nuevo, inicia sesión y vuelve aquí para activarlas.</li></ol>`,
  no: `<p class="muted">Este navegador no permite notificaciones. Prueba con Chrome (o Safari en iPhone).</p>`,
};
const bindPush = (v) => {
  $$("[data-push-on]", v).forEach((b) => (b.onclick = enablePush));
  const off = $("[data-push-off]", v), test = $("[data-push-test]", v);
  if (off) off.onclick = disablePush;
  if (test) test.onclick = async () => { await api("POST", "/push/test"); toast("Enviada: debería llegarte en unos segundos"); };
};

// ---------- apariencia ----------
// Automático sigue el modo claro/oscuro del dispositivo; Claro u Oscuro quedan guardados en este dispositivo
const THEMES = { auto: "Automático", light: "Claro", dark: "Oscuro" };
const DARK_OS = matchMedia("(prefers-color-scheme: dark)");
function applyTheme() {
  const t = store.get("theme");
  if (t) document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
  $('meta[name="theme-color"]').content = (t || (DARK_OS.matches ? "dark" : "light")) === "dark" ? "#0a0118" : "#f6f4fb";
}
DARK_OS.addEventListener("change", applyTheme);
applyTheme();
const themeCard = () => {
  const cur = store.get("theme") || "auto";
  return `
    <section class="card mt-4"><h2 class="h2">🌗 Apariencia</h2>
      <div class="mt-3 grid grid-cols-3 rounded-full border border-fg/10 bg-surface p-1 text-sm font-medium">${Object.entries(THEMES).map(([k, l]) => `
        <button data-theme-pick="${k}" aria-pressed="${cur === k}" class="rounded-full py-2 ${cur === k ? "bg-indigo-500 text-white" : ""}">${l}</button>`).join("")}</div>
      <p class="muted mt-2">Automático usa el modo claro u oscuro de tu dispositivo.</p>
    </section>`;
};
const bindTheme = (v) => $$("[data-theme-pick]", v).forEach((b) => (b.onclick = () => {
  const pick = () => {
    store.set("theme", b.dataset.themePick === "auto" ? null : b.dataset.themePick);
    applyTheme();
    $$("[data-theme-pick]", v).forEach((x) => {
      x.setAttribute("aria-pressed", x === b);
      x.classList.toggle("bg-indigo-500", x === b);
      x.classList.toggle("text-white", x === b);
    });
  };
  // cambio con fundido suave donde el navegador lo permite
  if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) document.startViewTransition(pick);
  else pick();
}));

// ---------- router ----------
const routes = { login, inicio, horario, semestre, perfil, importar, amigos, propuestas, agenda };
let shown = null; // pantalla que se ve ahora: solo se anima al cambiar de pantalla, no al refrescar la misma
async function render() {
  const [name, arg] = location.hash.slice(1).split("/");
  const route = routes[name] ? name : token ? "inicio" : "login";
  if (!token && route !== "login") { location.hash = "#login"; return; }
  if (token && route === "login") { location.hash = "#inicio"; return; }
  $("#nav").classList.toggle("hidden", route === "login");
  $$("#nav [data-route]").forEach((a) => a.classList.toggle("text-indigo-600", a.dataset.route === route));
  const v = $("#view"), changed = route !== shown;
  if (changed && shown) v.classList.add("leaving"); // la pantalla anterior se desenfoca mientras carga la nueva
  try {
    if (token && !ME) ME = await api("GET", "/me");
    $("#hdr").innerHTML = ME ? `<a href="#perfil" class="flex items-center gap-2 opacity-95">${avatar(ME, "sm")}@${esc(ME.username)}</a>` : "";
    await routes[route](v, arg);
    if (ME) { refreshBadge(); syncPush(); }
  } catch (e) {
    console.warn(e); // el error ya se mostró como toast
  }
  v.classList.remove("leaving");
  if (changed) {
    shown = route;
    scrollTo(0, 0);
    v.classList.remove("entering");
    void v.offsetWidth; // reinicia la animación
    v.classList.add("entering");
  }
}

addEventListener("hashchange", () => { closeDialog(); render(); });
render();
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
