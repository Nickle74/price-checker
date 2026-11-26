/* price check — offline shell.
   Bump CACHE whenever you regenerate bottles.js or edit the app.

   Bump IMG_CACHE as well whenever an EXISTING photo is replaced rather than a
   new one added. Photos are served cache-first with no revalidation, and
   IMG_CACHE survives activate() by design, so a player who has already seen a
   bottle keeps that picture for good. Replacing 165 crowd-sourced photos with
   clean cutouts changed nothing on screen until this bumped -- the app went
   on serving a hand holding a bottle from a cache it had no reason to doubt. */
var CACHE = 'price-check-v33';
var IMG_CACHE = 'price-check-img-v10';
var IMG_CAP = 300;   // keep the installed footprint sane
var ASSETS = [
  './',
  './index.html',
  './styles.css',
  './app.js',
  './data/bottles.js',
  './manifest.webmanifest',
  './icons/icon-180.png',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable-512.png'
];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (c) {
      return Promise.all(ASSETS.map(function (u) {
        // cache:'reload' bypasses the browser's own HTTP cache. Without it a
        // fresh CACHE version can be filled with the stale files the browser
        // still holds, so bumping the version would not ship an update.
        return c.add(new Request(u, { cache: 'reload' }))
                .catch(function () { /* a missing optional asset must not fail the install */ });
      }));
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        return (k === CACHE || k === IMG_CACHE) ? null : caches.delete(k);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (e) {
  if (e.request.method !== 'GET') return;
  var url = new URL(e.request.url);
  if (url.origin !== location.origin) return;

  // Network-first for the page itself so edits show up; cache-first for the rest.
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).then(function (res) {
        var copy = res.clone();
        caches.open(CACHE).then(function (c) { c.put(e.request, copy); });
        return res;
      }).catch(function () {
        return caches.match('./index.html').then(function (r) { return r || Response.error(); });
      })
    );
    return;
  }

  // Bottle photos are many and optional: never precached, cached as they are
  // actually shown, and trimmed so an installed copy cannot grow without end.
  if (url.pathname.indexOf('/img/') !== -1) {
    e.respondWith(
      caches.open(IMG_CACHE).then(function (c) {
        return c.match(e.request).then(function (hit) {
          if (hit) return hit;
          return fetch(e.request).then(function (res) {
            if (res && res.status === 200) {
              c.put(e.request, res.clone());
              trim(c);
            }
            return res;
          });
        });
      })
    );
    return;
  }

  e.respondWith(
    caches.match(e.request).then(function (hit) {
      return hit || fetch(e.request).then(function (res) {
        if (res && res.status === 200) {
          var copy = res.clone();
          caches.open(CACHE).then(function (c) { c.put(e.request, copy); });
        }
        return res;
      });
    })
  );
});

// Oldest-first eviction. Cache.keys() returns insertion order, so dropping
// from the front removes the least recently added image.
function trim(cache) {
  cache.keys().then(function (keys) {
    var over = keys.length - IMG_CAP;
    for (var i = 0; i < over; i++) cache.delete(keys[i]);
  });
}
