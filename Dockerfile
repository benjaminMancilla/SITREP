FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libfontconfig1 \
    libharfbuzz0b \
    libfreetype6 \
    libffi8 \
    shared-mime-info \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN SECRET_KEY=dummy-build-key python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate && gunicorn core.wsgi:application --bind 0.0.0.0:${PORT:-8000} --timeout 120 --workers 2"]