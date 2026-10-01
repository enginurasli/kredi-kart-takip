import hashlib
import json
import math
from datetime import datetime
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from app import db
from app.models import Card, Payment, Notification, Setting, Device
from app.date_utils import (
    days_until, format_date_tr, format_date_short,
    get_current_month_payments, get_today, get_utc_now,
    calculate_payment_due_date, describe_due_date_shift,
    is_non_working_day, get_holiday_name
)
from app.notifications import (
    cancel_stale_notifications, dismiss_notification,
    get_pending_notifications,
    generate_notifications_for_upcoming_payments
)
from app.push_notifications import send_to_all_user_devices
from app.vapid_keys import get_public_key

api_bp = Blueprint("api", __name__)


def json_payload():
    if not request.is_json:
        return None, (jsonify({"error": "Geçerli JSON verisi gerekli"}), 400)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, (jsonify({"error": "Geçerli JSON verisi gerekli"}), 400)
    return data, None


def parse_int(data, field, minimum, maximum, default=None):
    value = data.get(field, default)
    if value is None:
        raise ValueError(f"{field} zorunludur")
    if isinstance(value, bool):
        raise ValueError(f"{field} sayı olmalı")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} sayı olmalı")
    if str(value).strip() != str(parsed):
        raise ValueError(f"{field} sayı olmalı")
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{field} {minimum}-{maximum} arasında olmalı")
    return parsed


def parse_balance(data, field="current_balance", default=0.0):
    value = data.get(field, default)
    if isinstance(value, bool):
        raise ValueError("current_balance sayı olmalı")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError("current_balance sayı olmalı")
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError("current_balance sıfır veya daha büyük olmalı")
    return round(parsed, 2)


def parse_text(data, field, required=False, max_length=100):
    value = data.get(field, "")
    if not isinstance(value, str):
        raise ValueError(f"{field} metin olmalı")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{field} zorunludur")
    if len(value) > max_length:
        raise ValueError(f"{field} en fazla {max_length} karakter olabilir")
    return value


def parse_bool(data, field, default=True):
    value = data.get(field, default)
    if not isinstance(value, bool):
        raise ValueError(f"{field} doğru veya yanlış olmalı")
    return value


def get_or_create_setting(user_id):
    setting = Setting.query.filter_by(user_id=user_id).first()
    if setting is None:
        setting = Setting(user_id=user_id)
        db.session.add(setting)
        db.session.flush()
    return setting


@api_bp.route("/cards", methods=["GET"])
@login_required
def get_cards():
    cards = Card.query.filter_by(user_id=current_user.id).all()
    return jsonify([c.to_dict() for c in cards])


@api_bp.route("/cards", methods=["POST"])
@login_required
def create_card():
    data, error = json_payload()
    if error:
        return error

    try:
        setting = get_or_create_setting(current_user.id)
        card = Card(
            user_id=current_user.id,
            bank_name=parse_text(data, "bank_name", required=True),
            card_name=parse_text(data, "card_name", required=True),
            statement_day=parse_int(data, "statement_day", 1, 31),
            current_balance=parse_balance(data),
            currency=parse_text(data, "currency") or setting.currency or "TRY",
            reminder_days=parse_int(data, "reminder_days", 1, 30, setting.default_reminder_days),
            is_active=parse_bool(data, "is_active"),
            note=parse_text(data, "note", max_length=2000),
        )
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400

    db.session.add(card)
    db.session.flush()
    generate_notifications_for_upcoming_payments(current_user.id, commit=False)
    db.session.commit()

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

    data, error = json_payload()
    if error:
        return error

    try:
        if "bank_name" in data:
            card.bank_name = parse_text(data, "bank_name", required=True)
        if "card_name" in data:
            card.card_name = parse_text(data, "card_name", required=True)
        if "statement_day" in data:
            card.statement_day = parse_int(data, "statement_day", 1, 31)
        if "current_balance" in data:
            card.current_balance = parse_balance(data)
        if "currency" in data:
            currency = parse_text(data, "currency")
            if currency not in {"TRY", "USD", "EUR"}:
                raise ValueError("currency TRY, USD veya EUR olmalı")
            card.currency = currency
        if "reminder_days" in data:
            card.reminder_days = parse_int(data, "reminder_days", 1, 30)
        if "is_active" in data:
            card.is_active = parse_bool(data, "is_active")
        if "note" in data:
            card.note = parse_text(data, "note", max_length=2000)
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400

    db.session.commit()
    generate_notifications_for_upcoming_payments(current_user.id)
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


@api_bp.route("/notifications/cleanup", methods=["POST"])
@login_required
def cleanup_notifications():
    """Geçersiz hatırlatmaları temizler (bakım uç noktası)."""
    from app.notifications import purge_old_notifications
    cancel_stale_notifications(current_user.id)
    removed = purge_old_notifications()
    return jsonify({"message": f"{removed} eski bildirim temizlendi"})


@api_bp.route("/payments", methods=["GET"])
@login_required
def get_payments():
    # Not: Ödemeler takvim ayına göre değil, gerçek vade tarihine göre listelenir.
    # Hesap kesim günü bu ayın içinde geçmiş bir güne denk gelen kartlarda vade bir
    # sonraki aya kaydığı için ay bazlı filtre sayfayı boş gösteriyordu.
    today = get_today()
    period_start = today.replace(day=1)
    payments = (
        db.session.query(Payment)
        .join(Card)
        .filter(
            Card.user_id == current_user.id,
            Payment.due_date >= period_start,
        )
        .order_by(Payment.due_date.asc())
        .limit(100)
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
            result.append({
                "payment_id": None,
                "card_id": card.id,
                "card_name": card.full_name,
                "bank_name": card.bank_name,
                "amount": card.current_balance,
                "currency": card.currency,
                "due_date": due_date.isoformat(),
                "due_date_tr": format_date_tr(due_date),
                "due_date_short": format_date_short(due_date),
                "days_left": days_left,
                "is_paid": False,
                "status_color": get_status_color(days_left),
                "holiday_name": get_holiday_name(due_date),
                "is_holiday_or_weekend": is_non_working_day(due_date),
                "statement_date": item["statement_date"].isoformat(),
                "statement_date_tr": format_date_tr(item["statement_date"]),
                "due_date_shifted_to": item["shifted"],
            })
            continue

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
            "statement_date": payment.statement_date.isoformat(),
            "statement_date_tr": format_date_tr(payment.statement_date),
            "due_date_shifted_to": describe_due_date_shift(
                payment.statement_date, payment.due_date
            ),
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

    if not payment.is_paid:
        payment.is_paid = True
        payment.paid_at = get_utc_now()

    Notification.query.filter_by(
        payment_id=payment.id,
        user_id=current_user.id,
        status="pending",
    ).update({"status": "completed"}, synchronize_session=False)

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
    setting = get_or_create_setting(current_user.id)
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
    data, error = json_payload()
    if error:
        return error

    setting = get_or_create_setting(current_user.id)
    try:
        if "notifications_enabled" in data:
            setting.notifications_enabled = parse_bool(data, "notifications_enabled")
        if "default_reminder_days" in data:
            setting.default_reminder_days = parse_int(
                data,
                "default_reminder_days",
                1,
                30,
            )
        if "currency" in data:
            currency = parse_text(data, "currency")
            if currency not in {"TRY", "USD", "EUR"}:
                raise ValueError("currency TRY, USD veya EUR olmalı")
            setting.currency = currency
        if "notification_sound" in data:
            sound = parse_text(data, "notification_sound")
            if sound not in {"default", "none"}:
                raise ValueError("notification_sound default veya none olmalı")
            setting.notification_sound = sound
        if "theme" in data:
            theme = parse_text(data, "theme")
            if theme not in {"light", "dark"}:
                raise ValueError("theme light veya dark olmalı")
            setting.theme = theme
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400

    db.session.commit()
    if not setting.notifications_enabled:
        Notification.query.filter_by(
            user_id=current_user.id,
            status="pending",
        ).update({"status": "cancelled"}, synchronize_session=False)
        db.session.commit()

    return jsonify({"message": "Ayarlar güncellendi"})


@api_bp.route("/dashboard", methods=["GET"])
@login_required
def get_dashboard():
    cards = Card.query.filter_by(user_id=current_user.id, is_active=True).all()
    upcoming = get_current_month_payments(cards)

    today = get_today()
    total_month = sum(item["card"].current_balance for item in upcoming)

    # Yaklaşan her kart için tek sorguda ödenmiş ödeme var mı bakılır (N+1 yok).
    paid_pairs = set()
    if upcoming:
        card_ids = {item["card"].id for item in upcoming}
        due_dates = {item["due_date"] for item in upcoming}
        rows = (
            db.session.query(Payment.card_id, Payment.due_date)
            .join(Card)
            .filter(
                Card.user_id == current_user.id,
                Payment.is_paid == True,
                Payment.card_id.in_(card_ids),
                Payment.due_date.in_(due_dates),
            )
            .distinct()
            .all()
        )
        paid_pairs = {(card_id, due_date) for card_id, due_date in rows}

    unpaid_count = sum(
        1
        for item in upcoming
        if (item["card"].id, item["due_date"]) not in paid_pairs
    )

    # Ödenmiş kartlar "yaklaşan ödeme" ve toplamda sayılmaz.
    unpaid_items = [
        item
        for item in upcoming
        if (item["card"].id, item["due_date"]) not in paid_pairs
    ]
    next_payment = unpaid_items[0] if unpaid_items else None
    total_month = sum(item["card"].current_balance for item in unpaid_items)

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
            "is_paid": (item["card"].id, item["due_date"]) in paid_pairs,
        } for item in unpaid_items],
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


@api_bp.route("/due-date-preview", methods=["GET"])
@login_required
def due_date_preview():
    """Hesap kesim gününden son ödeme tarihini önizler.

    Tatil ve hafta sonu kaydırması yalnızca sunucuda hesaplanabilir; form
    bu uç noktayı kullanarak kullanıcıya nihai tarihi gösterir.
    """
    try:
        statement_day = parse_int(request.args, "statement_day", 1, 31)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    today = get_today()
    year = request.args.get("year", type=int) or today.year
    month = request.args.get("month", type=int) or today.month
    if not 1 <= month <= 12:
        return jsonify({"error": "month 1-12 arasında olmalı"}), 400

    try:
        statement_date, due_date = calculate_payment_due_date(year, month, statement_day)
    except (ValueError, OverflowError):
        return jsonify({"error": "Tarih hesaplanamadı"}), 400

    return jsonify({
        "statement_day": statement_day,
        "statement_date": statement_date.isoformat(),
        "statement_date_tr": format_date_tr(statement_date),
        "due_date": due_date.isoformat(),
        "due_date_tr": format_date_tr(due_date),
        "due_date_short": format_date_short(due_date),
        "days_left": days_until(due_date),
        "shifted_to_holiday": describe_due_date_shift(statement_date, due_date),
    })


@api_bp.route("/subscribe", methods=["POST"])
@login_required
def subscribe():
    data, error = json_payload()
    if error:
        return error

    subscription = data.get("subscription")
    if not isinstance(subscription, dict):
        return jsonify({"error": "Abonelik bilgisi gerekli"}), 400

    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys")
    if (
        not isinstance(endpoint, str)
        or urlparse(endpoint).scheme != "https"
        or not endpoint
        or not isinstance(keys, dict)
        or not isinstance(keys.get("p256dh"), str)
        or not isinstance(keys.get("auth"), str)
        or not keys["p256dh"]
        or not keys["auth"]
    ):
        return jsonify({"error": "Geçersiz push aboneliği"}), 400

    device_name = parse_text(data, "device_name") or "Bilinmeyen Cihaz"
    endpoint_hash = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()
    existing = Device.query.filter_by(
        user_id=current_user.id,
        endpoint_hash=endpoint_hash,
    ).first()

    if existing:
        existing.name = device_name
        existing.push_subscription = json.dumps(subscription)
        existing.is_active = True
    else:
        device = Device(
            user_id=current_user.id,
            endpoint_hash=endpoint_hash,
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
    data, error = json_payload()
    if error:
        return error

    endpoint = data.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint:
        return jsonify({"error": "Endpoint gerekli"}), 400

    endpoint_hash = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()
    device = Device.query.filter_by(
        user_id=current_user.id,
        endpoint_hash=endpoint_hash,
    ).first()
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


@api_bp.route("/notifications/send-test", methods=["POST"])
@login_required
def send_test_notification():
    sent = send_to_all_user_devices(
        current_user.id,
        "Test Bildirimi",
        "Bildirim sistemi başarıyla çalışıyor!",
    )
    return jsonify({"message": f"{sent} cihaza bildirim gönderildi"})
