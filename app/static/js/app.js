function toggleNav() {
    document.getElementById('navLinks').classList.toggle('show');
}

document.addEventListener('click', function(e) {
    const nav = document.getElementById('navLinks');
    const toggle = document.querySelector('.nav-toggle');
    if (nav && !nav.contains(e.target) && !toggle.contains(e.target)) {
        nav.classList.remove('show');
    }
});

if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
        navigator.serviceWorker.register('/sw.js')
            .then(reg => console.log('Service Worker kayitli, scope:', reg.scope))
            .catch(err => console.log('Service Worker hatasi:', err));

        navigator.serviceWorker.addEventListener('message', event => {
            if (event.data && event.data.type === 'PLAY_SOUND') {
                playNotificationSound(event.data.sound);
            }
        });
    });
}

function playNotificationSound(url) {
    try {
        const audio = new Audio(url);
        audio.volume = 1.0;
        audio.play().catch(e => console.log('Ses calmadi:', e));
    } catch(e) {
        console.log('Ses hatasi:', e);
    }
}

function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding)
        .replace(/-/g, '+')
        .replace(/_/g, '/');
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
}

async function subscribeToPush() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        alert('Tarayiciniz push notification desteklemiyor.');
        return false;
    }

    try {
        const permission = await Notification.requestPermission();
        if (permission !== 'granted') {
            alert('Bildirim izni verilmedi.');
            return false;
        }

        const reg = await navigator.serviceWorker.ready;

        const existingSubscription = await reg.pushManager.getSubscription();
        if (existingSubscription) {
            await existingSubscription.unsubscribe();
        }

        const keyRes = await fetch('/api/vapid-public-key');
        const keyData = await keyRes.json();

        const applicationServerKey = urlBase64ToUint8Array(keyData.public_key);
        const subscription = await reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: applicationServerKey,
        });

        const deviceName = getDeviceName();
        const subJson = subscription.toJSON();

        const res = await fetch('/api/subscribe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                subscription: subJson,
                device_name: deviceName,
            }),
        });

        if (res.status === 401) {
            console.error('Oturum sona erdi, giris yapmaniz gerekiyor.');
            return false;
        }

        if (res.ok) {
            console.log('Push aboneligi basarili');
            return true;
        } else {
            const err = await res.json();
            console.error('Abonelik hatasi:', err);
            return false;
        }
    } catch (err) {
        console.error('Push abonelik hatasi:', err);
        return false;
    }
}

async function unsubscribeFromPush() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        return;
    }

    try {
        const reg = await navigator.serviceWorker.ready;
        const subscription = await reg.pushManager.getSubscription();

        if (subscription) {
            const endpoint = subscription.endpoint;
            await subscription.unsubscribe();

            await fetch('/api/unsubscribe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ endpoint: endpoint }),
            });

            console.log('Push aboneligi iptal edildi');
        }
    } catch (err) {
        console.error('Unsubscribe hatasi:', err);
    }
}

async function isSubscribed() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        return false;
    }

    try {
        const reg = await navigator.serviceWorker.ready;
        const subscription = await reg.pushManager.getSubscription();
        return subscription !== null;
    } catch (err) {
        return false;
    }
}

async function sendTestNotification() {
    try {
        const res = await fetch('/api/notifications/0/send-test', { method: 'POST' });

        if (!res.ok) {
            if (res.status === 401) {
                alert('Oturumunuz sona erdi. Sayfayi yenileyip tekrar giris yapin.');
            } else {
                alert('Test bildirimi gonderilemedi (HTTP ' + res.status + ')');
            }
            return;
        }

        let data;
        try {
            data = await res.json();
        } catch(e) {
            alert('Beklenmeyen yanit. Oturumunuz sona ermis olabilir.');
            return;
        }
        alert(data.message || 'Test bildirimi gonderildi');
    } catch (err) {
        alert('Test bildirimi gonderilemedi');
    }
}

function getDeviceName() {
    const ua = navigator.userAgent;
    if (/Android/i.test(ua)) return 'Android Cihaz';
    if (/iPhone|iPad|iPod/i.test(ua)) return 'iOS Cihaz';
    if (/Windows/i.test(ua)) return 'Windows PC';
    if (/Macintosh|Mac OS X/i.test(ua)) return 'Mac';
    if (/Linux/i.test(ua)) return 'Linux PC';
    return 'Diger Cihaz';
}

async function checkAndShowNotifications() {
    try {
        const res = await fetch('/api/notifications');
        const notifications = await res.json();

        const container = document.getElementById('notificationsList');
        if (!container) return;

        if (notifications.length === 0) {
            container.innerHTML = '<p class="text-muted" style="text-align:center;padding:32px;">Aktif bildirim bulunmuyor.</p>';
            return;
        }

        container.innerHTML = notifications.map(n => `
            <div class="notification-item" id="notif-${n.id}">
                <div class="notification-icon">&#128276;</div>
                <div class="notification-content">
                    <div class="notification-message">${n.message}</div>
                    <div class="notification-meta">
                        ${n.card_name ? '<span>' + n.card_name + '</span>' : ''}
                        <span>${new Date(n.scheduled_at).toLocaleDateString('tr-TR')}</span>
                    </div>
                </div>
                <button class="btn btn-sm btn-secondary" onclick="dismissNotification(${n.id})">Kapat</button>
            </div>
        `).join('');
    } catch (err) {
        console.error('Bildirimler yuklenemedi:', err);
    }
}

async function dismissNotification(notifId) {
    try {
        const res = await fetch('/api/notifications/' + notifId + '/dismiss', { method: 'POST' });
        if (res.ok) {
            const el = document.getElementById('notif-' + notifId);
            if (el) el.remove();
        }
    } catch (err) {
        console.error('Bildirim kapatma hatasi:', err);
    }
}
