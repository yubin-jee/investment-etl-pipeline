FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default to running the full daily batch. Override the date by passing it as an
# argument, e.g. `docker run <image> 20240315`.
ENTRYPOINT ["python", "legacy_scripts/daily_batch.py"]
CMD ["20240315"]
