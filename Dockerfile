FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install chromium

COPY cli/snapshot_publish.py snapshot_publish.py

WORKDIR /reports
ENTRYPOINT ["python", "/app/snapshot_publish.py"]
