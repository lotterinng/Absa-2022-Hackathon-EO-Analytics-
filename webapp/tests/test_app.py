"""End-to-end tests of the main use cases (run with:  pytest)."""
import json
from datetime import date, timedelta

import pytest

from eo_analytics import api as api_module
from eo_analytics import create_app
from eo_analytics.models import Activity, Field, Reading, User, db
from eo_analytics.services import geo, insights
from eo_analytics.services.satellite import SatelliteUnavailable
from eo_analytics.services.weather import WeatherUnavailable

from .fake_satellite import FakeProvider

SQUARE = {"type": "Polygon", "coordinates": [[[26.0115, -24.4262], [26.0168, -24.4258],
                                              [26.0172, -24.4301], [26.0119, -24.4306], [26.0115, -24.4262]]]}


def fake_weather(lat, lon, timeout=20):
    today = date.today()
    days = [{"date": (today + timedelta(days=i)).isoformat(), "code": 61, "tmax": 30, "tmin": 15,
             "rain_mm": 2.0, "rain_chance": 40, "et0_mm": 5, "soil_moisture": 0.2,
             "description": "Light rain", "icon": "rain"} for i in range(-92, 8)]
    return {"source": "open-meteo",
            "current": {"time": today.isoformat() + "T12:00", "temperature": 25, "humidity": 40,
                        "wind_kmh": 10, "code": 0, "rain_mm": 0, "description": "Clear sky", "icon": "sun"},
            "past": [d for d in days if d["date"] < today.isoformat()],
            "forecast": [d for d in days if d["date"] >= today.isoformat()]}


@pytest.fixture()
def app(tmp_path, monkeypatch):
    """The app with the satellite and weather services replaced by offline stand-ins,
    so the tests run without internet. The real app never uses these."""
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        "NEWS_FEEDS": [],
        "CACHE_DIR": tmp_path / "cache",
        "ADMIN_EMAIL": "boss@example.com",
    })
    app.extensions["satellite"].provider = FakeProvider()
    monkeypatch.setattr(api_module, "get_weather", fake_weather)
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def register(client, email="farmer@example.com", pw="secret123", name="Neo Farmer"):
    return client.post("/register", data={"full_name": name, "email": email, "password": pw, "confirm": pw})


def login(client, email="farmer@example.com", pw="secret123"):
    return client.post("/login", data={"email": email, "password": pw})


def test_register_login_logout(client):
    assert register(client).status_code == 302
    r = register(client)
    assert b"already exists" in r.data
    assert b"Invalid email" in login(client, pw="wrong").data
    r = login(client)
    assert r.status_code == 302 and r.headers["Location"] == "/"
    assert b"Dumela, Neo" in client.get("/").data
    client.post("/logout")
    assert client.get("/").status_code == 302


def test_register_validation(client):
    r = client.post("/register", data={"full_name": "A", "email": "bad", "password": "secret123", "confirm": "secret123"})
    assert b"Invalid email" in r.data
    r = client.post("/register", data={"full_name": "A", "email": "a@b.co", "password": "secret123", "confirm": "nope12345"})
    assert b"do not match" in r.data


def test_password_reset(client, app):
    register(client)
    r = client.post("/forgot", data={"email": "farmer@example.com"})
    with app.app_context():
        token = User.query.filter_by(email="farmer@example.com").first().reset_token
    assert token and token.encode() in r.data  # shown because no mail server is configured
    r = client.post(f"/reset/{token}", data={"password": "newpass123", "confirm": "newpass123"})
    assert r.status_code == 302
    assert login(client, pw="newpass123").status_code == 302
    assert client.get(f"/reset/{token}").status_code == 302  # token used up


def test_fields_crud_and_ownership(client):
    register(client); login(client)
    r = client.post("/api/fields", json={"name": "Block A", "crop": "Maize", "geometry": SQUARE, "expected_yield_t_ha": 3})
    assert r.status_code == 201, r.json
    f = r.json
    assert 20 < f["area_ha"] < 30
    r = client.post("/api/fields", json={"name": "Tiny", "geometry": {"type": "Polygon", "coordinates": [[[26, -24], [26.00001, -24], [26, -24.00001], [26, -24]]]}})
    assert r.status_code == 400 and "too small" in r.json["error"]
    r = client.put(f"/api/fields/{f['id']}", json={**f, "name": "Block B"})
    assert r.json["name"] == "Block B"
    client.post("/logout")
    register(client, "other@example.com"); login(client, "other@example.com")
    assert client.get(f"/api/fields/{f['id']}/analysis").status_code == 404  # not their field
    assert client.delete(f"/api/fields/{f['id']}").status_code == 404


def test_satellite_analysis_and_cache(client, app):
    register(client); login(client)
    fid = client.post("/api/fields", json={"name": "A", "crop": "Maize", "geometry": SQUARE}).json["id"]
    for index in ("ndvi", "ndmi"):
        r = client.get(f"/api/fields/{fid}/analysis?index={index}")
        assert r.status_code == 200, r.json
        d = r.json
        assert d["source"] == "sentinel-2" and d["reading"][index] is not None
        assert d["overlay"]["image"].startswith("data:image/png;base64,")
        assert sum(d["reading"][index + "_classes"].values()) == pytest.approx(100, abs=0.5)
        assert d["recommendation"]
    with app.app_context():
        n = Reading.query.count()
    client.get(f"/api/fields/{fid}/analysis?index=ndvi")
    with app.app_context():
        assert Reading.query.count() == n  # served from cache
    ts = client.get(f"/api/fields/{fid}/timeseries").json
    assert len(ts["readings"]) >= 8 and ts["analysis"]["ndvi"] and ts["soil"]
    y = client.get("/api/yield").json
    assert y["fields"][0]["status"] in ("ok", "no-crop", "no-data") and y["recommendation"]


def test_editing_geometry_clears_cache(client, app):
    register(client); login(client)
    f = client.post("/api/fields", json={"name": "A", "crop": "Maize", "geometry": SQUARE}).json
    client.get(f"/api/fields/{f['id']}/analysis")
    moved = json.loads(json.dumps(SQUARE))
    moved["coordinates"][0][1][0] += 0.001
    client.put(f"/api/fields/{f['id']}", json={**f, "geometry": moved})
    with app.app_context():
        assert Reading.query.filter_by(field_id=f["id"]).count() == 0


def test_pages_render(client):
    register(client); login(client)
    assert client.get("/my-farm").status_code == 302  # no fields yet -> sent to draw one
    client.post("/api/fields", json={"name": "A", "crop": "Maize", "geometry": SQUARE})
    for url in ("/", "/fields", "/my-farm", "/my-farm?tab=yield", "/statistics", "/weather", "/news", "/help", "/account"):
        assert client.get(url).status_code == 200, url
    assert client.get("/admin/").status_code == 302  # farmers can't see admin


def test_admin_block_delete_and_news(client, app):
    register(client, "boss@example.com", name="Boss")  # ADMIN_EMAIL -> admin
    register(client)
    login(client)
    client.post("/api/fields", json={"name": "A", "crop": "Maize", "geometry": SQUARE})
    client.post("/logout")
    login(client, "boss@example.com")
    assert b"farmer@example.com" in client.get("/admin/").data
    with app.app_context():
        farmer = User.query.filter_by(email="farmer@example.com").first().id
    client.post(f"/admin/users/{farmer}/block")
    client.post("/logout")
    assert b"blocked" in login(client).data
    login(client, "boss@example.com")
    client.post("/admin/news/new", data={"title": "Rain is coming", "category": "Top News", "body": "Prepare.", "published": "on"})
    assert b"Rain is coming" in client.get("/news").data
    client.post(f"/admin/users/{farmer}/delete")
    with app.app_context():
        assert db.session.get(User, farmer) is None
        assert Field.query.count() == 0
        assert Activity.query.filter_by(action="deleted user").count() == 1
    assert client.get("/admin/activity").status_code == 200


def test_csrf_enforced(tmp_path):
    app = create_app({"TESTING": True, "WTF_CSRF_DISABLED": False,
                      "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'c.db'}", "CACHE_DIR": tmp_path})
    c = app.test_client()
    assert c.post("/login", data={"email": "x@y.z", "password": "p"}).status_code == 400


def test_geometry_helpers():
    assert geo.area_hectares(SQUARE) == pytest.approx(26.2, rel=0.02)
    lat, lon = geo.centroid(SQUARE)
    assert -24.431 < lat < -24.426 and 26.011 < lon < 26.018
    with pytest.raises(geo.GeometryError):
        geo.outer_ring({"type": "Point", "coordinates": [0, 0]})


def test_yield_estimate_rules():
    class F:  # minimal stand-in for a Field
        id, name, crop, area_ha, expected_yield_t_ha, planting_date = 1, "A", "Maize", 10, 2.0, None
    from datetime import date, timedelta
    today = date.today()
    good = [{"date": (today - timedelta(days=d)).isoformat(), "ndvi": v} for d, v in ((40, 0.5), (30, 0.7), (20, 0.8), (10, 0.79))]
    est = insights.yield_estimate(F, good, today)
    assert est["status"] == "ok" and est["current_pct"] >= 90
    bare = [{"date": (today - timedelta(days=d)).isoformat(), "ndvi": 0.18} for d in (30, 20, 10)]
    assert insights.yield_estimate(F, bare, today)["status"] == "no-crop"


def test_satellite_outage_shows_error_not_fake_data(client, app):
    class Down:
        name = "sentinel-2"

        def list_scenes(self, *a):
            raise SatelliteUnavailable("Cannot reach the Sentinel-2 satellite service right now.")

    register(client); login(client)
    fid = client.post("/api/fields", json={"name": "A", "crop": "Maize", "geometry": SQUARE}).json["id"]
    app.extensions["satellite"].provider = Down()
    r = client.get(f"/api/fields/{fid}/analysis")
    assert r.status_code == 503 and "satellite" in r.json["error"]
    assert client.get(f"/api/fields/{fid}/timeseries").status_code == 503
    with app.app_context():
        assert Reading.query.count() == 0


def test_weather_outage_shows_error(client, monkeypatch):
    def down(*a, **k):
        raise WeatherUnavailable("Cannot reach the weather service right now.")

    monkeypatch.setattr(api_module, "get_weather", down)
    register(client); login(client)
    r = client.get("/api/weather")
    assert r.status_code == 503 and "weather" in r.json["error"]


def test_real_provider_reads_sentinel2_files(tmp_path):
    """Run the real Planetary Computer code on small local GeoTIFFs laid out exactly like
    Sentinel-2 L2A (UTM, 10 m and 20 m bands, +1000 offset). Two tiles cover the same day:
    the first has no data over the field, so the provider must use the second."""
    rasterio = pytest.importorskip("rasterio")
    import numpy as np
    from types import SimpleNamespace as NS

    from rasterio.transform import from_origin
    from rasterio.warp import transform_bounds

    from eo_analytics.services.satellite import PlanetaryComputerProvider, Scene

    crs = "EPSG:32735"
    b = transform_bounds("EPSG:4326", crs, 25.99, -24.45, 26.04, -24.41)
    x0, y1 = b[0] // 20 * 20, (b[3] // 20 + 1) * 20
    w10, h10 = int((b[2] - x0) // 10) + 2, int((y1 - b[1]) // 10) + 2
    xx = np.mgrid[0:h10, 0:w10][1]

    def tile(name, scl_value):
        folder = tmp_path / name
        folder.mkdir()

        def write(band, arr, res):
            with rasterio.open(folder / f"{band}.tif", "w", driver="GTiff", width=arr.shape[1],
                               height=arr.shape[0], count=1, dtype="uint16", crs=crs,
                               transform=from_origin(x0, y1, res, res)) as dst:
                dst.write(arr, 1)

        write("B04", np.full((h10, w10), 500 + 1000, np.uint16), 10)
        write("B08", (np.where(xx < w10 // 2, 4000, 2000) + 1000).astype(np.uint16), 10)
        write("B11", np.full((h10 // 2, w10 // 2), 2000 + 1000, np.uint16), 20)
        write("SCL", np.full((h10 // 2, w10 // 2), scl_value, np.uint16), 20)
        return NS(id=name, properties={"s2:processing_baseline": "05.10", "eo:cloud_cover": 1},
                  assets={k: NS(href=str(folder / f"{k}.tif")) for k in ("B04", "B08", "B11", "SCL")})

    empty, good = tile("EMPTY_TILE", 0), tile("GOOD_TILE", 4)  # SCL 0 = no data, 4 = vegetation
    scene = Scene(id="x", date=date.today(), cloud_cover=1, payload=[empty, good])
    arrays = PlanetaryComputerProvider().compute(SQUARE, scene)
    assert scene.id == "GOOD_TILE" and arrays.clear_fraction > 0.99
    ndvi = arrays.ndvi[np.isfinite(arrays.ndvi)]
    assert ndvi.max() == pytest.approx((0.40 - 0.05) / 0.45, abs=0.005)  # offset removed correctly
    assert ndvi.min() == pytest.approx((0.20 - 0.05) / 0.25, abs=0.005)
    ndmi = arrays.ndmi[np.isfinite(arrays.ndmi)]
    assert ndmi.max() == pytest.approx((0.40 - 0.20) / 0.60, abs=0.005)
