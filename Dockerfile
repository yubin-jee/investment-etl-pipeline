FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy only what the pipeline needs to run.
COPY legacy_scripts/ ./legacy_scripts/
COPY legacy_data/ ./legacy_data/
COPY config/ ./config/

# Run as a non-root user and give it ownership of the writable report dir.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p reports/client_reports \
    && chown -R appuser:appuser /app
USER appuser

# Default to running the full daily batch. Override the date by passing it as an
# argument, e.g. `docker run <image> 20240315`.
ENTRYPOINT ["python", "legacy_scripts/daily_batch.py"]
CMD ["20240315"]
