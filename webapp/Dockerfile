FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p instance && useradd -m eo && chown -R eo /app
USER eo

EXPOSE 8000
# Satellite downloads can take a while on the first visit to a field, hence the long timeout.
CMD gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 180 wsgi:app
