FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Override at build time: --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple

COPY requirements.txt ./
RUN pip install --no-cache-dir -i "$PIP_INDEX_URL" -r requirements.txt

COPY backoffice ./backoffice

RUN useradd --create-home --uid 10002 appuser \
 && chown -R appuser:appuser /app
USER appuser

WORKDIR /app/backoffice

EXPOSE 8001

# collectstatic: WhiteNoise needs the admin CSS/JS in STATIC_ROOT
# migrate: Django's own auth/session/admin tables (business tables are owned by Alembic in the api image)
CMD ["sh", "-c", "python manage.py collectstatic --noinput && python manage.py migrate --noinput && exec gunicorn backoffice.wsgi:application --bind 0.0.0.0:8001 --workers 2 --access-logfile -"]
