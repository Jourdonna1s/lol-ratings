// Keeps the site's data on the device between visits (plain static file, no build step).
// * data files with ?v=<data_until>: never change once built, so they come from the cache; older versions of the
//   same file are dropped when a new one is saved
// * fonts and champion icons: from the cache, refreshed in the background
// * everything else (index.html, app.js, style.css, data/index.json): the network, as without this file
const CACHE = 'lol-ratings-v1';
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (k !== CACHE) await caches.delete(k);
  await self.clients.claim();
})()));
self.addEventListener('fetch', e => {
  const req = e.request, u = new URL(req.url);
  if (req.method !== 'GET' || u.origin !== location.origin) return;
  const ver = u.searchParams.get('v');
  if (ver && u.pathname.includes('/data/')) e.respondWith(versioned(req, u, ver));
  else if (u.pathname.includes('/fonts/') || u.pathname.includes('/img/champions/')) e.respondWith(refreshed(req));
});
async function versioned(req, u, ver) {
  const c = await caches.open(CACHE), hit = await c.match(req);
  if (hit) return hit;
  const r = await fetch(req);
  if (r.ok) {
    await c.put(req, r.clone());
    for (const k of await c.keys()) {
      const ku = new URL(k.url);
      if (ku.pathname === u.pathname && ku.searchParams.get('v') !== ver) await c.delete(k);
    }
  }
  return r;
}
async function refreshed(req) {
  const c = await caches.open(CACHE), hit = await c.match(req);
  const net = fetch(req).then(r => { if (r.ok) c.put(req, r.clone()); return r; });
  if (hit) { net.catch(() => {}); return hit; }
  return net;
}
