from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User, Setting

auth_bp = Blueprint("auth", __name__)


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
        next_page = request.args.get("next")
        return redirect(next_page or url_for("main.dashboard"))

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
        if user is None or user.email.lower() != email.lower():
            flash("Kullanıcı adı veya e-posta eşleşmiyor.", "error")
            return render_template("forgot_password.html")

        session["reset_user_id"] = user.id
        return redirect(url_for("auth.reset_password"))

    return render_template("forgot_password.html")


@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    user_id = session.get("reset_user_id")
    if not user_id:
        flash("Önce kullanıcı adı ve e-posta doğrulaması yapın.", "error")
        return redirect(url_for("auth.forgot_password"))

    user = db.session.get(User, user_id)
    if user is None:
        session.pop("reset_user_id", None)
        flash("Kullanıcı bulunamadı.", "error")
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
            db.session.commit()
            session.pop("reset_user_id", None)
            flash("Şifreniz güncellendi. Giriş yapabilirsiniz.", "success")
            return redirect(url_for("auth.login"))

    return render_template("reset_password.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
