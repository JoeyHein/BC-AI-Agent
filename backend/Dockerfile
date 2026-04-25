FROM python:3.12-slim

WORKDIR /app

# Install system deps for psycopg2 + fonts for shop-drawing PDF rendering.
# fonts-liberation provides LiberationSans-Regular.ttf (referenced by the
# ezdxf "Standard" text style); fonts-dejavu-core is matplotlib's default
# fallback. Without these, ezdxf's matplotlib backend can't find any TTF
# on disk and renders all TEXT/MTEXT entities as empty bounding-box outlines.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    fonts-liberation \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run DB migrations then start Gunicorn with 4 Uvicorn workers
CMD ["sh", "-c", "alembic upgrade head && gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4 --bind 0.0.0.0:8000 --timeout 120 --access-logfile - --error-logfile -"]
