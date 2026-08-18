from flask import Blueprint, render_template, redirect, url_for, request, flash
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


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
