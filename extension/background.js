// Abre Faltapp en una pestaña de fondo con lo copiado de Phoenix: si los ramos ya están emparejados se importa solo y la
// pestaña se cierra; si hay que elegir ramos o iniciar sesión, la muestra.
const FALTAPP = "https://faltapp.appscristianrojo.cl";
const EVERY = 30 * 60e3; // como mucho una importación cada 30 min (cada página de Phoenix vuelve a avisar)
const WAIT = 3 * 60e3; // Render dormido tarda ~1 min en despertar

chrome.runtime.onMessage.addListener((m, sender, reply) => {
  if (m.type === "due") {
    chrome.storage.local.get("last").then(({ last = 0 }) => {
      const due = Date.now() - last > EVERY;
      if (due) chrome.storage.local.set({ last: Date.now() });
      reply(due);
    });
    return true; // respuesta asíncrona
  }
  if (m.type === "import") importInBackground(m);
});

async function importInBackground({ portal, pages }) {
  const url = `${FALTAPP}/#importar/${encodeURIComponent(JSON.stringify({ portal, pages, v: 4 }))}`;
  const tab = await chrome.tabs.create({ url, active: false });
  for (const until = Date.now() + WAIT; Date.now() < until;) {
    await new Promise((r) => setTimeout(r, 2000)); // cada llamada a chrome.* mantiene vivo el service worker
    const t = await chrome.tabs.get(tab.id).catch(() => null);
    if (!t) return; // la cerró el usuario
    const hash = new URL(t.url || url).hash;
    if (/^#(inicio|notas)/.test(hash)) {
      await chrome.tabs.remove(tab.id);
      chrome.action.setBadgeText({ text: "✓" });
      chrome.action.setTitle({ title: `Faltapp: importado de Phoenix a las ${new Date().toTimeString().slice(0, 5)}` });
      return;
    }
    if (hash.startsWith("#login") || t.title?.startsWith("Elige tus ramos")) break; // necesita al usuario
  }
  chrome.tabs.update(tab.id, { active: true });
}

chrome.action.onClicked.addListener(() => chrome.tabs.create({ url: FALTAPP }));
