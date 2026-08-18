from datetime import datetime, date
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db, login_manager


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    cards = db.relationship("Card", backref="user", lazy=True, cascade="all, delete-orphan")
    devices = db.relationship("Device", backref="user", lazy=True, cascade="all, delete-orphan")
    settings = db.relationship("Setting", backref="user", uselist=False, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Card(db.Model):
    __tablename__ = "cards"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    bank_name = db.Column(db.String(100), nullable=False)
    card_name = db.Column(db.String(100), nullable=False)
    statement_day = db.Column(db.Integer, nullable=False)
    due_day = db.Column(db.Integer, nullable=False)
    current_balance = db.Column(db.Float, default=0.0)
    currency = db.Column(db.String(10), default="TRY")
    reminder_days = db.Column(db.Integer, default=2)
    is_active = db.Column(db.Boolean, default=True)
    note = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    payments = db.relationship("Payment", backref="card", lazy=True, cascade="all, delete-orphan")

    @property
    def full_name(self):
        return f"{self.bank_name} {self.card_name}"

    def to_dict(self):
        return {
            "id": self.id,
            "bank_name": self.bank_name,
            "card_name": self.card_name,
            "full_name": self.full_name,
            "statement_day": self.statement_day,
            "due_day": self.due_day,
            "current_balance": self.current_balance,
            "currency": self.currency,
            "reminder_days": self.reminder_days,
            "is_active": self.is_active,
            "note": self.note,
            "created_at": self.created_at.isoformat(),
        }


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    card_id = db.Column(db.Integer, db.ForeignKey("cards.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default="TRY")
    due_date = db.Column(db.Date, nullable=False)
    statement_date = db.Column(db.Date, nullable=False)
    is_paid = db.Column(db.Boolean, default=False)
    paid_at = db.Column(db.DateTime, nullable=True)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    notifications = db.relationship("Notification", backref="payment", lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "card_id": self.card_id,
            "amount": self.amount,
            "currency": self.currency,
            "due_date": self.due_date.isoformat(),
            "statement_date": self.statement_date.isoformat(),
            "is_paid": self.is_paid,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "month": self.month,
            "year": self.year,
            "created_at": self.created_at.isoformat(),
        }


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reminder_type = db.Column(db.String(20), default="2_days")
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="pending")
    scheduled_at = db.Column(db.DateTime, nullable=False)
    sent_at = db.Column(db.DateTime, nullable=True)
    dismissed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "payment_id": self.payment_id,
            "user_id": self.user_id,
            "reminder_type": self.reminder_type,
            "message": self.message,
            "status": self.status,
            "scheduled_at": self.scheduled_at.isoformat(),
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "dismissed_at": self.dismissed_at.isoformat() if self.dismissed_at else None,
            "created_at": self.created_at.isoformat(),
        }


class Device(db.Model):
    __tablename__ = "devices"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    push_subscription = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Setting(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    notifications_enabled = db.Column(db.Boolean, default=True)
    default_reminder_days = db.Column(db.Integer, default=2)
    currency = db.Column(db.String(10), default="TRY")
    notification_sound = db.Column(db.String(50), default="default")
    theme = db.Column(db.String(20), default="light")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
