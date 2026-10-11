FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY reefhub ./reefhub
RUN pip install . && useradd --system --uid 10001 reefhub

USER reefhub
CMD ["python", "-m", "reefhub"]
