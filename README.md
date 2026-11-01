# Absa-2022-Hackathon-EO-Analytics-
This is a repository of the Earth Observation Application that was designed for the Absa BW Agric Hackathon
/Code
/Technical

## Web application

The working web app is in [`webapp/`](webapp/). It implements the storyboard and screens in
`Non Technical/`: sign up and sign in, draw your field on a satellite map, Crop Health and
Soil Moisture maps from real Sentinel-2 imagery, Crop Yield estimate, 3-month Statistics,
Weather, Agric News and an Admin panel.

Quick start:

```bash
cd webapp
pip install -r requirements.txt
flask --app wsgi seed-sample
python wsgi.py          # then open http://localhost:5000
```

See [`webapp/README.md`](webapp/README.md) for details and hosting.

