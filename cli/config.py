from __future__ import annotations
import os

__version__ = "0.1.0"
GRAFANA_URL = os.environ.get("GRAFANA_URL", "https://kitcat-grafana.kakaopaycorp.com",).strip().rstrip("/")
GRAFANA_USER = os.environ.get("GRAFANA_USER", "admin").strip()
GRAFANA_PASSWORD = os.environ.get("GRAFANA_PASSWORD", "admin").strip()
GRAFANA_DASHBOARD_UID = os.environ.get("GRAFANA_DASHBOARD_UID", "k6-scenarios").strip()
