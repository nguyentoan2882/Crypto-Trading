FROM python:3.13.7-slim@sha256:5f55cdf0c5d9dc1a415637a5ccc4a9e18663ad203673173b8cda8f8dcacef689

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    ROLE=web \
    NXT_ENVIRONMENT=SHADOW

WORKDIR /app

RUN addgroup --system nxt && adduser --system --ingroup nxt --home /nonexistent nxt

COPY requirements-cloud.lock /app/requirements-cloud.lock
RUN pip install --no-cache-dir --requirement /app/requirements-cloud.lock

COPY app /app/app
COPY scripts /app/scripts

USER nxt
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/healthz',timeout=3).read()"]
CMD ["python", "-m", "app.nxt_cloud.entrypoint"]
