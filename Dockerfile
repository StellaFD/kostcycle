FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home appuser
COPY app/__init__.py app/models.py app/seed.py app/bootstrap.py app/common.py app/service_auth.py ./app/
RUN chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
ENV SKIP_DB_INIT=1 SEED_DEMO=0
HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)"

FROM base AS reservation
ENV SERVICE=reservation
COPY --chown=appuser:appuser app/reservation.py ./app/
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--access-logfile", "-", "--log-level", "info", "app.reservation:create_app()"]

FROM base AS catalog
ENV SERVICE=catalog
COPY --chown=appuser:appuser app/catalog.py ./app/
COPY --chown=appuser:appuser app/static ./app/static
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--access-logfile", "-", "--log-level", "info", "app.catalog:create_app()"]
