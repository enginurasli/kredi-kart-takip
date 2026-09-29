import json
from datetime import UTC, datetime
from urllib.parse import urlparse

from pywebpush import WebPushException, webpush

from app import db
from app.date_utils import get_utc_now
from app.models import Card, Device, Notification, Payment, Setting
from app.vapid_keys import get_private_key_der_b64


VAPID_SUBJECT = "mailto:karttakip@uygulama.com"
PUSH_TIMEOUT = 10


def _subscription_is_valid(subscription):
    if not isinstance(subscription, dict):
        return False
    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys")
    if not isinstance(endpoint, str) or urlparse(endpoint).scheme != "https":
        return False
    if not endpoint or not isinstance(keys, dict):
        return False
    return all(
        isinstance(keys.get(key), str) and bool(keys[key])
        for key in ("p256dh", "auth")
    )


def send_push_notification(device, title, body, url="/"):
    try:
        subscription_info = json.loads(device.push_subscription or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        device.is_active = False
        db.session.commit()
        return False

    if not _subscription_is_valid(subscription_info):
        device.is_active = False
        db.session.commit()
        return False

    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps({
                "title": title,
                "body": body,
                "url": url,
            }),
            vapid_private_key=get_private_key_der_b64(),
            vapid_claims={"sub": VAPID_SUBJECT},
            ttl=86400,
            timeout=PUSH_TIMEOUT,
        )
        return True
    except WebPushException as exc:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code in {400, 404, 410}:
            device.is_active = False
            db.session.commit()
        return False
    except (OSError, ValueError, RuntimeError):
        return False


def send_payment_reminder(notification_id):
    notification = db.session.get(Notification, notification_id)
    if notification is None or notification.status != "pending":
        return False
    if notification.sent_at is not None:
        return False

    payment = db.session.get(Payment, notification.payment_id)
    card = db.session.get(Card, payment.card_id) if payment else None
    setting = Setting.query.filter_by(user_id=notification.user_id).first()
    if (
        payment is None
        or card is None
        or payment.is_paid
        or not card.is_active
        or (setting is not None and not setting.notifications_enabled)
    ):
        notification.status = "cancelled"
        db.session.commit()
        return False

    from app.date_utils import days_until
    days_left = days_until(payment.due_date)
    title = "Kredi Kartı Ödeme Hatırlatması"
    body = (
        f"{card.full_name} kredi kartı ödemeniz {days_left} gün sonra. "
        f"Ödenecek tutar: {payment.amount:,.2f} {payment.currency}. "
        f"Son ödeme: {payment.due_date.strftime('%d.%m.%Y')}"
    )

    devices = Device.query.filter_by(
        user_id=notification.user_id,
        is_active=True,
    ).all()
    sent_count = sum(
        send_push_notification(device, title, body, url="/")
        for device in devices
    )

    if sent_count > 0:
        notification.status = "sent"
        notification.sent_at = get_utc_now()
        notification.message = body
        db.session.commit()

    return sent_count > 0


def send_to_all_user_devices(user_id, title, body, url="/"):
    devices = Device.query.filter_by(
        user_id=user_id,
        is_active=True,
    ).all()
    return sum(
        send_push_notification(device, title, body, url)
        for device in devices
    )
