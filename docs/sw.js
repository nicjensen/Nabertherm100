/* Service worker for the kiln price page.
 *
 * The page is a self-contained snapshot — the numbers are baked into the HTML at build
 * time — so caching the HTML is enough to keep the last known prices on screen with no
 * network at all. Pages are fetched NETWORK-FIRST (prices are never stale when the phone
 * is online) and everything else cache-first. Only same-origin requests are touched: the
 * page's own links out, and any API call, are left alone.
 *
 * Paths are relative, so the site works under any repo subpath (e.g. /Nabertherm100/).
 */
const CACHE = "kiln-v1";
const ROOT = new URL("./", self.location).href;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll([
        ROOT,
        new URL("manifest.webmanifest", ROOT).href,
        new URL("icon-192.png", ROOT).href,
        new URL("apple-touch-icon.png", ROOT).href
      ]))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

async function networkFirst(request) {
  const cache = await caches.open(CACHE);
  try {
    const response = await fetch(request);
    if (response && response.ok) cache.put(request, response.clone());
    return response;
  } catch (err) {
    const hit = await cache.match(request, { ignoreSearch: true });
    if (hit) return hit;
    const root = await cache.match(ROOT);
    if (root) return root;
    throw err;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE);
  const hit = await cache.match(request, { ignoreSearch: true });
  if (hit) return hit;
  const response = await fetch(request);
  if (response && response.ok) cache.put(request, response.clone());
  return response;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;        // leave other origins alone
  const isPage = request.mode === "navigate" || url.pathname.endsWith("/")
    || url.pathname.endsWith(".html") || url.pathname.endsWith(".json");
  event.respondWith(isPage ? networkFirst(request) : cacheFirst(request));
});
