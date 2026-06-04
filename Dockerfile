FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY cli/ ./cli/
RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev \
    && uv run playwright install chromium

ENV PATH="/app/.venv/bin:${PATH}"
WORKDIR /reports
ENTRYPOINT ["grafana-snapshots"]
