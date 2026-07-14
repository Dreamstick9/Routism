# Routism — self-hosted OpenAI-compatible orchestration API
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ROUTISM_HOST=0.0.0.0 \
    ROUTISM_PORT=8000 \
    ROUTISM_DATA_DIR=/data \
    ROUTISM_OPEN_LOCAL=1 \
    ROUTISM_ALLOW_ANON_LOOPBACK=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY routism/ ./routism/
COPY routism_orch/ ./routism_orch/
COPY routism.example.yaml ./routism.yaml

RUN mkdir -p /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/models')"

CMD ["python", "-m", "uvicorn", "routism.server:app", "--host", "0.0.0.0", "--port", "8000"]
