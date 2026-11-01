"""EO Analytics - Space-Tech Farming web application."""
import logging
import secrets

from flask import Flask, abort, request, session

from .config import INSTANCE_DIR, Config
from .models import db


def create_app(overrides=None):
    app = Flask(__name__, instance_path=str(INSTANCE_DIR), instance_relative_config=False)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db.init_app(app)

    from .services.satellite import SatelliteService

    app.extensions["satellite"] = SatelliteService(
        app.config, app.config.get("CACHE_DIR", INSTANCE_DIR / "imagery_cache")
    )

    from .admin import bp as admin_bp
    from .api import bp as api_bp
    from .auth import bp as auth_bp
    from .views import bp as views_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    _csrf(app)
    _errors(app)

    from .cli import register_cli

    register_cli(app)

    with app.app_context():
        db.create_all()

    return app


def _csrf(app):
    """Minimal CSRF protection: every form/fetch that changes data must echo a session token."""

    def token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_urlsafe(32)
        return session["_csrf"]

    app.jinja_env.globals["csrf_token"] = token

    @app.before_request
    def check():
        if app.config.get("TESTING") and app.config.get("WTF_CSRF_DISABLED", True):
            return
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
            if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
                abort(400, "Your session expired. Please reload the page and try again.")


def _errors(app):
    from flask import jsonify, render_template
    from werkzeug.exceptions import HTTPException

    @app.errorhandler(HTTPException)
    def handle(exc):
        message = exc.description if exc.code == 400 else {
            403: "You do not have access to this page.",
            404: "We couldn't find that page.",
            405: "That action isn't allowed here.",
        }.get(exc.code, exc.description)
        if request.path.startswith("/api/"):
            return jsonify({"error": message}), exc.code
        return render_template("error.html", code=exc.code, message=message), exc.code
