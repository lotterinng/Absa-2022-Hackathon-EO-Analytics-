"""Database tables.

User      - farmers and administrators
Field     - a farm field drawn on the map (one crop per field)
Reading   - cached satellite result for one field on one image date
Article   - Agric News posts written by administrators
Activity  - audit trail the administrator can view
"""
import json
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(40))
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_blocked = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    last_login = db.Column(db.DateTime)
    reset_token = db.Column(db.String(64), index=True)
    reset_expires = db.Column(db.DateTime)

    fields = db.relationship("Field", backref="owner", cascade="all, delete-orphan")
    activities = db.relationship("Activity", backref="user", cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def first_name(self):
        return (self.full_name or "").split(" ")[0]


class Field(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    crop = db.Column(db.String(60), nullable=False, default="Maize")
    geometry = db.Column(db.Text, nullable=False)  # GeoJSON Polygon, lon/lat
    area_ha = db.Column(db.Float, nullable=False)
    centroid_lat = db.Column(db.Float, nullable=False)
    centroid_lon = db.Column(db.Float, nullable=False)
    expected_yield_t_ha = db.Column(db.Float)  # what the farmer expects per hectare
    planting_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=utcnow)

    readings = db.relationship(
        "Reading", backref="field", cascade="all, delete-orphan", order_by="Reading.date"
    )

    @property
    def geojson(self):
        return json.loads(self.geometry)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "crop": self.crop,
            "geometry": self.geojson,
            "area_ha": round(self.area_ha, 2),
            "centroid": [self.centroid_lat, self.centroid_lon],
            "expected_yield_t_ha": self.expected_yield_t_ha,
            "planting_date": self.planting_date.isoformat() if self.planting_date else None,
        }


class Reading(db.Model):
    """Field-average index values for one satellite pass (cached so we only download once)."""

    id = db.Column(db.Integer, primary_key=True)
    field_id = db.Column(db.Integer, db.ForeignKey("field.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False)
    source = db.Column(db.String(30), nullable=False)  # "sentinel-2" or "demo"
    scene_id = db.Column(db.String(120))
    ndvi_mean = db.Column(db.Float)
    ndmi_mean = db.Column(db.Float)
    clear_fraction = db.Column(db.Float)
    ndvi_classes = db.Column(db.Text)  # JSON {"poor": %, "medium": %, "good": %}
    ndmi_classes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow)

    __table_args__ = (db.UniqueConstraint("field_id", "date", "source"),)

    def to_dict(self):
        return {
            "date": self.date.isoformat(),
            "source": self.source,
            "scene_id": self.scene_id,
            "ndvi": None if self.ndvi_mean is None else round(self.ndvi_mean, 3),
            "ndmi": None if self.ndmi_mean is None else round(self.ndmi_mean, 3),
            "clear_fraction": None if self.clear_fraction is None else round(self.clear_fraction, 2),
            "ndvi_classes": json.loads(self.ndvi_classes) if self.ndvi_classes else None,
            "ndmi_classes": json.loads(self.ndmi_classes) if self.ndmi_classes else None,
        }


class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(40), nullable=False, default="Top News")
    summary = db.Column(db.String(400))
    body = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(500))
    link = db.Column(db.String(500))
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    published = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    @property
    def read_minutes(self):
        return max(1, round(len((self.body or "").split()) / 200))


class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    action = db.Column(db.String(60), nullable=False)
    detail = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=utcnow, index=True)


def log_activity(user, action, detail=None):
    db.session.add(Activity(user_id=user.id if user else None, action=action, detail=detail))
    db.session.commit()
