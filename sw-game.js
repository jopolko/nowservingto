var CACHE = 'dinner-lottery-v4';
var SHELL = ['/game', '/game.html', '/manifest-game.json', '/pwa-icons/game-192.png'];

self.addEventListener('install', function(e){
  e.waitUntil(caches.open(CACHE).then(function(c){ return c.addAll(SHELL); }));
  self.skipWaiting();
});
self.addEventListener('activate', function(e){
  e.waitUntil(caches.keys().then(function(keys){
    return Promise.all(keys.filter(function(k){ return k!==CACHE; }).map(function(k){ return caches.delete(k); }));
  }));
  self.clients.claim();
});
self.addEventListener('fetch', function(e){
  var url = new URL(e.request.url);
  // corridors.json: network-first (always want fresh data), cache as fallback
  if(url.pathname === '/data/corridors.json'){
    e.respondWith(fetch(e.request).then(function(r){
      var clone = r.clone();
      caches.open(CACHE).then(function(c){ c.put(e.request, clone); });
      return r;
    }).catch(function(){ return caches.match(e.request); }));
    return;
  }
  // shell: cache-first
  if(SHELL.indexOf(url.pathname) > -1 || url.pathname.startsWith('/fonts/') || url.pathname.startsWith('/icons/')){
    e.respondWith(caches.match(e.request).then(function(r){ return r || fetch(e.request); }));
    return;
  }
});
