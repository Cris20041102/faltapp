const CACHE = "faltapp-v1";
const SHELL = ["/", "/app.js", "/app.css", "/manifest.json", "/icon.svg"];

// La versión nueva toma el control al tiro (si no, queda "esperando" mientras la app esté abierta y los avisos no se muestran)
self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) =>
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())));

// Red primero; si no hay conexión, la última copia del shell. La API nunca se cachea.
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.startsWith("/api")) return;
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        const copy = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return r;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match("/")))
  );
});

// Notificaciones push: el servidor manda {title, body, url}; al tocarla se abre esa pantalla de Faltapp
self.addEventListener("push", (e) => {
  const d = e.data ? e.data.json() : { title: "Faltapp" };
  e.waitUntil(self.registration.showNotification(d.title, {
    body: d.body || "", icon: "/icon-192.png", badge: "/icon-192.png", tag: d.tag, data: { url: d.url || "/#inicio" },
  }));
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = new URL(e.notification.data?.url || "/#inicio", self.location.origin).href;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((tabs) => {
    const tab = tabs.find((t) => t.url.startsWith(self.location.origin));
    return tab ? tab.focus().then((t) => t.navigate(url)).catch(() => self.clients.openWindow(url)) : self.clients.openWindow(url);
  }));
});
