import json
from pywebpush import webpush, WebPushException
from app.models import Device, Notification, Card, Payment
from app.vapid_keys import get_private_key_der_b64
from app import db
from datetime import datetime, UTC


VAPID_CLAIMS = {
    "sub": "mailto:karttakip@uygulama.local"
}


def send_push_notification(device, title, body, url="/"):
    subscription_info = json.loads(device.push_subscription)

    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps({
                "title": title,
                "body": body,
                "url": url,
            }),
            vapid_private_key=get_private_key_der_b64(),
            vapid_claims=VAPID_CLAIMS,
            ttl=86400,
        )
        return True
    except WebPushException as e:
        print(f"Push notification hatası: {e}")
        if "404" in str(e) or "410" in str(e):
            device.is_active = False
            db.session.commit()
        return False


def send_payment_reminder(notification_id):
    notification = Notification.query.get(notification_id)
    if not notification or notification.status != "pending":
        return False

    if notification.sent_at is not None:
        return False

    payment = Payment.query.get(notification.payment_id)
    if not payment:
        return False

    card = Card.query.get(payment.card_id)
    if not card:
        return False

    from app.date_utils import days_until
    days_left = days_until(payment.due_date)

    title = f"Kredi Kartı Ödeme Hatırlatması"
    body = (
        f"{card.full_name} kredi kartı ödemeniz {days_left} gün sonra. "
        f"Ödenecek tutar: {payment.amount:,.2f} {payment.currency}. "
        f"Son ödeme: {payment.due_date.strftime('%d.%m.%Y')}"
    )

    devices = Device.query.filter_by(
        user_id=notification.user_id,
        is_active=True
    ).all()

    sent_count = 0
    for device in devices:
        if send_push_notification(device, title, body, url="/"):
            sent_count += 1

    if sent_count > 0:
        from datetime import datetime
        notification.status = "sent"
        notification.sent_at = datetime.now(UTC)
        notification.message = body
        db.session.commit()

    return sent_count > 0


def send_to_all_user_devices(user_id, title, body, url="/"):
    devices = Device.query.filter_by(
        user_id=user_id,
        is_active=True
    ).all()

    sent_count = 0
    for device in devices:
        if send_push_notification(device, title, body, url):
            sent_count += 1

    return sent_count
