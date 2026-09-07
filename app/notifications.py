from datetime import datetime, date, timedelta, UTC
from app import db
from app.models import Payment, Notification, Card


def create_payment_notification(payment, reminder_days=2):
    existing = Notification.query.filter_by(
        payment_id=payment.id,
        reminder_type=f"{reminder_days}_days"
    ).first()

    if existing:
        return None

    card = db.session.get(Card, payment.card_id)
    scheduled_date = payment.due_date - timedelta(days=reminder_days)

    if scheduled_date < date.today():
        return None

    scheduled_at = datetime.combine(scheduled_date, datetime.min.time().replace(hour=9, minute=0))

    message = (
        f"{card.full_name} kredi kartı ödemeniz {reminder_days} gün sonra. "
        f"Ödenecek tutar: {payment.amount:,.2f} {payment.currency}. "
        f"Son ödeme: {payment.due_date.strftime('%d.%m.%Y')}"
    )

    notification = Notification(
        payment_id=payment.id,
        user_id=card.user_id,
        reminder_type=f"{reminder_days}_days",
        message=message,
        status="pending",
        scheduled_at=scheduled_at,
    )

    db.session.add(notification)
    db.session.commit()
    return notification


def get_pending_notifications(user_id):
    now = datetime.now(UTC)
    return Notification.query.filter(
        Notification.user_id == user_id,
        Notification.status == "pending",
        Notification.scheduled_at <= now,
    ).all()


def dismiss_notification(notification_id, user_id):
    notification = Notification.query.filter_by(
        id=notification_id,
        user_id=user_id
    ).first()

    if notification is None:
        return False

    notification.status = "dismissed"
    notification.dismissed_at = datetime.now(UTC)
    db.session.commit()
    return True


def generate_notifications_for_upcoming_payments(user_id):
    cards = Card.query.filter_by(user_id=user_id, is_active=True).all()
    today = date.today()

    for card in cards:
        for month_offset in range(0, 3):
            target_month = today.month + month_offset
            target_year = today.year
            while target_month > 12:
                target_month -= 12
                target_year += 1

            from app.date_utils import calculate_due_date
            due_date = calculate_due_date(target_year, target_month, card.due_day)

            if due_date < today:
                continue

            payment = Payment.query.filter_by(
                card_id=card.id,
                month=target_month,
                year=target_year
            ).first()

            if payment is None:
                from app.date_utils import calculate_statement_date
                statement_date = calculate_statement_date(
                    target_year, target_month, card.statement_day
                )
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
                db.session.commit()

            create_payment_notification(payment, reminder_days=card.reminder_days)
