import json
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from datetime import date, datetime, UTC
from app import db
from app.models import Card, Payment, Notification, Setting, Device
from app.date_utils import (
    calculate_due_date, calculate_statement_date,
    days_until, format_date_tr, format_date_short,
    get_current_month_payments, is_non_working_day,
    get_next_working_day, get_holiday_name
)
from app.notifications import (
    create_payment_notification, dismiss_notification,
    get_pending_notifications, generate_notifications_for_upcoming_payments
)
from app.push_notifications import send_to_all_user_devices
from app.vapid_keys import get_public_key

api_bp = Blueprint("api", __name__)


@api_bp.route("/cards", methods=["GET"])
@login_required
def get_cards():
    cards = Card.query.filter_by(user_id=current_user.id).all()
    return jsonify([c.to_dict() for c in cards])


@api_bp.route("/cards", methods=["POST"])
@login_required
def create_card():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Veri gönderilmedi"}), 400

    required = ["bank_name", "card_name", "statement_day", "due_day"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"{field} zorunludur"}), 400

    card = Card(
        user_id=current_user.id,
        bank_name=data["bank_name"].strip(),
        card_name=data["card_name"].strip(),
        statement_day=int(data["statement_day"]),
        due_day=int(data["due_day"]),
        current_balance=float(data.get("current_balance", 0)),
        currency=data.get("currency", "TRY"),
        reminder_days=int(data.get("reminder_days", 2)),
        is_active=data.get("is_active", True),
        note=data.get("note", ""),
    )

    db.session.add(card)
    db.session.commit()

    generate_notifications_for_upcoming_payments(current_user.id)

    return jsonify(card.to_dict()), 201


@api_bp.route("/cards/<int:card_id>", methods=["GET"])
@login_required
def get_card(card_id):
    card = Card.query.filter_by(id=card_id, user_id=current_user.id).first()
    if not card:
        return jsonify({"error": "Kart bulunamadı"}), 404
    return jsonify(card.to_dict())


@api_bp.route("/cards/<int:card_id>", methods=["PUT"])
@login_required
def update_card(card_id):
    card = Card.query.filter_by(id=card_id, user_id=current_user.id).first()
    if not card:
        return jsonify({"error": "Kart bulunamadı"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "Veri gönderilmedi"}), 400

    if "bank_name" in data:
        card.bank_name = data["bank_name"].strip()
    if "card_name" in data:
        card.card_name = data["card_name"].strip()
    if "statement_day" in data:
        card.statement_day = int(data["statement_day"])
    if "due_day" in data:
        card.due_day = int(data["due_day"])
    if "current_balance" in data:
        card.current_balance = float(data["current_balance"])
    if "currency" in data:
        card.currency = data["currency"]
    if "reminder_days" in data:
        card.reminder_days = int(data["reminder_days"])
    if "is_active" in data:
        card.is_active = data["is_active"]
    if "note" in data:
        card.note = data["note"]

    db.session.commit()
    return jsonify(card.to_dict())


@api_bp.route("/cards/<int:card_id>", methods=["DELETE"])
@login_required
def delete_card(card_id):
    card = Card.query.filter_by(id=card_id, user_id=current_user.id).first()
    if not card:
        return jsonify({"error": "Kart bulunamadı"}), 404

    db.session.delete(card)
    db.session.commit()
    return jsonify({"message": "Kart silindi"})


@api_bp.route("/payments", methods=["GET"])
@login_required
def get_payments():
    today = date.today()
    payments = (
        db.session.query(Payment)
        .join(Card)
        .filter(
            Card.user_id == current_user.id,
            Payment.is_paid == False,
            Payment.month == today.month,
            Payment.year == today.year,
        )
        .order_by(Payment.due_date.asc())
        .all()
    )
    result = []
    for p in payments:
        d = p.to_dict()
        d["card_name"] = p.card.full_name
        d["days_left"] = days_until(p.due_date)
        result.append(d)
    return jsonify(result)


@api_bp.route("/payments/upcoming", methods=["GET"])
@login_required
def get_upcoming_payments():
    cards = Card.query.filter_by(user_id=current_user.id, is_active=True).all()
    upcoming = get_current_month_payments(cards)

    result = []
    for item in upcoming:
        card = item["card"]
        due_date = item["due_date"]
        days_left = item["days_left"]

        payment = Payment.query.filter_by(
            card_id=card.id,
            due_date=due_date
        ).first()

        if payment is None:
            statement_date = calculate_statement_date(
                due_date.year, due_date.month, card.statement_day
            )
            payment = Payment(
                card_id=card.id,
                amount=card.current_balance,
                currency=card.currency,
                due_date=due_date,
                statement_date=statement_date,
                month=due_date.month,
                year=due_date.year,
            )
            db.session.add(payment)
            db.session.commit()

        result.append({
            "payment_id": payment.id,
            "card_id": card.id,
            "card_name": card.full_name,
            "bank_name": card.bank_name,
            "amount": payment.amount,
            "currency": payment.currency,
            "due_date": payment.due_date.isoformat(),
            "due_date_tr": format_date_tr(payment.due_date),
            "due_date_short": format_date_short(payment.due_date),
            "days_left": days_left,
            "is_paid": payment.is_paid,
            "status_color": get_status_color(days_left),
            "holiday_name": get_holiday_name(payment.due_date),
            "is_holiday_or_weekend": is_non_working_day(payment.due_date),
        })

    return jsonify(result)


@api_bp.route("/payments/<int:payment_id>/paid", methods=["POST"])
@login_required
def mark_payment_paid(payment_id):
    payment = (
        db.session.query(Payment)
        .join(Card)
        .filter(Payment.id == payment_id, Card.user_id == current_user.id)
        .first()
    )

    if not payment:
        return jsonify({"error": "Ödeme bulunamadı"}), 404

    payment.is_paid = True
    payment.paid_at = datetime.now(UTC)

    Notification.query.filter_by(
        payment_id=payment.id,
        user_id=current_user.id
    ).update({"status": "completed"})

    db.session.commit()
    return jsonify(payment.to_dict())


@api_bp.route("/notifications", methods=["GET"])
@login_required
def get_notifications():
    notifications = get_pending_notifications(current_user.id)
    result = []
    for n in notifications:
        d = n.to_dict()
        payment = db.session.get(Payment, n.payment_id)
        if payment:
            card = db.session.get(Card, payment.card_id)
            d["card_name"] = card.full_name if card else ""
            d["amount"] = payment.amount
            d["currency"] = payment.currency
            d["due_date"] = payment.due_date.isoformat()
        result.append(d)
    return jsonify(result)


@api_bp.route("/notifications/<int:notif_id>/dismiss", methods=["POST"])
@login_required
def api_dismiss_notification(notif_id):
    success = dismiss_notification(notif_id, current_user.id)
    if not success:
        return jsonify({"error": "Bildirim bulunamadı"}), 404
    return jsonify({"message": "Bildirim kapatıldı"})


@api_bp.route("/settings", methods=["GET"])
@login_required
def get_settings():
    setting = Setting.query.filter_by(user_id=current_user.id).first()
    if not setting:
        setting = Setting(user_id=current_user.id)
        db.session.add(setting)
        db.session.commit()
    return jsonify({
        "notifications_enabled": setting.notifications_enabled,
        "default_reminder_days": setting.default_reminder_days,
        "currency": setting.currency,
        "notification_sound": setting.notification_sound,
        "theme": setting.theme,
    })


@api_bp.route("/settings", methods=["PUT"])
@login_required
def update_settings():
    setting = Setting.query.filter_by(user_id=current_user.id).first()
    if not setting:
        setting = Setting(user_id=current_user.id)
        db.session.add(setting)

    data = request.get_json()
    if "notifications_enabled" in data:
        setting.notifications_enabled = data["notifications_enabled"]
    if "default_reminder_days" in data:
        setting.default_reminder_days = int(data["default_reminder_days"])
    if "currency" in data:
        setting.currency = data["currency"]
    if "notification_sound" in data:
        setting.notification_sound = data["notification_sound"]
    if "theme" in data:
        setting.theme = data["theme"]

    db.session.commit()
    return jsonify({"message": "Ayarlar güncellendi"})


@api_bp.route("/dashboard", methods=["GET"])
@login_required
def get_dashboard():
    cards = Card.query.filter_by(user_id=current_user.id, is_active=True).all()
    upcoming = get_current_month_payments(cards)

    today = date.today()
    total_month = sum(item["card"].current_balance for item in upcoming)
    unpaid_count = len([u for u in upcoming if not any(
        p.card_id == u["card"].id and p.is_paid
        for p in Payment.query.filter_by(
            month=today.month, year=today.year
        ).all()
    )])

    next_payment = upcoming[0] if upcoming else None

    return jsonify({
        "today": format_date_tr(today),
        "upcoming_count": len(upcoming),
        "total_month": total_month,
        "unpaid_count": unpaid_count,
        "next_payment": {
            "card_name": next_payment["card"].full_name if next_payment else None,
            "amount": next_payment["card"].current_balance if next_payment else 0,
            "due_date": format_date_tr(next_payment["due_date"]) if next_payment else None,
            "days_left": next_payment["days_left"] if next_payment else None,
            "status_color": get_status_color(next_payment["days_left"]) if next_payment else None,
        } if next_payment else None,
        "upcoming": [{
            "card_name": item["card"].full_name,
            "amount": item["card"].current_balance,
            "due_date": format_date_tr(item["due_date"]),
            "due_date_short": format_date_short(item["due_date"]),
            "days_left": item["days_left"],
            "status_color": get_status_color(item["days_left"]),
        } for item in upcoming],
    })


def get_status_color(days_left):
    if days_left <= 2:
        return "red"
    elif days_left <= 7:
        return "yellow"
    else:
        return "green"


@api_bp.route("/vapid-public-key", methods=["GET"])
def vapid_public_key():
    return jsonify({"public_key": get_public_key()})


@api_bp.route("/subscribe", methods=["POST"])
@login_required
def subscribe():
    data = request.get_json()
    if not data or "subscription" not in data:
        return jsonify({"error": "Abonelik bilgisi gerekli"}), 400

    subscription = data["subscription"]
    endpoint = subscription.get("endpoint", "")
    device_name = data.get("device_name", "Bilinmeyen Cihaz")

    existing = Device.query.filter_by(
        user_id=current_user.id,
        name=device_name
    ).first()

    if existing:
        existing.push_subscription = json.dumps(subscription)
        existing.is_active = True
    else:
        device = Device(
            user_id=current_user.id,
            name=device_name,
            push_subscription=json.dumps(subscription),
            is_active=True,
        )
        db.session.add(device)

    db.session.commit()
    return jsonify({"message": "Bildirim aboneliği başarıyla oluşturuldu"})


@api_bp.route("/unsubscribe", methods=["POST"])
@login_required
def unsubscribe():
    data = request.get_json()
    if not data or "endpoint" not in data:
        return jsonify({"error": "Endpoint gerekli"}), 400

    endpoint = data["endpoint"]
    devices = Device.query.filter_by(user_id=current_user.id).all()

    device = None
    for d in devices:
        try:
            sub = json.loads(d.push_subscription)
            if sub.get("endpoint") == endpoint:
                device = d
                break
        except (ValueError, TypeError, json.JSONDecodeError):
            continue

    if device:
        device.is_active = False
        db.session.commit()

    return jsonify({"message": "Abonelik iptal edildi"})


@api_bp.route("/devices", methods=["GET"])
@login_required
def get_devices():
    devices = Device.query.filter_by(user_id=current_user.id).all()
    return jsonify([{
        "id": d.id,
        "name": d.name,
        "is_active": d.is_active,
        "created_at": d.created_at.isoformat(),
    } for d in devices])


@api_bp.route("/notifications/all", methods=["GET"])
@login_required
def get_all_notifications():
    notifications = Notification.query.filter_by(
        user_id=current_user.id
    ).order_by(Notification.created_at.desc()).limit(50).all()

    result = []
    for n in notifications:
        d = n.to_dict()
        payment = db.session.get(Payment, n.payment_id)
        if payment:
            card = db.session.get(Card, payment.card_id)
            d["card_name"] = card.full_name if card else ""
            d["amount"] = payment.amount
            d["currency"] = payment.currency
            d["due_date"] = payment.due_date.isoformat()
        result.append(d)
    return jsonify(result)


@api_bp.route("/notifications/<int:notif_id>/send-test", methods=["POST"])
@login_required
def send_test_notification(notif_id):
    from app.push_notifications import send_to_all_user_devices
    title = "Test Bildirimi"
    body = "Bildirim sistemi başarıyla çalışıyor!"
    sent = send_to_all_user_devices(current_user.id, title, body)
    return jsonify({"message": f"{sent} cihaza bildirim gönderildi"})
