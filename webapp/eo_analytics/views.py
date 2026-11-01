"""Page routes. Pages are thin; the data is loaded by JavaScript from /api."""
from flask import Blueprint, abort, current_app, g, redirect, render_template, request, url_for

from .auth import login_required
from .models import Article, db, log_activity
from .services.insights import CROPS
from .services.news import CATEGORIES, fetch_feed

bp = Blueprint("views", __name__)


@bp.app_context_processor
def inject():
    return {"crops": CROPS}


@bp.route("/")
def home():
    if g.user is None:
        return redirect(url_for("auth.login"))
    return render_template("home.html")


@bp.route("/fields")
@login_required
def fields():
    return render_template("fields.html")


@bp.route("/my-farm")
@login_required
def my_farm():
    if not g.user.fields:
        return redirect(url_for("views.fields", first=1))
    log_activity(g.user, "viewed my farm")
    return render_template("my_farm.html", tab=request.args.get("tab", "health"))


@bp.route("/statistics")
@login_required
def statistics():
    if not g.user.fields:
        return redirect(url_for("views.fields", first=1))
    return render_template("statistics.html", tab=request.args.get("tab", "health"))


@bp.route("/weather")
@login_required
def weather():
    return render_template("weather.html")


@bp.route("/news")
@login_required
def news():
    category = request.args.get("category", "Top News")
    q = request.args.get("q", "").strip()
    query = Article.query.filter_by(published=True)
    if category in CATEGORIES and category != "Top News":
        query = query.filter_by(category=category)
    if q:
        like = f"%{q}%"
        query = query.filter(Article.title.ilike(like) | Article.body.ilike(like))
    articles = query.order_by(Article.created_at.desc()).all()
    external = []
    if category == "Top News":
        for url in current_app.config["NEWS_FEEDS"]:
            external.extend(fetch_feed(url, timeout=current_app.config["HTTP_TIMEOUT"]))
        if q:
            external = [e for e in external if q.lower() in (e["title"] + e["summary"]).lower()]
        external.sort(key=lambda e: e["date"], reverse=True)
    featured = [a for a in articles if a.image_url][:5] or articles[:5]
    return render_template("news.html", articles=articles, external=external[:20], featured=featured,
                           categories=CATEGORIES, category=category, q=q)


@bp.route("/news/<int:article_id>")
@login_required
def article(article_id):
    item = db.session.get(Article, article_id)
    if item is None or (not item.published and not g.user.is_admin):
        abort(404)
    return render_template("article.html", article=item)


@bp.route("/help")
@login_required
def help_page():
    return render_template("help.html")
