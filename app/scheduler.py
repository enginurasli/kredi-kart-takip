from apscheduler.schedulers.background import BackgroundScheduler
from datetime import date, datetime, timedelta, UTC
from app import db
from app.models import Card, Notification
from app.notifications import generate_notifications_for_upcoming_payments


scheduler = BackgroundScheduler()
_scheduler_started = False


def check_upcoming_payments():
    from app import create_app
    app = create_app()

    with app.app_context():
        cards = Card.query.filter_by(is_active=True).all()
        user_ids = list(set(card.user_id for card in cards))

        for user_id in user_ids:
            generate_notifications_for_upcoming_payments(user_id)

        from app.push_notifications import send_payment_reminder
        pending = Notification.query.filter(
            Notification.status == "pending",
            Notification.scheduled_at <= datetime.now(UTC),
        ).all()

        for notif in pending:
            send_payment_reminder(notif.id)


def init_scheduler(app):
    global _scheduler_started
    if _scheduler_started:
        return

    scheduler.add_job(
        check_upcoming_payments,
        "interval",
        minutes=5,
        id="check_payments",
        replace_existing=True,
    )
    scheduler.start()
    _scheduler_started = True


def stop_scheduler():
    global _scheduler_started
    scheduler.shutdown()
    _scheduler_started = False