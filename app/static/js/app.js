function toggleNav() {
    document.getElementById('navLinks').classList.toggle('show');
}

function escapeHtml(value) {
    const element = document.createElement('div');
    element.textContent = value == null ? '' : String(value);
    return element.innerHTML;
}

function formatMoney(amount, currency = 'TRY') {
    return new Intl.NumberFormat('tr-TR', {
        style: 'currency',
        currency: currency,
        minimumFractionDigits: 0,
        maximumFractionDigits: 2
    }).format(Number(amount) || 0);
}

// HTML'e gömülürken kullanıcı verisi her zaman escapeHtml ile sarılmalıdır;
// formatMoney yalnızca sayıyı biçimlendirir, HTML kaçışı yapmaz.
function moneyHtml(amount, currency = 'TRY') {
    return escapeHtml(formatMoney(amount, currency));
}

async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    let data = null;
    try {
        data = await response.json();
    } catch (e) {}
    if (!response.ok) {
        if (response.status === 401) {
            window.location.href = '/login';
        }
        throw new Error(data?.error || `HTTP ${response.status}`);
    }
    return data;
}

document.addEventListener('click', function(e) {
    const nav = document.getElementById('navLinks');
    const toggle = document.querySelector('.nav-toggle');
    if (nav && toggle && !nav.contains(e.target) && !toggle.contains(e.target)) {
        nav.classList.remove('show');
    }
});

if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
        navigator.serviceWorker.register('/sw.js')
            .then(reg => console.log('Service Worker kayitli, scope:', reg.scope))
            .catch(err => console.log('Service Worker hatasi:', err));

        // Yeni sürüm kurulduğında açık sekmeleri bir kez yenileyerek
        // eski HTML/JS ile yeni backend arasında kalıcı uyumsuzluğu önler.
        let refreshing = false;
        navigator.serviceWorker.addEventListener('controllerchange', function() {
            if (refreshing) return;
            refreshing = true;
            window.location.reload();
        });

        navigator.serviceWorker.addEventListener('message', event => {
            if (event.data && event.data.type === 'PLAY_SOUND') {
                playNotificationSound(event.data.sound);
            }
        });

        // Sayfa her açıldığında güncelleme kontrolü yap.
        if (navigator.serviceWorker.controller) {
            navigator.serviceWorker.getRegistration().then(reg => {
                if (reg) reg.update();
            }).catch(() => {});
        }
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
        const data = await fetchJson('/api/notifications/send-test', { method: 'POST' });
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
        const notifications = await fetchJson('/api/notifications');

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
                <div class="notification-message">${escapeHtml(n.message)}</div>
                <div class="notification-meta">
                    ${n.card_name ? '<span>' + escapeHtml(n.card_name) + '</span>' : ''}
                    <span>${escapeHtml(new Date(n.scheduled_at).toLocaleDateString('tr-TR'))}</span>

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
        await fetchJson('/api/notifications/' + notifId + '/dismiss', { method: 'POST' });
        const el = document.getElementById('notif-' + notifId);
        if (el) el.remove();
    } catch (err) {
        console.error('Bildirim kapatma hatasi:', err);
    }
}
