from apscheduler.schedulers.background import BackgroundScheduler

from app import db
from app.date_utils import get_utc_now
from app.models import Card, Notification
from app.notifications import generate_notifications_for_upcoming_payments


scheduler = BackgroundScheduler(timezone="UTC")
_scheduler_started = False


def check_upcoming_payments(app=None):
    if app is None:
        from flask import current_app
        app = current_app._get_current_object()

    with app.app_context():
        try:
            cards = Card.query.filter_by(is_active=True).all()
            user_ids = list({card.user_id for card in cards})

            for user_id in user_ids:
                generate_notifications_for_upcoming_payments(user_id)

            from app.push_notifications import send_payment_reminder
            pending = Notification.query.filter(
                Notification.status == "pending",
                Notification.scheduled_at <= get_utc_now(),
            ).all()

            for notification in pending:
                try:
                    send_payment_reminder(notification.id)
                except Exception:
                    db.session.rollback()

            # Tamamlanmış/iptal edilmiş eski kayıtları temizle.
            from app.notifications import purge_old_notifications
            purge_old_notifications()
        except Exception:
            db.session.rollback()
            raise


def init_scheduler(app):
    global _scheduler_started
    if not app.config.get("ENABLE_SCHEDULER", False):
        return

    if _scheduler_started:
        return

    # APScheduler varsayılan olarak job'ları bellekte tutar. Birden fazla
    # süreç/instance çalışırsa aynı bildirim mükerrer gönderilir; bu yüzden
    # job durumu kalıcı bir depoda tutulur (varsayılan: SQLAlchemyStore).
    jobstore = app.config.get("SCHEDULER_JOBSTORE")
    if jobstore:
        scheduler.add_jobstore(jobstore, replace_existing=True)

    scheduler.add_job(
        check_upcoming_payments,
        "interval",
        minutes=app.config.get("SCHEDULER_INTERVAL_MINUTES", 5),
        id="check_payments",
        replace_existing=True,
        kwargs={"app": app},
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.start()
    _scheduler_started = True


def stop_scheduler():
    global _scheduler_started
    if _scheduler_started and scheduler.running:
        scheduler.shutdown(wait=False)
    _scheduler_started = False
