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
  amarillo: { cls: "bg-yellow-400 text-slate-900", dot: "bg-yellow-400", label: "Justo en el límite" },
  rojo: { cls: "bg-red-500 text-white", dot: "bg-red-500", label: "No puedes faltar" },
  falta: { cls: "bg-slate-800 text-white", dot: "bg-slate-800", label: "Falta marcada" },
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
  el.className = `pointer-events-auto max-w-sm rounded-xl px-4 py-2 text-sm font-medium shadow-lg ${bad ? "bg-red-600 text-white" : "bg-slate-900 text-white"}`;
  el.textContent = msg;
  $("#toast").append(el);
  setTimeout(() => el.remove(), 3500);
}

async function api(method, path, body, { quiet = false } = {}) {
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
  token = null; ME = null; store.set("token", null);
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
    cells.push(c && c !== "gris" && onPick
      ? `<button data-date="${k}" title="${COLOR[c].label}" class="aspect-square rounded-lg text-sm font-semibold ${COLOR[c].cls}${ring}">${d}</button>`
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
  $("[data-month-prev]", el).onclick = () => { calMonths[key] = shiftMonth(m, -1); calendar(el, key, colors, range, onPick); };
  $("[data-month-next]", el).onclick = () => { calMonths[key] = shiftMonth(m, 1); calendar(el, key, colors, range, onPick); };
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
      <h1 class="h1 text-center">Falta con cabeza</h1>
      <p class="muted mt-1 text-center">Calcula cuántas clases puedes faltar y ponte de acuerdo con tus amigos.</p>
      <div class="mt-6 grid grid-cols-2 rounded-xl bg-slate-200 p-1 text-sm font-medium">
        <button data-mode="login" class="rounded-lg py-2 ${reg ? "" : "bg-white shadow"}">Entrar</button>
        <button data-mode="register" class="rounded-lg py-2 ${reg ? "bg-white shadow" : ""}">Crear cuenta</button>
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
    location.hash = "#inicio";
  };
}

// ---------- inicio ----------
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
      <p class="mt-1 text-xs text-slate-500">${c.total} clases · mínimo ${c.minimo} · faltaste ${c.reales}${c.planeadas ? ` · planeas ${c.planeadas}` : ""}</p>
    </article>`;
}

async function inicio(v) {
  const sem = await activeSemester();
  if (!sem) { location.hash = "#semestre"; return; }
  const s = await api("GET", `/semesters/${sem.id}/summary?today=${today()}`);
  const wd = Object.entries(s.weekdays);
  v.innerHTML = `
    <div class="flex items-end justify-between">
      <div><p class="muted">Semestre</p><h1 class="h1">${esc(sem.name)}</h1></div>
      <a href="#semestre" class="text-sm font-medium text-indigo-600">Fechas y feriados</a>
    </div>
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
  calendar($("#cal", v), "home", s.calendar, { start: s.semester.start_date, end: s.semester.end_date }, (d) => openDay(s, d), tests);
}

function openDay(s, day) {
  const w = weekdayOf(day);
  const slots = s.courses.flatMap((c) => c.slots.filter((x) => x.weekday === w).map((x) => ({ ...x, course: c })))
    .sort((a, b) => a.start_time.localeCompare(b.start_time));
  const marked = new Set(s.absences.filter((a) => a.date === day).map((a) => a.slot_id));
  const events = s.events.filter((e) => e.date === day);
  const past = day < today();
  openDialog(`
    <div class="p-5">
      <div class="flex items-start justify-between">
        <div><h2 class="h2">${longDate(day)}</h2><p class="muted">${COLOR[s.calendar[day]].label}${past ? "" : " · futura: queda como falta planeada"}</p></div>
        <button data-close class="btn h-9 w-9 !p-0" aria-label="Cerrar">&#10005;</button>
      </div>
      ${events.map((e) => `<div class="mt-3 rounded-xl ${e.kind === "prueba" ? "bg-red-50 text-red-800" : "bg-sky-50 text-sky-800"} px-3 py-2 text-sm"><b>${KINDS[e.kind]}</b> · ${esc(e.title)}${e.time ? ` · ${e.time}` : ""}</div>`).join("")}
      <p class="mt-4 text-sm font-medium text-slate-600">Marca las clases a las que ${past ? "faltaste" : "vas a faltar"}:</p>
      <ul class="mt-2 space-y-2">${slots.map((x) => `
        <li><label class="flex cursor-pointer items-center gap-3 rounded-xl border border-slate-200 p-3">
          <input type="checkbox" data-slot="${x.id}" ${marked.has(x.id) ? "checked" : ""} class="h-5 w-5 accent-indigo-600">
          <span class="flex-1"><span class="font-medium">${esc(x.course.name)}</span> <span class="text-xs text-slate-500">${x.course.kind === "L" ? "Lab" : "Teoría"}</span></span>
          <span class="text-xs text-slate-500">${x.start_time}–${x.end_time}</span></label></li>`).join("")}
      </ul>
      <div class="mt-4 grid grid-cols-2 gap-2">
        <button data-all class="btn-primary">Faltar todo el día</button>
        <button data-none class="btn">Quitar faltas</button>
      </div>
      <a href="#agenda/${day}" class="mt-4 block text-center text-sm font-medium text-indigo-600">+ Agregar prueba o evento este día</a>
    </div>`, (d) => {
    const warn = (r) => r?.warnings?.forEach((m) => toast("⚠ " + m));
    $$("[data-slot]", d).forEach((cb) => (cb.onchange = async () => {
      try {
        warn(await api(cb.checked ? "POST" : "DELETE", "/absences", { date: day, slot_ids: [Number(cb.dataset.slot)] }));
      } catch { cb.checked = !cb.checked; }
      render();
    }));
    $("[data-all]", d).onclick = async () => { warn(await api("POST", "/absences", { date: day })); closeDialog(); render(); };
    $("[data-none]", d).onclick = async () => { await api("DELETE", "/absences", { date: day }); closeDialog(); render(); };
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
          </button></li>`).join("") || `<li class="text-sm text-slate-400">Sin clases</li>`}
        </ul>
      </section>`).join("")}
    </div>`;
  $("[data-pdf]", v).onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const r = await api("POST", `/semesters/${full.id}/import-uls`, file);
    toast(r.created ? `${r.created} ramo${r.created > 1 ? "s" : ""} cargado${r.created > 1 ? "s" : ""}. Revisa el % mínimo de cada uno.` : "Esos ramos ya estaban cargados");
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
    <details class="card mt-4"><summary class="cursor-pointer font-semibold">Nuevo semestre</summary><div class="mt-3">${newForm}</div></details>
    <button data-logout class="mt-6 w-full text-center text-sm text-slate-500">Cerrar sesión</button>` : `
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
  const lo = $("[data-logout]", v);
  if (lo) lo.onclick = logout;
}

// ---------- amigos ----------
const person = (u, actions, extra = "") => `
  <li class="flex items-center justify-between gap-2 py-3">
    <div class="flex items-center gap-3"><span class="grid h-10 w-10 place-items-center rounded-full bg-indigo-100 font-bold text-indigo-700">${esc(u.display_name[0]?.toUpperCase())}</span>
    <div><div class="font-medium leading-tight">${esc(u.display_name)}</div><div class="text-xs text-slate-500">@${esc(u.username)}</div>${extra ? `<div class="text-xs text-indigo-600">${extra}</div>` : ""}</div></div>
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

// ---------- router ----------
const routes = { login, inicio, horario, semestre, amigos, propuestas, agenda };
async function render() {
  const [name, arg] = location.hash.slice(1).split("/");
  const route = routes[name] ? name : token ? "inicio" : "login";
  if (!token && route !== "login") { location.hash = "#login"; return; }
  if (token && route === "login") { location.hash = "#inicio"; return; }
  $("#nav").classList.toggle("hidden", route === "login");
  $$("#nav [data-route]").forEach((a) => a.classList.toggle("text-indigo-600", a.dataset.route === route));
  try {
    if (token && !ME) ME = await api("GET", "/me");
    $("#hdr").innerHTML = ME ? `<a href="#semestre" class="opacity-90">@${esc(ME.username)}</a>` : "";
    await routes[route]($("#view"), arg);
    if (ME) refreshBadge();
  } catch (e) {
    console.warn(e); // el error ya se mostró como toast
  }
}

addEventListener("hashchange", () => { closeDialog(); render(); });
render();
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
