"""Administrator screens: view, block and delete users; activity log; manage Agric News."""
from flask import Blueprint, current_app, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func

from .auth import admin_required
from .models import Activity, Article, Field, Reading, User, db, log_activity
from .services.news import CATEGORIES

bp = Blueprint("admin", __name__)


@bp.route("/")
@admin_required
def dashboard():
    q = request.args.get("q", "").strip()
    users = User.query
    if q:
        like = f"%{q}%"
        users = users.filter(User.full_name.ilike(like) | User.email.ilike(like))
    users = users.order_by(User.created_at.desc()).all()
    field_counts = dict(db.session.query(Field.user_id, func.count(Field.id)).group_by(Field.user_id).all())
    area = dict(db.session.query(Field.user_id, func.sum(Field.area_ha)).group_by(Field.user_id).all())
    stats = {
        "users": User.query.count(),
        "blocked": User.query.filter_by(is_blocked=True).count(),
        "fields": Field.query.count(),
        "hectares": round(db.session.query(func.coalesce(func.sum(Field.area_ha), 0)).scalar(), 1),
        "readings": Reading.query.count(),
    }
    recent = Activity.query.order_by(Activity.created_at.desc()).limit(12).all()
    return render_template("admin/dashboard.html", users=users, field_counts=field_counts, area=area,
                           stats=stats, recent=recent, q=q,
                           provider=current_app.extensions["satellite"].config.get("SATELLITE_PROVIDER"))


@bp.post("/users/<int:user_id>/block")
@admin_required
def toggle_block(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        flash("User not found.", "error")
    elif user.id == g.user.id:
        flash("You cannot block your own account.", "error")
    else:
        user.is_blocked = not user.is_blocked
        db.session.commit()
        log_activity(g.user, "blocked user" if user.is_blocked else "unblocked user", user.email)
        flash(f"{user.full_name} {'blocked' if user.is_blocked else 'unblocked'}.", "success")
    return redirect(request.referrer or url_for("admin.dashboard"))


@bp.post("/users/<int:user_id>/delete")
@admin_required
def delete_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        flash("User not found.", "error")
    elif user.id == g.user.id:
        flash("You cannot delete your own account.", "error")
    else:
        sat = current_app.extensions["satellite"]
        for f in user.fields:
            sat.clear_field_cache(f.id)
        email = user.email
        Article.query.filter_by(author_id=user.id).update({"author_id": None})
        db.session.delete(user)
        db.session.commit()
        log_activity(g.user, "deleted user", email)
        flash(f"Account {email} deleted.", "success")
    return redirect(url_for("admin.dashboard"))


@bp.post("/users/<int:user_id>/admin")
@admin_required
def toggle_admin(user_id):
    user = db.session.get(User, user_id)
    if user and user.id != g.user.id:
        user.is_admin = not user.is_admin
        db.session.commit()
        log_activity(g.user, "granted admin" if user.is_admin else "removed admin", user.email)
        flash(f"{user.full_name} is {'now' if user.is_admin else 'no longer'} an administrator.", "success")
    return redirect(request.referrer or url_for("admin.dashboard"))


@bp.route("/users/<int:user_id>")
@admin_required
def user_detail(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("admin.dashboard"))
    activity = Activity.query.filter_by(user_id=user.id).order_by(Activity.created_at.desc()).limit(100).all()
    return render_template("admin/user.html", u=user, activity=activity)


@bp.route("/activity")
@admin_required
def activity():
    rows = Activity.query.order_by(Activity.created_at.desc()).limit(300).all()
    return render_template("admin/activity.html", rows=rows)


@bp.route("/news")
@admin_required
def news_list():
    return render_template("admin/news.html", articles=Article.query.order_by(Article.created_at.desc()).all())


@bp.route("/news/new", methods=["GET", "POST"])
@bp.route("/news/<int:article_id>/edit", methods=["GET", "POST"])
@admin_required
def news_edit(article_id=None):
    item = db.session.get(Article, article_id) if article_id else Article(author_id=g.user.id)
    if item is None:
        flash("Article not found.", "error")
        return redirect(url_for("admin.news_list"))
    if request.method == "POST":
        f = request.form
        item.title = f.get("title", "").strip()
        item.category = f.get("category") if f.get("category") in CATEGORIES else "Top News"
        item.summary = f.get("summary", "").strip()[:400] or None
        item.body = f.get("body", "").strip()
        item.image_url = f.get("image_url", "").strip() or None
        item.link = f.get("link", "").strip() or None
        item.published = bool(f.get("published"))
        if not item.title or not item.body:
            flash("Title and article text are required.", "error")
        else:
            if item.id is None:
                db.session.add(item)
            db.session.commit()
            log_activity(g.user, "saved article", item.title[:200])
            flash("Article saved.", "success")
            return redirect(url_for("admin.news_list"))
    return render_template("admin/news_edit.html", item=item, categories=CATEGORIES)


@bp.post("/news/<int:article_id>/delete")
@admin_required
def news_delete(article_id):
    item = db.session.get(Article, article_id)
    if item:
        db.session.delete(item)
        db.session.commit()
        log_activity(g.user, "deleted article", item.title[:200])
        flash("Article deleted.", "success")
    return redirect(url_for("admin.news_list"))
