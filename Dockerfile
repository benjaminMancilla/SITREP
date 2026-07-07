FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
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
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# python-django
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# node js (vite-svelte)
COPY package.json package-lock.json* ./
RUN npm install

COPY . .

#frontend
RUN npm run build

RUN SECRET_KEY=dummy-build-key python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["sh", "-c", "python -c \"\nimport time, psycopg2, os\nurl = os.environ['DATABASE_URL']\nfor i in range(30):\n    try:\n        psycopg2.connect(url)\n        print('Postgres ready')\n        break\n    except Exception as e:\n        print(f'Waiting for postgres... ({e})')\n        time.sleep(2)\n\" && python manage.py migrate --no-input && gunicorn core.wsgi:application --bind 0.0.0.0:${PORT:-8000} --timeout 120 --workers 2"]