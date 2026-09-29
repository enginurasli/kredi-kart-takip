import hashlib
import json

from flask import Flask, jsonify, redirect, request, url_for
from flask_login import LoginManager, current_user
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine

from config import Config


db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Lütfen giriş yapın."


@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith("/api/"):
        return jsonify({"error": "Oturum açmanız gerekiyor"}), 401
    return redirect(url_for("auth.login", next=request.url))


def _configure_sqlite():
    if hasattr(Engine, "_kart_takip_sqlite_configured"):
        return

    @event.listens_for(Engine, "connect")
    def configure_sqlite(dbapi_connection, connection_record):
        if dbapi_connection.__class__.__module__.startswith("sqlite3"):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    Engine._kart_takip_sqlite_configured = True


def _migrate_schema(app):
    connection = db.engine.connect()
    try:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        if "devices" in tables:
            columns = {column["name"] for column in inspector.get_columns("devices")}
            if "endpoint_hash" not in columns:
                connection.execute(text("ALTER TABLE devices ADD COLUMN endpoint_hash VARCHAR(64)"))
                connection.commit()
                inspector = inspect(connection)
                rows = connection.execute(text("SELECT id, user_id, push_subscription FROM devices")).mappings().all()
                for row in rows:
                    endpoint = ""
                    try:
                        payload = json.loads(row["push_subscription"] or "")
                        endpoint = payload.get("endpoint", "") if isinstance(payload, dict) else ""
                    except (TypeError, ValueError, json.JSONDecodeError):
                        endpoint = ""
                    endpoint_hash = hashlib.sha256(endpoint.encode("utf-8")).hexdigest() if endpoint else hashlib.sha256(f"legacy-{row['id']}".encode("utf-8")).hexdigest()
                    connection.execute(
                        text("UPDATE devices SET endpoint_hash = :endpoint_hash, is_active = CASE WHEN :endpoint = '' THEN 0 ELSE is_active END WHERE id = :id"),
                        {"endpoint_hash": endpoint_hash, "endpoint": endpoint, "id": row["id"]},
                    )
                connection.commit()

        if "users" in tables:
            columns = {column["name"] for column in inspector.get_columns("users")}
            if "reset_token_hash" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN reset_token_hash VARCHAR(64)"))
            if "reset_token_expires_at" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN reset_token_expires_at FLOAT"))
            connection.commit()

        if "payments" in tables:
            columns = {column["name"] for column in inspector.get_columns("payments")}
            if "card_id" in columns and "month" in columns and "year" in columns:
                duplicate = connection.execute(text("""
                    SELECT card_id, month, year
                    FROM payments
                    GROUP BY card_id, month, year
                    HAVING COUNT(*) > 1
                    LIMIT 1
                """)).first()
                if duplicate is None:
                    connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_card_period ON payments (card_id, month, year)"))
                    connection.commit()

        if "notifications" in tables:
            columns = {column["name"] for column in inspector.get_columns("notifications")}
            if "payment_id" in columns and "reminder_type" in columns:
                duplicate = connection.execute(text("""
                    SELECT payment_id, reminder_type
                    FROM notifications
                    GROUP BY payment_id, reminder_type
                    HAVING COUNT(*) > 1
                    LIMIT 1
                """)).first()
                if duplicate is None:
                    connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_payment_reminder ON notifications (payment_id, reminder_type)"))
                    connection.commit()
    finally:
        connection.close()


def _theme_context(app):
    """Kayıtlı tema tercihini tüm şablonlara sunar (KOD9)."""

    @app.context_processor
    def inject_theme():
        theme = "light"
        if getattr(current_user, "is_authenticated", False):
            from app.models import Setting
            setting = Setting.query.filter_by(user_id=current_user.id).first()
            if setting is not None and setting.theme in {"light", "dark"}:
                theme = setting.theme
        return {"app_theme": theme}

    return inject_theme


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    if not app.secret_key:
        raise RuntimeError("SECRET_KEY ayarlanmalı")

    if app.config.get("SQLALCHEMY_DATABASE_URI", "").startswith("sqlite:///"):
        _configure_sqlite()

    db.init_app(app)
    login_manager.init_app(app)
    _theme_context(app)

    from app.auth import auth_bp
    from app.routes import main_bp
    from app.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    with app.app_context():
        db.create_all()
        _migrate_schema(app)

    from app.scheduler import init_scheduler
    init_scheduler(app)

    return app
