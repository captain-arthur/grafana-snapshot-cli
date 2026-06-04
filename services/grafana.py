from __future__ import annotations

from typing import Any

import requests
import urllib3
from pydantic import BaseModel

from cli import config

urllib3.disable_warnings()

VERIFY_SSL = False
TIMEOUT = 120


class Snapshot(BaseModel):
    key: str = ""
    url: str = ""

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Snapshot:
        snapshot = cls.model_validate(data)
        if not snapshot.key:
            raise RuntimeError(f"snapshot api response missing key: {data}")
        return snapshot


class GrafanaApi:
    def __init__(self) -> None:
        self.auth = (config.GRAFANA_USER, config.GRAFANA_PASSWORD)
        self.verify = VERIFY_SSL
        self.timeout = TIMEOUT

    def get_dashboard(self, key: str) -> dict[str, Any]:
        url = f"{config.GRAFANA_URL}/api/snapshots/{key}"
        body = requests.get(url, auth=self.auth, verify=self.verify, timeout=self.timeout).json()
        dashboard = body.get("dashboard")
        if not isinstance(dashboard, dict):
            raise RuntimeError(f"snapshot dashboard missing for key {key!r}: {body}")
        return dashboard

    def delete_snapshot(self, key: str) -> None:
        url = f"{config.GRAFANA_URL}/api/snapshots/{key}"
        requests.delete(url, auth=self.auth, verify=self.verify, timeout=self.timeout)

    def get_snapshot(self, name: str) -> Snapshot | None:
        url = f"{config.GRAFANA_URL}/api/dashboard/snapshots"
        items = requests.get(url, params={"query": name}, auth=self.auth, verify=self.verify, timeout=self.timeout).json()
        for item in items:
            if item.get("name") == name:
                key = item.get("key", "")
                if not key:
                    return None
                return Snapshot(key=key, url=f"{config.GRAFANA_URL}/dashboard/snapshot/{key}")
        return None

    def create_snapshot(self, dashboard: dict[str, Any], name: str) -> Snapshot:
        url = f"{config.GRAFANA_URL}/api/snapshots"
        body = {"dashboard": dashboard, "name": name, "expires": 0}
        created = requests.post(url, json=body, auth=self.auth, verify=self.verify, timeout=self.timeout).json()
        return Snapshot.from_api(created)
