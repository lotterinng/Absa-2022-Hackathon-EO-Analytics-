"""Register, sign in, sign out and password reset (use cases from the System Analysis)."""
import logging
import re
import secrets
import smtplib
from datetime import timedelta
from email.message import EmailMessage
from functools import wraps

from flask import (
    Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for,
)

from .models import User, db, log_activity, utcnow

bp = Blueprint("auth", __name__)
log = logging.getLogger(__name__)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@bp.before_app_request
def load_user():
    uid = session.get("user_id")
    g.user = db.session.get(User, uid) if uid else None
    if g.user is not None and g.user.is_blocked:
        session.clear()
        g.user = None
        flash("Your account has been blocked. Please contact the administrator.", "error")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if request.path.startswith("/api/"):
                return {"error": "Please sign in."}, 401
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not g.user.is_admin:
            flash("Administrator access only.", "error")
            return redirect(url_for("views.home"))
        return view(*args, **kwargs)

    return wrapped


def _safe_next(target):
    return target if target and target.startswith("/") and not target.startswith("//") else None


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("views.home"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user is None or not user.check_password(password):
            flash("Invalid email or password.", "error")
        elif user.is_blocked:
            flash("Your account has been blocked. Please contact the administrator.", "error")
        else:
            session.clear()
            session["user_id"] = user.id
            session.permanent = True
            user.last_login = utcnow()
            db.session.commit()
            log_activity(user, "login")
            return redirect(_safe_next(request.args.get("next")) or url_for("views.home"))
    return render_template("auth/login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("views.home"))
    form = request.form
    if request.method == "POST":
        name = form.get("full_name", "").strip()
        email = form.get("email", "").strip().lower()
        phone = form.get("phone", "").strip()
        pw, pw2 = form.get("password", ""), form.get("confirm", "")
        error = None
        if not name:
            error = "Please enter your name."
        elif not EMAIL_RE.match(email):
            error = "Invalid email address."
        elif len(pw) < 8:
            error = "Password must be at least 8 characters."
        elif pw != pw2:
            error = "Passwords do not match."
        elif User.query.filter_by(email=email).first():
            error = "An account with this email already exists."
        if error:
            flash(error, "error")
        else:
            admin_email = current_app.config.get("ADMIN_EMAIL")
            user = User(
                full_name=name, email=email, phone=phone or None,
                is_admin=bool(admin_email and email == admin_email),
            )
            user.set_password(pw)
            db.session.add(user)
            db.session.commit()
            log_activity(user, "register")
            flash("Account created. Please sign in.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form=form)


@bp.route("/logout", methods=["POST"])
def logout():
    if g.user:
        log_activity(g.user, "logout")
    session.clear()
    return redirect(url_for("auth.login"))


def _send_reset_mail(user, link):
    cfg = current_app.config
    if not cfg.get("MAIL_SERVER"):
        return False
    msg = EmailMessage()
    msg["Subject"] = "Reset your EO Analytics password"
    msg["From"] = cfg["MAIL_FROM"]
    msg["To"] = user.email
    msg.set_content(
        f"Hello {user.first_name},\n\nUse this link within 1 hour to choose a new password:\n{link}\n\n"
        "If you did not ask for this you can ignore this email."
    )
    try:
        with smtplib.SMTP(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=15) as s:
            s.starttls()
            if cfg.get("MAIL_USERNAME"):
                s.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
            s.send_message(msg)
        return True
    except Exception as exc:
        log.error("Could not send reset mail: %s", exc)
        return False


@bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    reset_link = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user and not user.is_blocked:
            user.reset_token = secrets.token_urlsafe(32)
            user.reset_expires = utcnow() + timedelta(hours=1)
            db.session.commit()
            link = url_for("auth.reset", token=user.reset_token, _external=True)
            log.info("Password reset link for %s: %s", email, link)
            sent = _send_reset_mail(user, link)
            if not sent and current_app.config.get("SHOW_RESET_LINK"):
                reset_link = link
        # Same message whether or not the account exists, so emails can't be probed.
        flash("If that email is registered, a reset link has been sent.", "success")
    return render_template("auth/forgot.html", reset_link=reset_link)


@bp.route("/reset/<token>", methods=["GET", "POST"])
def reset(token):
    user = User.query.filter_by(reset_token=token).first()
    if user is None or user.reset_expires is None or user.reset_expires < utcnow():
        flash("This reset link is invalid or has expired.", "error")
        return redirect(url_for("auth.forgot"))
    if request.method == "POST":
        pw, pw2 = request.form.get("password", ""), request.form.get("confirm", "")
        if len(pw) < 8:
            flash("Password must be at least 8 characters.", "error")
        elif pw != pw2:
            flash("Passwords do not match.", "error")
        else:
            user.set_password(pw)
            user.reset_token = None
            user.reset_expires = None
            db.session.commit()
            log_activity(user, "password reset")
            flash("Password changed. You can now sign in.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset.html")


@bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        user = g.user
        if not user.check_password(request.form.get("current", "")):
            flash("Current password is incorrect.", "error")
        else:
            pw, pw2 = request.form.get("password", ""), request.form.get("confirm", "")
            name = request.form.get("full_name", "").strip()
            if name:
                user.full_name = name
            user.phone = request.form.get("phone", "").strip() or None
            if pw:
                if len(pw) < 8 or pw != pw2:
                    flash("New passwords must match and be at least 8 characters.", "error")
                    return render_template("auth/account.html")
                user.set_password(pw)
            db.session.commit()
            log_activity(user, "account updated")
            flash("Account updated.", "success")
    return render_template("auth/account.html")
