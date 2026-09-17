"""
Gunicorn config for Heroku and local deployment.
Tuned for 512MB dyno: 1 worker to avoid OOM (R15). Override with GUNICORN_WORKERS on larger dynos.
"""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
# 512MB dyno: use 1 worker (thumbnail generation loads full images; 2 workers = 2x memory)
workers = int(os.environ.get("GUNICORN_WORKERS", "1"))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
# Large media uploads can take a while in production, especially on slower links.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "300"))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.environ.get("GUNICORN_KEEPALIVE", "15"))
# Recycle often to limit memory creep (thumbnails + PIL can spike)
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "300"))
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "50"))
# No preload: saves ~1 process copy of app on small dyno
preload = False
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
