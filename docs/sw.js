// Service worker：把 app 本身存在手机里，没网络也能打开（数据的离线备份在 app.js 处理）
const SHELL = "shell-v12";
const PHOTOS = "photos-v1";   // 板块照片（Unsplash）：看过一次就存在手机
const FILES = ["./", "index.html", "style.css", "app.js", "config.js", "manifest.webmanifest",
               "icon-192.png", "icon-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(FILES.map(f => new Request(f, { cache: "reload" })))).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => (k.startsWith("shell-") && k !== SHELL) || (k.startsWith("photos-") && k !== PHOTOS)).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  const isShell = url.origin === location.origin && !url.pathname.includes("/reports/");
  const isFont = url.hostname.includes("fonts.g");
  if (url.hostname === "images.unsplash.com") {
    e.respondWith(caches.open(PHOTOS).then(async cache => {
      const hit = await cache.match(e.request);
      if (hit) return hit;
      const res = await fetch(e.request);
      if (res.ok || res.type === "opaque") cache.put(e.request, res.clone());
      return res;
    }).catch(() => fetch(e.request)));
    return;
  }
  if (!isShell && !isFont) return;  // 报告数据交给 app.js
  if (isFont) {                      // 字体很少变：先用手机里的
    e.respondWith(caches.open(SHELL).then(async cache => (await cache.match(e.request)) ||
      fetch(e.request).then(res => { cache.put(e.request, res.clone()); return res; })));
    return;
  }
  // App 本身：有网络就一定拿最新版（不用旧的），4 秒内拿不到或没网络才用手机里存的
  e.respondWith(caches.open(SHELL).then(async cache => {
    const net = fetch(e.request, { cache: "no-cache" }).then(res => {
      if (res.ok) cache.put(e.request, res.clone());
      return res;
    });
    const slow = new Promise(r => setTimeout(r, 4000));
    try {
      const res = await Promise.race([net, slow.then(() => null)]);
      if (res) return res;
      return (await cache.match(e.request)) || net;
    } catch (err) {
      return (await cache.match(e.request)) || Response.error();
    }
  }));
});
