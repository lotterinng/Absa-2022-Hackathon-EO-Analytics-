# EO Analytics – Web Application

The working web app for the **EO Analytics – Space-Tech Farming** design
(Absa BW Agric Hackathon 2022). It implements the use cases in
`System Analysis.pdf` and the screens in `Non Technical/Screens`.

| Screen | What it does | Data source |
|---|---|---|
| Sign up / Sign in / Reset password | Farmer accounts | Local database |
| Home | My Farm, Statistics, Weather, Agric News tiles | – |
| My Fields | Draw your field on a satellite map, set crop, planting date, expected yield | – |
| My Farm → Crop Health | Latest cloud-free NDVI map of the field + recommendation | Sentinel-2 (10 m) |
| My Farm → Soil Moisture | Latest NDMI moisture map + recommendation (uses rain forecast) | Sentinel-2 + Open-Meteo |
| My Farm → Crop Yield | Rings and cards: estimated yield vs. expected, per field | Sentinel-2 NDVI season peak |
| Statistics | 3-month charts, monthly averages, written analysis, CSV download | Sentinel-2 + Open-Meteo |
| Weather | Now, 7-day forecast, 3-month rainfall, farm tip | Open-Meteo |
| Agric News | Admin-written articles by category + public RSS feeds | Database + RSS |
| Admin | View/search users, block, delete, make admin, activity log, write news | Database |

**No API keys are needed.** Satellite images come free from the European
Sentinel-2 satellites through Microsoft Planetary Computer, and weather from
Open-Meteo. If the server has no internet, the app switches to realistic
*demo data* and shows a yellow "Demo data" note, so it always runs.

---

## 1. Run it on your computer

You need **Python 3.10 or newer**.

```bash
cd webapp
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate

pip install -r requirements.txt
flask --app wsgi seed-demo        # optional: demo farmer, admin, 3 fields, help articles
python wsgi.py
```

Open <http://localhost:5000>.

Demo logins (after `seed-demo`):

* Farmer: `farmer@demo.bw` / `farmer123`
* Admin:  `admin@demo.bw` / `admin1234`

Create your own administrator:

```bash
flask --app wsgi create-admin you@example.com --name "Your Name"
```

> **Windows tip:** if `pip install rasterio` fails, install the rest first
> (`pip install Flask Flask-SQLAlchemy requests numpy Pillow`). The app will
> run on demo satellite data until rasterio is installed.

## 2. Run the tests

```bash
pip install -r requirements-dev.txt
pytest
```

## 3. Put it online

The app is a standard Python web app (`gunicorn wsgi:app`). Any host that runs
Docker or Python works, for example Render, Railway, Fly.io, Azure App Service
or a VPS.

```bash
docker build -t eo-analytics .
docker run -p 8000:8000 -e SECRET_KEY=change-me -v eo-data:/app/instance eo-analytics
```

On a hosting site, set at least `SECRET_KEY` and keep the `instance/` folder on
persistent storage (or set `DATABASE_URL` to a PostgreSQL database; install
`psycopg2-binary` for that).

## 4. Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `SECRET_KEY` | dev value | **Change in production.** Signs login cookies. |
| `DATABASE_URL` | SQLite in `instance/` | Any SQLAlchemy URL, e.g. PostgreSQL |
| `SATELLITE_PROVIDER` | `auto` | `planetary` (real only), `demo`, or `auto` (real, demo if offline) |
| `WEATHER_PROVIDER` | `auto` | `openmeteo`, `demo`, or `auto` |
| `MAX_CLOUD_COVER` | `40` | Skip Sentinel-2 scenes cloudier than this (%) |
| `MIN_CLEAR_FRACTION` | `0.6` | Share of the field that must be cloud-free to use a scene |
| `ADMIN_EMAIL` | – | First account registered with this email becomes admin |
| `NEWS_FEEDS` | FAO + agriculture.com | Comma-separated RSS feeds for Agric News |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM` | – | SMTP for password-reset emails |
| `SHOW_RESET_LINK` | `true` | Without SMTP, show the reset link on screen. Set `false` in production. |
| `SESSION_COOKIE_SECURE` | `false` | Set `true` when served over HTTPS |

## 5. How it works

```
webapp/
├── wsgi.py                  entry point
├── eo_analytics/
│   ├── __init__.py          app factory, CSRF protection, error pages
│   ├── config.py            settings
│   ├── models.py            User, Field, Reading, Article, Activity tables
│   ├── auth.py              register / login / reset / account
│   ├── views.py             page routes
│   ├── api.py               JSON used by the pages (fields, analysis, timeseries, yield, weather)
│   ├── admin.py             admin screens
│   ├── cli.py               create-admin, seed-demo
│   ├── services/
│   │   ├── satellite.py     Sentinel-2 NDVI/NDMI (Planetary Computer) + demo provider, caching, map images
│   │   ├── weather.py       Open-Meteo weather + modelled soil moisture
│   │   ├── insights.py      recommendations, statistics text, yield estimate
│   │   ├── news.py          RSS reader
│   │   └── geo.py           polygon area / centroid
│   ├── templates/           HTML pages
│   └── static/              CSS, JavaScript, Leaflet maps, Chart.js
└── tests/test_app.py
```

**Satellite pipeline.** For each field the server searches the Sentinel-2
Level-2A catalogue for passes in the last 3–6 months with less than 40% cloud,
reads only the small window covering the field (bands B04 red, B08 near-infrared,
B11 short-wave infrared and the SCL cloud mask), removes cloud and shadow
pixels, and computes:

* **NDVI** = (B08 − B04) / (B08 + B04) → *Crop Health*
* **NDMI** = (B08 − B11) / (B08 + B11) → *Soil Moisture* (water in the crop and soil surface)

Field averages are saved in the database and the pixels in `instance/imagery_cache`,
so each image is downloaded only once. The first visit to a new field can take
up to a minute; after that pages load instantly.

**Crop yield** is an indicative estimate: the season's peak NDVI compared with
the peak a healthy crop of that type usually reaches, applied to the farmer's
expected yield. It is a planning aid, not a measured harvest. A trained
model (like `Classification_Absa.ipynb`) could replace it once labelled yield
data is available.

**Compared with the hackathon prototype.** `Codes/Python_Modules/Soil Moisture`
was a Google Earth Engine script that needed an Earth Engine account and only
ran inside the Earth Engine Code Editor. The same idea (draw a polygon, NDVI
time chart, click a date to see the map, red→blue colour ramp) is now part of a
normal web app that any farmer can sign up to.
