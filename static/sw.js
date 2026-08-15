const CACHE = "ark-v7";
const ASSETS = ["/", "/styles.css", "/app.js", "/manifest.webmanifest", "/logo.svg", "/icon-32.png", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  if (e.request.method !== "GET") return;
  if (url.pathname.startsWith("/api/")) return; // always network for data
  if (url.pathname.startsWith("/uploads/")) return; // avatars: always fresh
  if (e.request.mode === "navigate") {
    e.respondWith(fetch(e.request).catch(() => caches.match("/")));
    return;
  }
  e.respondWith(
    caches.match(e.request).then((cached) => {
      const fresh = fetch(e.request).then((res) => {
        if (res.ok) e.waitUntil(caches.open(CACHE).then((c) => c.put(e.request, res.clone())));
        return res;
      });
      return cached || fresh;
    })
  );
});
