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


def _backfill_statement_dates(connection):
    """Mevcut ödemelerin statement_date'ini hesap kesim gününe göre düzeltir.

    due_day kaldırılmadan önce statement_date, eski mantıkla (ödeme tarihinden
    geriye doğru) hesaplanmıştı. Bu yardımcı, ödemeleri yeni kurala göre
    yeniden hesaplar; SQLite ve PostgreSQL'in ortak SQL'i ile çalışır.
    """
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "payments" not in tables or "cards" not in tables:
        return inspector

    payment_columns = {column["name"] for column in inspector.get_columns("payments")}
    card_columns = {column["name"] for column in inspector.get_columns("cards")}
    if not {"card_id", "month", "year"} <= payment_columns:
        return inspector
    if "statement_day" not in card_columns:
        return inspector

    dialect = connection.engine.dialect.name
    month_expr = f'CAST(payments."month" AS TEXT)' if dialect == "postgresql" else 'payments.month'
    year_expr = f'CAST(payments."year" AS TEXT)' if dialect == "postgresql" else 'payments.year'
    if dialect == "postgresql":
        connection.execute(text("""
            UPDATE payments
            SET statement_date = make_date(
                    CAST(payments."year" AS INTEGER),
                    payments."month",
                    LEAST(
                        cards.statement_day,
                        EXTRACT(DAY FROM make_date(
                            CAST(payments."year" AS INTEGER),
                            payments."month",
                            1
                        ) + INTERVAL '1 month' - INTERVAL '1 day')
                    )::INTEGER
                )
            FROM cards
            WHERE payments.card_id = cards.id
        """))
    else:
        connection.execute(text(f"""
            UPDATE payments
            SET statement_date = date(
                printf('%04d-%02d-%02d', {year_expr}, {month_expr},
                    MIN(
                        cards.statement_day,
                        CAST(strftime('%d', date({year_expr} || '-' ||
                            printf('%02d', {month_expr}) || '-01', '+1 month', '-1 day'))
                            AS INTEGER)
                    )
                )
            )
            FROM cards
            WHERE payments.card_id = cards.id
        """))
    connection.commit()
    return inspect(connection)


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

        if "cards" in tables:
            # due_day kaldırıldı: son ödeme tarihi hesap kesim gününden
            # türetiliyor. Sütun veritabanında NOT NULL kalırsa yeni kayıtlar
            # başarısız olur, o yüzden düşürülür. Ödemelerin statement_date'i
            # önce ORM üzerinden yeniden hesaplanır.
            columns = {column["name"] for column in inspector.get_columns("cards")}
            if "due_day" in columns:
                inspector = _backfill_statement_dates(connection)
                connection.execute(text("ALTER TABLE cards DROP COLUMN due_day"))
                connection.commit()
                inspector = inspect(connection)

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

    # Render ve benzeri ters vekil arkasında uygulama HTTP görür; bu olmadan
    # şifre sıfırlama bağlantısı http:// üretilir ve tarayıcıda kararsız çalışır.
    if app.config.get("TRUST_PROXY", True):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

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
