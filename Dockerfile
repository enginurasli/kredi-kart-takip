FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# SQLite varsayılanı ve VAPID anahtar dosyası buraya yazılır.
RUN mkdir -p instance && \
    adduser --disabled-password --gecos "" --uid 10001 appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

# Tek worker: APScheduler yalnızca bir süreçte çalışmalı, aksi halde
# bildirimler mükerrer gönderilir.
CMD ["sh", "-c", "gunicorn run:app --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 120"]
