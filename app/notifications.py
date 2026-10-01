from datetime import UTC, datetime, time, timedelta
from sqlalchemy.exc import IntegrityError

from app import db
from app.date_utils import (
    APP_TIMEZONE,
    calculate_payment_due_date,
    get_today,
    get_utc_now,
)
from app.models import Card, Notification, Payment, Setting


REMINDER_HOUR = 9


def _scheduled_at(scheduled_date):
    return datetime.combine(
        scheduled_date,
        time(REMINDER_HOUR, 0),
        APP_TIMEZONE,
    ).astimezone(UTC).replace(tzinfo=None)


def build_notification_message(payment, card):
    days_left = max((payment.due_date - get_today()).days, 0)
    return (
        f"{card.full_name} kredi kartı ödemeniz {days_left} gün sonra. "
        f"Ödenecek tutar: {payment.amount:,.2f} {payment.currency}. "
        f"Son ödeme: {payment.due_date.strftime('%d.%m.%Y')}"
    )


def create_payment_notification(payment, reminder_days=2, commit=True):
    reminder_days = int(reminder_days)
    if not 1 <= reminder_days <= 30:
        raise ValueError("Hatırlatma günü 1-30 arasında olmalı")

    card = db.session.get(Card, payment.card_id)
    if card is None or not card.is_active or payment.is_paid:
        return None

    setting = Setting.query.filter_by(user_id=card.user_id).first()
    if setting is not None and not setting.notifications_enabled:
        return None

    reminder_type = f"{reminder_days}_days"
    existing = Notification.query.filter_by(
        payment_id=payment.id,
        reminder_type=reminder_type,
    ).first()

    today = get_today()
    scheduled_at = _scheduled_at(
        max(payment.due_date - timedelta(days=reminder_days), today)
    )
    message = build_notification_message(payment, card)

    if existing is not None:
        if existing.status not in ("pending",):
            # "cancelled" hatırlatmalar yeniden planlanır.
            existing.status = "pending"
            existing.sent_at = None
            existing.dismissed_at = None
        # Tutarlar veya vadeler değişmişse mesaj/zamanlama tazelenir.
        existing.message = message
        existing.scheduled_at = scheduled_at
        db.session.flush()
        return existing

    notification = Notification(
        payment_id=payment.id,
        user_id=card.user_id,
        reminder_type=reminder_type,
        message=message,
        status="pending",
        scheduled_at=scheduled_at,
    )
    db.session.add(notification)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return None
    if commit:
        db.session.commit()
    return notification


def get_pending_notifications(user_id):
    return Notification.query.filter(
        Notification.user_id == user_id,
        Notification.status == "pending",
        Notification.scheduled_at <= get_utc_now(),
    ).all()


def dismiss_notification(notification_id, user_id):
    notification = Notification.query.filter_by(
        id=notification_id,
        user_id=user_id,
    ).first()
    if notification is None or notification.status != "pending":
        return False

    notification.status = "dismissed"
    notification.dismissed_at = get_utc_now()
    db.session.commit()
    return True


def cancel_stale_notifications(user_id, commit=True):
    """Artık geçerli olmayan bekleyen hatırlatmaları iptal eder.

    Kapsam: geçmiş vadeli ödemeler, ödenmiş ödemeler, pasif kartlar ve
    silinmiş kartlar. Bu kayıtlar gönderilemeyeceği için "pending" kalıp
    birikir ve gereksiz iş yaratır.
    """
    # SQLAlchemy join'li sorguda toplu update desteklemez; geçersiz ödeme
    # kimlikleri alt sorguyla belirlenir.
    invalid_payment_ids = (
        db.session.query(Payment.id)
        .outerjoin(Card, Payment.card_id == Card.id)
        .filter(
            db.or_(
                Card.id.is_(None),
                Card.is_active == False,
                Payment.is_paid == True,
                Payment.due_date < get_today(),
            )
        )
    )
    cancelled = Notification.query.filter(
        Notification.user_id == user_id,
        Notification.status == "pending",
        db.or_(
            # Silinmiş ödemeye bağlı bildirimler
            ~Notification.payment_id.in_(db.select(Payment.id)),
            # Geçersiz ödemelere bağlı bildirimler
            Notification.payment_id.in_(invalid_payment_ids),
        ),
    ).update({"status": "cancelled"}, synchronize_session=False)

    if commit:
        db.session.commit()
    return cancelled


def purge_old_notifications(days=180, commit=True):
    """Tamamlanmış/iptal edilmiş eski kayıtları temizler (tablo büyümesini önler)."""
    cutoff = get_utc_now() - timedelta(days=days)
    removed = Notification.query.filter(
        Notification.status.in_(("completed", "cancelled", "dismissed")),
        Notification.created_at < cutoff,
    ).delete(synchronize_session=False)
    if removed:
        # Toplu silme oturum önbelleğini bayatlatmaz; aksi halde aynı
        # oturumda silinen kayıtlara erişim ObjectDeletedError verir.
        db.session.expire_all()
    if commit:
        db.session.commit()
    return removed


def generate_notifications_for_upcoming_payments(user_id, commit=True):
    cards = Card.query.filter_by(user_id=user_id, is_active=True).all()
    setting = Setting.query.filter_by(user_id=user_id).first()
    notifications_enabled = setting is None or setting.notifications_enabled

    # Pasif/silinmiş kartlar ve geçmiş vadeli ödemeler için bekleyen
    # hatırlatmalar önce temizlenir.
    cancel_stale_notifications(user_id, commit=False)

    if not notifications_enabled:
        Notification.query.filter_by(
            user_id=user_id,
            status="pending",
        ).update({"status": "cancelled"}, synchronize_session=False)
        # Ödeme kayıtları yine de üretilir; yalnızca hatırlatma planlanmaz.

    today = get_today()
    for card in cards:
        for month_offset in range(3):
            target_month = today.month + month_offset
            target_year = today.year + (target_month - 1) // 12
            target_month = (target_month - 1) % 12 + 1
            # Son ödeme tarihi hesap kesim gününden türetilir; bankalar vade
            # gününü resmî tatile denk gelirse bir sonraki iş gününe uzatır.
            statement_date, due_date = calculate_payment_due_date(
                target_year, target_month, card.statement_day
            )
            if due_date < today:
                continue

            payment = Payment.query.filter_by(
                card_id=card.id,
                month=target_month,
                year=target_year,
            ).first()
            if payment is None:
                payment = Payment(
                    card_id=card.id,
                    amount=card.current_balance,
                    currency=card.currency,
                    due_date=due_date,
                    statement_date=statement_date,
                    month=target_month,
                    year=target_year,
                )
                db.session.add(payment)
                db.session.flush()
            elif not payment.is_paid:
                # Ödenmemiş ödeme kartın güncel verisine göre senkronlanır.
                payment.due_date = due_date
                payment.statement_date = statement_date
                payment.amount = card.current_balance
                payment.currency = card.currency
                db.session.flush()

            if notifications_enabled:
                create_payment_notification(
                    payment,
                    reminder_days=card.reminder_days,
                    commit=False,
                )
                # Hatırlatma günü değişmişse eski tipteki bekleyen bildirim
                # mükerrer push üretmemek için iptal edilir.
                current_type = f"{card.reminder_days}_days"
                Notification.query.filter(
                    Notification.payment_id == payment.id,
                    Notification.reminder_type != current_type,
                    Notification.status == "pending",
                ).update({"status": "cancelled"}, synchronize_session=False)

    if commit:
        db.session.commit()
