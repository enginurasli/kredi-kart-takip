const CACHE_NAME = 'kart-takip-v4';
const urlsToCache = [
    '/static/css/style.css',
    '/static/js/app.js',
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png',
    '/static/sounds/notification.wav'
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(urlsToCache))
    );
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.filter(name => name !== CACHE_NAME)
                    .map(name => caches.delete(name))
            );
        })
    );
    self.clients.claim();
});

function isStaticAsset(url) {
    return url.pathname.startsWith('/static/');
}

function isApiRequest(url) {
    return url.pathname.startsWith('/api/');
}

self.addEventListener('fetch', event => {
    const request = event.request;
    const url = new URL(request.url);

    if (request.method !== 'GET' || url.origin !== self.location.origin) {
        return;
    }

    event.respondWith(
        (async () => {
            if (isApiRequest(url)) {
                return fetch(request);
            }

            if (isStaticAsset(url)) {
                const cached = await caches.match(request);
                if (cached) return cached;
                const network = await fetch(request);
                if (network && network.ok) {
                    const copy = network.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
                }
                return network;
            }

            const network = await fetch(request).catch(() => null);
            if (network && network.ok) {
                const copy = network.clone();
                caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
                return network;
            }

            const cached = await caches.match(request);
            if (cached) return cached;
            return fetch(request);
        })()
    );
});

self.addEventListener('push', event => {
    let data = { title: 'Kredi Karti Hatirlatmasi', body: 'Odeme hatirlatmasi var' };

    if (event.data) {
        try {
            data = event.data.json();
        } catch (e) {
            data.body = event.data.text();
        }
    }

    const options = {
        body: data.body,
        icon: '/static/icons/icon-192.png',
        badge: '/static/icons/icon-192.png',
        vibrate: [500, 200, 500, 200, 500],
        tag: 'kart-takip-' + Date.now(),
        renotify: true,
        requireInteraction: true,
        silent: false,
        data: {
            url: data.url || '/',
            dateOfArrival: Date.now()
        }
    };

    event.waitUntil(
        self.registration.showNotification(data.title, options)
            .then(() => {
                return self.clients.matchAll({ type: 'window' }).then(clients => {
                    clients.forEach(client => {
                        client.postMessage({
                            type: 'PLAY_SOUND',
                            sound: '/static/sounds/notification.wav'
                        });
                    });
                });
            })
    );
});

self.addEventListener('notificationclick', event => {
    event.notification.close();

    const urlToOpen = event.notification.data && event.notification.data.url
        ? event.notification.data.url
        : '/';

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then(windowClients => {
                for (let client of windowClients) {
                    if (client.url.includes(self.location.origin) && 'focus' in client) {
                        client.navigate(urlToOpen);
                        return client.focus();
                    }
                }
                if (clients.openWindow) {
                    return clients.openWindow(urlToOpen);
                }
            })
    );
});
