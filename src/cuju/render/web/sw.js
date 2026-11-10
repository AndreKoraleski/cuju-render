// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The service worker of the installable page. It keeps the page's own static files, the HTML,
// styles, scripts, models, pictures and sounds, in a cache named after the build of the page, so
// an installed page starts from its own copy and opens even with the server stopped, when its Home
// page says that the server is not answering. It never keeps an answer of the API, so recordings,
// teams, live streams and every other datum always come from the server, and it never keeps a
// request with a query, a range, a video or a file of another site. The build comes from the
// worker's own address, sw.js?build=, which the page registers. Each navigation asks the server
// for its build. While the server's build is the worker's own, files come from the cache first.
// While it differs, files come from the server, so a new version shows at once, and the page
// registers the worker of the new build, which replaces this one. With no server, the cache
// answers. The worker works only on the loopback origins that the server allows, and elsewhere it
// keeps nothing and unregisters itself.

const BUILD = new URL(self.location.href).searchParams.get('build') || 'none';
const PREFIX = 'cuju-page-';
const CACHE = `${PREFIX}${BUILD}`;
const LOOPBACK = ['127.0.0.1', 'localhost', '[::1]'];
// The shell of the page, kept as the worker installs.
const SHELL = [
    '', 'style.css', 'home.css', 'easy.css', 'flat.css', 'js/main.js', 'js/capture.js', 'lessons.json',
    'manifest.webmanifest', 'assets/cuju-logo.png', 'assets/icons/cuju-192.png', 'assets/icons/cuju-512.png',
];
// Media that the page streams in ranges, which the cache leaves to the server.
const STREAMED = /\.(mp4|webm|mov|m4v|cjr)$/i;
// How long a check of the server's build stands before a request asks again, in milliseconds.
const MODE_MS = 10000;
const BUILD_TIMEOUT_MS = 1500;

// Whether the address is http on a loopback host.
function onLoopback(url) {
    return url.protocol === 'http:' && LOOPBACK.includes(url.hostname);
}

// The path of a request inside the scope of the worker, or null outside it.
function inScope(url, scope) {
    if (url.origin !== scope.origin || !url.pathname.startsWith(scope.pathname)) {
        return null;
    }
    return url.pathname.slice(scope.pathname.length);
}

// Whether the cache may hold the answer of a request. Only a GET of a static file of the page
// itself qualifies, without a query or a range, outside the API and the sandbox of team workers.
function cacheable(method, url, scope, ranged = false) {
    if (method !== 'GET' || ranged || url.search || !onLoopback(url) || !onLoopback(scope)) {
        return false;
    }
    const path = inScope(url, scope);
    if (path === null || path === 'api' || path.startsWith('api/') || path.startsWith('sandbox/')) {
        return false;
    }
    return path !== 'sw.js' && !STREAMED.test(path);
}

// The key of a request in the cache, the page itself for every navigation to it.
function cacheKey(url, scope, navigate = false) {
    const path = inScope(url, scope);
    if (navigate || path === '' || path === 'index.html') {
        return scope.href;
    }
    return url.href;
}

// The way the worker answers, from the server's build. cache, the build is the worker's own.
// network, the server holds a new build. offline, the server does not answer.
function modeFor(answer) {
    if (!answer) {
        return 'offline';
    }
    return answer.build === BUILD ? 'cache' : 'network';
}

// The names of the caches that an activated worker of this build deletes.
function staleCaches(names) {
    return names.filter((name) => name.startsWith(PREFIX) && name !== CACHE);
}

// The rules, for the tests of the repository, which load this file without a browser.
self.cujuPage = { BUILD, CACHE, SHELL, cacheable, cacheKey, modeFor, onLoopback, staleCaches };

const scope = () => new URL(self.registration ? self.registration.scope : new URL('./', self.location.href).href);
let mode = null;

async function askBuild() {
    try {
        const res = await fetch(new URL('api/help/app', scope()).href, {
            cache: 'no-store', signal: AbortSignal.timeout(BUILD_TIMEOUT_MS),
        });
        return res.ok ? await res.json() : null;
    } catch {
        return null;
    }
}

function currentMode(fresh = false) {
    if (fresh || !mode || Date.now() - mode.at > MODE_MS) {
        mode = { at: Date.now(), value: askBuild().then(modeFor) };
    }
    return mode.value;
}

function offlinePage() {
    const text = '<!doctype html><meta charset="utf-8"><title>cuju</title>'
        + '<body style="font-family: sans-serif; padding: 24px">'
        + '<h1>The cuju server is not running</h1>'
        + '<p>Start it with <code>cuju render</code>, then reload this page.</p>';
    return new Response(text, { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
}

async function answer(request, url) {
    const navigate = request.mode === 'navigate';
    const key = cacheKey(url, scope(), navigate);
    const how = await currentMode(navigate);
    const cache = await caches.open(CACHE);
    if (how === 'network') {
        try {
            return await fetch(request);
        } catch {
            return (await cache.match(key)) || (navigate ? offlinePage() : Response.error());
        }
    }
    const kept = await cache.match(key);
    if (kept) {
        return kept;
    }
    try {
        const res = await fetch(request);
        if (how === 'cache' && res.ok && res.status === 200 && res.type === 'basic') {
            await cache.put(key, res.clone());
        }
        return res;
    } catch {
        return navigate ? offlinePage() : Response.error();
    }
}

async function forget() {
    for (const name of await caches.keys()) {
        if (name.startsWith(PREFIX)) {
            await caches.delete(name);
        }
    }
    await self.registration.unregister();
}

self.addEventListener('install', (event) => {
    event.waitUntil((async () => {
        if (!onLoopback(scope())) {
            return;
        }
        // The shell is kept only while the server holds this very build.
        if ((await currentMode(true)) === 'cache') {
            const cache = await caches.open(CACHE);
            await Promise.allSettled(SHELL.map(async (path) => {
                const url = new URL(path, scope());
                const res = await fetch(url.href, { cache: 'no-cache' });
                if (res.ok && res.status === 200 && res.type === 'basic') {
                    await cache.put(cacheKey(url, scope()), res);
                }
            }));
        }
        await self.skipWaiting();
    })());
});

self.addEventListener('activate', (event) => {
    event.waitUntil((async () => {
        if (!onLoopback(scope())) {
            await forget();
            return;
        }
        await Promise.all(staleCaches(await caches.keys()).map((name) => caches.delete(name)));
        await self.clients.claim();
    })());
});

self.addEventListener('fetch', (event) => {
    const request = event.request;
    const url = new URL(request.url);
    if (!cacheable(request.method, url, scope(), request.headers.has('range'))) {
        return;
    }
    event.respondWith(answer(request, url));
});

self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'forget') {
        event.waitUntil(forget());
    }
});
