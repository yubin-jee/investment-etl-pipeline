# Minimal image for the Meridian ETL scripts.
# Kept compatible with python:3.12-slim (a separate modernization session may
# replace/extend this Dockerfile; docker-compose references it via `build: .`).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir python-dotenv && \
    pip install --no-cache-dir -r requirements.txt

# Copy the application (includes sample input data under legacy_data/).
COPY . .

# Inputs come from the image (sample data); reports/logs are written to the
# mounted named volume at /data (replaces the C:\MeridianData network drive).
# In production, override MERIDIAN_DATA_DIR to point at the volume's input drop.
ENV MERIDIAN_DATA_DIR=/app/legacy_data \
    MERIDIAN_REPORT_DIR=/data/reports \
    MERIDIAN_LOG_DIR=/data/logs

# Run the full daily batch by default; override the date via `command`.
CMD ["python", "legacy_scripts/daily_batch.py"]
