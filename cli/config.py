from __future__ import annotations

import os

__version__ = "0.1.0"

GRAFANA_URL = os.environ.get("GRAFANA_URL", "").strip().rstrip("/")
GRAFANA_USER = os.environ.get("GRAFANA_USER", "").strip()
GRAFANA_PASSWORD = os.environ.get("GRAFANA_PASSWORD", "").strip()

DASHBOARD_UID = "snapshot-demo"
