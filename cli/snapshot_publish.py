#!/usr/bin/env python3
"""Grafana 12 — snapshot export (browser) and import (API)."""
from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel, field_validator
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

__version__ = "0.1.0"

PANEL_WAIT_MS = 30_000
VIEWPORT = {"width": 1920, "height": 1080}


class GrafanaConfig(BaseModel):
    url: str
    user: str
    password: str

    @field_validator("url")
    @classmethod
    def no_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @classmethod
    def from_env(cls) -> GrafanaConfig:
        fields = {}
        for key in ("GRAFANA_URL", "GRAFANA_USER", "GRAFANA_PASSWORD"):
            value = os.environ.get(key, "").strip()
            if not value:
                raise RuntimeError(f"{key} is required")
            fields[key.removeprefix("GRAFANA_").lower()] = value
        return cls(**fields)


class ExportResult(BaseModel):
    url: str
    key: str
    file: str
    name: str


class ImportEntry(BaseModel):
    file: str
    name: str
    key: str
    url: str


class ImportReport(BaseModel):
    imported: int
    snapshots: list[ImportEntry]


class GrafanaApi:
    def __init__(self, cfg: GrafanaConfig) -> None:
        self._cfg = cfg
        self._ssl = ssl._create_unverified_context() if cfg.url.startswith("https://") else None

    def call(self, path: str, method: str = "GET", body: dict[str, Any] | None = None) -> dict[str, Any]:
        auth = base64.b64encode(f"{self._cfg.user}:{self._cfg.password}".encode()).decode()
        payload = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": f"Basic {auth}"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"{self._cfg.url}{path}", data=payload, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=60, context=self._ssl) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"{method} {path} failed ({exc.code}): {detail}") from exc

    def fetch_dashboard(self, key: str) -> dict[str, Any]:
        body = self.call(f"/api/snapshots/{key}")
        return body.get("dashboard") or body

    def delete(self, key: str) -> None:
        try:
            self.call(f"/api/snapshots/{key}", method="DELETE")
        except Exception:
            pass

    def create(self, dashboard: dict[str, Any], name: str) -> dict[str, Any]:
        return self.call(
            "/api/snapshots",
            method="POST",
            body={"dashboard": dashboard, "name": name, "expires": 0},
        )


class SnapshotService:
    def __init__(self, cfg: GrafanaConfig) -> None:
        self._cfg = cfg
        self._api = GrafanaApi(cfg)

    def export(
        self, uid: str, name: str, output_dir: Path, time_from: str, time_to: str
    ) -> ExportResult:
        dashboard_url = f"{self._cfg.url}/d/{uid}/?from={time_from}&to={time_to}"
        published = self._capture_via_browser(dashboard_url)
        key = published.get("key")
        if not key:
            raise RuntimeError(f"snapshot publish returned no key: {published}")

        snapshot = self._api.fetch_dashboard(key)
        missing = _panels_missing_snapshot(snapshot)
        if missing:
            self._api.delete(key)
            titles = ", ".join(missing[:8])
            suffix = f" (+{len(missing) - 8} more)" if len(missing) > 8 else ""
            raise RuntimeError(
                f"snapshot missing metric data for panels: {titles}{suffix}"
            )

        snapshot["title"] = name
        out_path = _write_json(snapshot, output_dir / f"{name}.json")
        self._api.delete(key)

        saved = self._api.create(snapshot, name)
        saved_key = saved.get("key")
        if not saved_key:
            raise RuntimeError(f"snapshot save failed: {saved}")

        return ExportResult(
            url=saved.get("url", f"{self._cfg.url}/dashboard/snapshot/{saved_key}"),
            key=saved_key,
            file=str(out_path),
            name=name,
        )

    def import_dir(self, directory: Path) -> ImportReport:
        if not directory.is_dir():
            raise RuntimeError(f"not a directory: {directory}")
        paths = sorted(directory.glob("*.json"))
        if not paths:
            raise RuntimeError(f"no *.json files in {directory}")

        entries: list[ImportEntry] = []
        for path in paths:
            dashboard = json.loads(path.read_text(encoding="utf-8"))
            snap_name = dashboard.get("title") or path.stem
            created = self._api.create(dashboard, snap_name)
            key = created.get("key")
            if not key:
                raise RuntimeError(f"import failed for {path.name}: {created}")
            entries.append(
                ImportEntry(
                    file=str(path),
                    name=snap_name,
                    key=key,
                    url=created.get("url", f"{self._cfg.url}/dashboard/snapshot/{key}"),
                )
            )
        return ImportReport(imported=len(entries), snapshots=entries)

    def _capture_via_browser(self, dashboard_url: str) -> dict[str, Any]:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                ctx = browser.new_context(
                    viewport=VIEWPORT,
                    ignore_https_errors=True,
                    locale="en-US",
                )
                login = ctx.request.post(
                    f"{self._cfg.url}/login",
                    data=json.dumps({"user": self._cfg.user, "password": self._cfg.password}),
                    headers={"Content-Type": "application/json"},
                )
                if login.status >= 400:
                    raise RuntimeError(f"login failed: {login.status}")

                page = ctx.new_page()
                page.goto(dashboard_url, wait_until="domcontentloaded", timeout=60_000)
                if "/login" in page.url:
                    raise RuntimeError("session expired")

                _wait_dashboard_ready(page)
                _wait_rows_ready(page)
                _expand_rows(page)
                _scroll_dashboard(page)
                _wait_panels(page)
                return _publish_snapshot(page)
            finally:
                browser.close()


def _wait_dashboard_ready(page: Page) -> None:
    try:
        page.get_by_label("Loading Grafana").wait_for(state="hidden", timeout=60_000)
    except PlaywrightTimeoutError:
        pass


def _wait_rows_ready(page: Page) -> None:
    """Row headers render after the global loading overlay disappears."""
    try:
        page.wait_for_function(
            """() =>
              document.querySelectorAll(
                'button[aria-label="Expand row"], button[aria-label="Collapse row"]'
              ).length > 0
              || document.querySelector('[data-testid*="panel"]') !== null""",
            timeout=60_000,
        )
    except PlaywrightTimeoutError:
        pass


def _expand_rows(page: Page) -> None:
    """Expand collapsed dashboard rows so hidden panels load and snapshot."""
    for _ in range(16):
        expand = page.get_by_role("button", name="Expand row")
        count = expand.count()
        if count == 0:
            break
        for i in range(count):
            try:
                btn = expand.nth(i)
                btn.scroll_into_view_if_needed(timeout=5_000)
                btn.click(timeout=5_000)
            except PlaywrightTimeoutError:
                pass
        page.wait_for_timeout(400)


def _scroll_dashboard(page: Page) -> None:
    page.evaluate(
        """async () => {
          const el = document.querySelector('[data-testid="page-content"]')
            || document.querySelector('.dashboard-container');
          if (!el) return;
          const step = 400;
          for (let y = 0; y <= el.scrollHeight; y += step) {
            el.scrollTop = y;
            await new Promise((r) => setTimeout(r, 60));
          }
          el.scrollTop = 0;
        }"""
    )


def _wait_panels(page: Page) -> None:
    try:
        page.wait_for_function(
            """() => ['.panel-loading', '[aria-label="Panel loading bar"]']
                .every(s => document.querySelectorAll(s).length === 0)""",
            timeout=PANEL_WAIT_MS,
        )
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(f"panels still loading after {PANEL_WAIT_MS // 1000}s") from exc


def _publish_snapshot(page: Page) -> dict[str, Any]:
    page.keyboard.press("Escape")
    page.evaluate(
        """() => {
          window.scrollTo(0, 0);
          const el = document.querySelector('[data-testid="page-content"]')
            || document.querySelector('.dashboard-container');
          if (el) el.scrollTop = 0;
        }"""
    )
    share = page.get_by_role("button", name="Share").last
    share.wait_for(state="visible", timeout=PANEL_WAIT_MS)
    share.click(timeout=8_000)
    page.get_by_role("menuitem", name="Share snapshot").click(timeout=8_000)

    def is_post(resp) -> bool:
        return "/api/snapshots" in resp.url and resp.request.method == "POST"

    with page.expect_response(is_post, timeout=60_000) as pending:
        page.get_by_role("button", name="Publish snapshot").click(timeout=8_000)
    return pending.value.json()


def _iter_panels(panels: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for panel in panels:
        if panel.get("type") == "row":
            yield from _iter_panels(panel.get("panels") or [])
        else:
            yield panel


def _target_has_snapshot_data(target: dict[str, Any]) -> bool:
    snap = target.get("snapshot")
    if not isinstance(snap, list):
        return False
    for frame in snap:
        values = (frame.get("data") or {}).get("values") or []
        if any(isinstance(col, list) and col for col in values):
            return True
    return False


def _panels_missing_snapshot(dashboard: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for panel in _iter_panels(dashboard.get("panels") or []):
        if panel.get("type") == "row":
            continue
        targets = panel.get("targets") or []
        if not targets:
            continue
        label = str(panel.get("title") or panel.get("id") or "unknown")
        for target in targets:
            if target.get("hide"):
                continue
            if _target_has_snapshot_data(target):
                continue
            if target.get("queryType") == "snapshot" or target.get("expr") or target.get(
                "datasource"
            ):
                missing.append(label)
                break
    return missing


def _write_json(data: dict[str, Any], path: Path) -> Path:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="grafana-snapshots")
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"grafana-snapshots {__version__}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    export_p = sub.add_parser("export")
    export_p.add_argument("-u", "--uid", required=True)
    export_p.add_argument("-n", "--name", required=True)
    export_p.add_argument("-f", "--from", dest="time_from", required=True)
    export_p.add_argument("-t", "--to", dest="time_to", required=True)
    export_p.add_argument("-o", "--output", default=".")

    import_p = sub.add_parser("import")
    import_p.add_argument("-d", "--dir", required=True)

    args = parser.parse_args(argv)
    cfg = GrafanaConfig.from_env()
    svc = SnapshotService(cfg)

    try:
        if args.command == "export":
            result = svc.export(
                args.uid,
                args.name,
                Path(args.output).expanduser().resolve(),
                args.time_from,
                args.time_to,
            )
            print(result.model_dump_json())
        else:
            report = svc.import_dir(Path(args.dir).expanduser().resolve())
            print(report.model_dump_json())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
