import hashlib
import hmac
import secrets

from flask import Blueprint, render_template, redirect, url_for, request, flash, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User, Setting
from app.date_utils import get_utc_now

auth_bp = Blueprint("auth", __name__)

RESET_TOKEN_TTL_SECONDS = 30 * 60
PASSWORD_RESET_SUBJECT = "Kredi Kartı Takip - Şifre Sıfırlama"
RESET_TOKEN_ISSUER = "kredi-kart-takip"
NEUTRAL_RESET_MESSAGE = (
    "Eğer bu bilgiler kayıtlıysa sıfırlama bağlantısı e-postanıza gönderildi."
)


def _safe_next_url(target):
    """Yalnızca site içi göreli yollara izin ver (open redirect koruması)."""
    if not target:
        return None
    if not target.startswith("/") or target.startswith("//"):
        return None
    if "\\" in target or ":" in target.split("/", 1)[0]:
        return None
    return target


def _hash_reset_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _issue_reset_token(user):
    token = secrets.token_urlsafe(32)
    user.reset_token_hash = _hash_reset_token(token)
    user.reset_token_expires_at = get_utc_now().timestamp() + RESET_TOKEN_TTL_SECONDS
    return token


def _consume_reset_token(user, token):
    if user is None or not user.reset_token_hash or not token:
        return False
    if not user.reset_token_expires_at or user.reset_token_expires_at < get_utc_now().timestamp():
        return False
    return hmac.compare_digest(user.reset_token_hash, _hash_reset_token(token))


def _clear_reset_token(user):
    user.reset_token_hash = None
    user.reset_token_expires_at = None


def _send_reset_email(user, token):
    """E-posta gönderimi. SMTP yapılandırılmamışsa bağlantı bilgileri konsola yazılır."""
    reset_url = url_for(
        "auth.reset_password",
        token=token,
        _external=True,
        _scheme="https" if request.is_secure else "http",
    )
    body = (
        f"Merhaba {user.username},\n\n"
        f"Şifre sıfırlama bağlantınız (geçerlilik {RESET_TOKEN_TTL_SECONDS // 60} dakika):\n"
        f"{reset_url}\n\n"
        "Bu isteği siz yapmadıysanız bu e-postayı yok sayabilirsiniz.\n"
    )

    smtp_server = current_app.config.get("MAIL_SERVER")
    if not smtp_server:
        current_app.logger.warning(
            "MAIL_SERVER tanimli degil. Sifre sifirlama baglantisi: %s", reset_url
        )
        return False

    import smtplib
    from email.message import EmailMessage

    message = EmailMessage()
    message["Subject"] = PASSWORD_RESET_SUBJECT
    message["From"] = current_app.config["MAIL_DEFAULT_SENDER"]
    message["To"] = user.email
    message.set_content(body)

    with smtplib.SMTP(
        current_app.config["MAIL_SERVER"],
        current_app.config.get("MAIL_PORT", 587),
        timeout=current_app.config.get("MAIL_TIMEOUT", 10),
    ) as smtp:
        smtp.starttls()
        smtp.login(
            current_app.config["MAIL_USERNAME"],
            current_app.config["MAIL_PASSWORD"],
        )
        smtp.send_message(message)
    return True


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        if user is None or not user.check_password(password):
            flash("Kullanıcı adı veya şifre hatalı.", "error")
            return render_template("login.html")

        login_user(user)
        return redirect(_safe_next_url(request.args.get("next")) or url_for("main.dashboard"))

    return render_template("login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")

        errors = []
        if not username:
            errors.append("Kullanıcı adı gerekli.")
        if not email:
            errors.append("E-posta gerekli.")
        if len(password) < 4:
            errors.append("Şifre en az 4 karakter olmalı.")
        if password != password2:
            errors.append("Şifreler eşleşmiyor.")
        if User.query.filter_by(username=username).first():
            errors.append("Bu kullanıcı adı zaten var.")
        if User.query.filter_by(email=email).first():
            errors.append("Bu e-posta zaten kayıtlı.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("register.html")

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)

        setting = Setting(user=user)
        db.session.add(setting)

        db.session.commit()

        flash("Hesabınız oluşturuldu. Giriş yapabilirsiniz.", "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html")


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()

        user = User.query.filter_by(username=username).first()
        matched = user is not None and hmac.compare_digest(user.email.lower(), email.lower())

        if not matched:
            # Kullanıcı var/yok bilgisi sızdırmadan aynı yanıt verilir.
            flash(NEUTRAL_RESET_MESSAGE, "success")
            return render_template("forgot_password.html")

        token = _issue_reset_token(user)
        db.session.commit()

        _send_reset_email(user, token)
        flash(NEUTRAL_RESET_MESSAGE, "success")
        return render_template("forgot_password.html")

    return render_template("forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = User.query.filter(
        User.reset_token_hash == _hash_reset_token(token)
    ).first()

    if not _consume_reset_token(user, token):
        flash("Sıfırlama bağlantısı geçersiz veya süresi dolmuş.", "error")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")

        if len(password) < 4:
            flash("Şifre en az 4 karakter olmalı.", "error")
        elif password != password2:
            flash("Şifreler eşleşmiyor.", "error")
        else:
            user.set_password(password)
            _clear_reset_token(user)
            db.session.commit()
            flash("Şifreniz güncellendi. Giriş yapabilirsiniz.", "success")
            return redirect(url_for("auth.login"))

    return render_template("reset_password.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
