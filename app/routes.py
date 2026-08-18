from flask import Blueprint, render_template, send_from_directory
from flask_login import login_required, current_user

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required
def dashboard():
    return render_template("dashboard.html")


@main_bp.route("/cards")
@login_required
def cards():
    return render_template("cards.html")


@main_bp.route("/cards/new")
@login_required
def new_card():
    return render_template("card_form.html", card=None, card_id=None)


@main_bp.route("/cards/<int:card_id>")
@login_required
def card_detail(card_id):
    return render_template("card_detail.html", card_id=card_id)


@main_bp.route("/cards/<int:card_id>/edit")
@login_required
def card_edit(card_id):
    return render_template("card_form.html", card_id=card_id)


@main_bp.route("/payments")
@login_required
def payments():
    return render_template("payments.html")


@main_bp.route("/settings")
@login_required
def settings():
    return render_template("settings.html")


@main_bp.route("/notifications")
@login_required
def notifications():
    return render_template("notifications.html")


@main_bp.route("/sw.js")
def service_worker():
    return send_from_directory("static/js", "sw.js", mimetype="application/javascript")
