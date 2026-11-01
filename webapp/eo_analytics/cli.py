"""Command-line helpers:

    flask --app eo_analytics create-admin you@example.com
    flask --app eo_analytics seed-sample
"""
import json

import click

from .models import Article, Field, User, db
from .services import geo

# Three real locations near Bokaa, Botswana (the study area used in the hackathon notebooks).
# Their maps come from real Sentinel-2 imagery of these places.
SAMPLE_FIELDS = [
    ("North maize block", "Maize", 2.8, [[26.0115, -24.4262], [26.0168, -24.4258], [26.0172, -24.4301], [26.0119, -24.4306]]),
    ("Sorghum strip", "Sorghum", 1.6, [[26.0185, -24.4270], [26.0215, -24.4268], [26.0218, -24.4318], [26.0188, -24.4320]]),
    ("Sweet reed plot", "Sweet reed", 15.0, [[26.0120, -24.4318], [26.0160, -24.4316], [26.0163, -24.4345], [26.0122, -24.4347]]),
]

HELP_ARTICLES = [
    ("Farming Basics", "How to read your Crop Health map",
     "Red means weak growth, green to blue means strong, healthy crops.",
     "The Crop Health map is built from the Normalised Difference Vegetation Index (NDVI). Healthy green "
     "leaves reflect a lot of near-infrared light and absorb red light, so NDVI rises as the crop canopy "
     "grows.\n\nOn the map, red and orange areas have little green growth, yellow is moderate, and green "
     "to blue areas are growing strongly. Early in the season most of the field will be red because the "
     "soil is still bare - this is normal.\n\nWhen part of a field stays red while the rest turns green, walk "
     "to that spot. Common causes are poor germination, waterlogging, pests, weeds or a nutrient shortage."),
    ("Farming Basics", "Using the Soil Moisture view to plan irrigation",
     "The moisture map shows which parts of the field are drying first.",
     "The Soil Moisture view uses the Normalised Difference Moisture Index (NDMI), which compares "
     "near-infrared and short-wave infrared light from Sentinel-2. It responds to water in the crop "
     "canopy and the soil surface.\n\nRed and orange areas are drier. If they match the weak areas on the "
     "Crop Health map, water stress is the likely cause. Check the Weather page before irrigating - "
     "if good rain is forecast in the next few days you may be able to wait.\n\nThe Statistics page also "
     "shows modelled soil moisture (3-9 cm depth) and daily rainfall for your location."),
    ("Tech", "Where do the satellite images come from?",
     "EO Analytics uses free Sentinel-2 images from the European Space Agency.",
     "Sentinel-2 is a pair of European satellites that photograph every farm on Earth about every five "
     "days at 10 metre detail. EO Analytics reads these images through Microsoft's Planetary Computer, "
     "removes cloudy pixels and calculates crop health and moisture just for the area you drew.\n\n"
     "Because the satellites cannot see through cloud, there can be gaps of a week or more during the "
     "rainy season. Results are saved, so pages load quickly the next time you open them."),
    ("Business", "Estimating yield before harvest",
     "How the Crop Yield tab works and how to make it more accurate.",
     "The Crop Yield tab compares how green each field became this season with how green a healthy, "
     "well-managed crop of the same type usually gets. The result is shown as a percentage of the yield "
     "you expect.\n\nTo improve the estimate, open My Fields and enter the planting date and the yield you "
     "normally expect per hectare. The estimate is a guide for planning (for example for input loans or "
     "sales) - it is not a guarantee."),
]


def register_cli(app):
    @app.cli.command("create-admin")
    @click.argument("email")
    @click.option("--name", default="Administrator")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(email, name, password):
        """Create an administrator (or promote an existing user)."""
        email = email.strip().lower()
        user = User.query.filter_by(email=email).first()
        if user is None:
            user = User(full_name=name, email=email)
            db.session.add(user)
        user.set_password(password)
        user.is_admin = True
        user.is_blocked = False
        db.session.commit()
        click.echo(f"{email} is now an administrator.")

    @app.cli.command("seed-sample")
    def seed_sample():
        """Add a sample farmer with three fields near Bokaa, an admin and starter help articles.

        The fields are real locations; their maps come from real Sentinel-2 imagery."""
        _seed()
        click.echo("Sample accounts ready.  Farmer: farmer@demo.bw / farmer123   Admin: admin@demo.bw / admin1234")


def _seed():
    admin = User.query.filter_by(email="admin@demo.bw").first()
    if admin is None:
        admin = User(full_name="EO Admin", email="admin@demo.bw", is_admin=True)
        admin.set_password("admin1234")
        db.session.add(admin)
    farmer = User.query.filter_by(email="farmer@demo.bw").first()
    if farmer is None:
        farmer = User(full_name="Kagiso Molefe", email="farmer@demo.bw", phone="+267 71 234 567")
        farmer.set_password("farmer123")
        db.session.add(farmer)
        db.session.flush()
        for name, crop, expected, ring in SAMPLE_FIELDS:
            geometry = {"type": "Polygon", "coordinates": [ring + [ring[0]]]}
            lat, lon = geo.centroid(geometry)
            db.session.add(Field(
                user_id=farmer.id, name=name, crop=crop, geometry=json.dumps(geometry),
                area_ha=geo.area_hectares(geometry), centroid_lat=lat, centroid_lon=lon,
                expected_yield_t_ha=expected,
            ))
    if Article.query.count() == 0:
        for category, title, summary, body in HELP_ARTICLES:
            db.session.add(Article(category=category, title=title, summary=summary, body=body,
                                   author_id=admin.id if admin.id else None))
    db.session.commit()
