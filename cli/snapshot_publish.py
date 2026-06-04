#!/usr/bin/env python3
"""Grafana 12.3 — manual snapshot export (browser) and import (API)."""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

QUERY_WAIT_MS = int(os.environ.get("SNAPSHOT_QUERY_WAIT_MS", "30000"))
VIEWPORT = {"width": 1920, "height": 2400}


def export_snapshot(
    uid: str,
    name: str,
    output_dir: str,
    *,
    time_from: str = "now-1h",
    time_to: str = "now",
    base_url: str,
    user: str,
    password: str,
) -> dict[str, Any]:
    output_file = os.path.join(output_dir, f"{name}.json")
    url = f"{base_url}/d/{uid}/?from={time_from}&to={time_to}"

    published = _capture_via_browser(base_url, user, password, url)
    key = published.get("key")
    if not key:
        raise RuntimeError(f"snapshot publish returned no key: {published}")

    snapshot = _fetch_snapshot(base_url, user, password, key)
    if not _has_embedded_data(snapshot):
        _delete_snapshot(base_url, user, password, key)
        raise RuntimeError("empty snapshot — no embedded metric data (No data)")

    snapshot["title"] = name
    out_path = _save_json(snapshot, output_file)
    _delete_snapshot(base_url, user, password, key)
    saved = _create_snapshot(base_url, user, password, snapshot, name)
    key = saved.get("key")
    if not key:
        raise RuntimeError(f"snapshot save failed: {saved}")

    return {
        "url": saved.get("url", f"{base_url}/dashboard/snapshot/{key}"),
        "key": key,
        "file": out_path,
        "name": name,
    }


def import_snapshots(directory: str, *, base_url: str, user: str, password: str) -> list[dict[str, Any]]:
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError(f"not a directory: {root}")

    paths = sorted(root.glob("*.json"))
    if not paths:
        raise RuntimeError(f"no *.json files in {root}")

    results: list[dict[str, Any]] = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            dashboard = json.load(fh)
        snap_name = dashboard.get("title") or path.stem
        created = _create_snapshot(base_url, user, password, dashboard, snap_name)
        key = created.get("key")
        if not key:
            raise RuntimeError(f"import failed for {path.name}: {created}")
        results.append(
            {
                "file": str(path),
                "name": snap_name,
                "key": key,
                "url": created.get("url", f"{base_url}/dashboard/snapshot/{key}"),
            }
        )
    return results


def _capture_via_browser(base_url: str, user: str, password: str, dashboard_url: str) -> dict[str, Any]:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(viewport=VIEWPORT, ignore_https_errors=True)
            login = ctx.request.post(
                f"{base_url}/login",
                data=json.dumps({"user": user, "password": password}),
                headers={"Content-Type": "application/json"},
            )
            if login.status >= 400:
                raise RuntimeError(f"login failed: {login.status}")

            page = ctx.new_page()
            page.goto(dashboard_url, wait_until="networkidle", timeout=60_000)
            if "/login" in page.url:
                raise RuntimeError("session expired")

            _expand_collapsed_rows(page)
            _wait_for_panels_loaded(page)
            return _publish_via_ui(page)
        finally:
            browser.close()


def _expand_collapsed_rows(page: Page) -> None:
    toggles = page.locator(".dashboard-container [aria-expanded='false']")
    for i in range(toggles.count()):
        toggles.nth(i).click(timeout=5000)


def _wait_for_panels_loaded(page: Page) -> None:
    try:
        page.wait_for_function(
            """() => {
                const sels = ['.panel-loading', '[aria-label="Panel loading bar"]'];
                return sels.every(s => document.querySelectorAll(s).length === 0);
            }""",
            timeout=QUERY_WAIT_MS,
        )
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(
            f"panels still loading after {QUERY_WAIT_MS // 1000}s"
        ) from exc


def _publish_via_ui(page: Page) -> dict[str, Any]:
    page.get_by_role("button", name="Share").click(timeout=8000)
    page.get_by_role("menuitem", name="Share snapshot").click(timeout=8000)

    def is_snapshot_post(resp):
        return "/api/snapshots" in resp.url and resp.request.method == "POST"

    with page.expect_response(is_snapshot_post, timeout=60_000) as pending:
        page.get_by_role("button", name="Publish snapshot").click(timeout=8000)
    return pending.value.json()


def _has_embedded_data(dashboard: dict[str, Any]) -> bool:
    """True if at least one query target has non-empty snapshot series."""
    for panel in _iter_panels(dashboard.get("panels") or []):
        for target in panel.get("targets") or []:
            if target.get("hide"):
                continue
            snap = target.get("snapshot")
            if not isinstance(snap, list):
                continue
            for frame in snap:
                values = (frame.get("data") or {}).get("values") or []
                if any(isinstance(col, list) and len(col) > 0 for col in values):
                    return True
    return False


def _iter_panels(panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in panels:
        if p.get("type") == "row":
            out.extend(_iter_panels(p.get("panels") or []))
        else:
            out.append(p)
    return out


def _api_request(
    base_url: str,
    user: str,
    password: str,
    path: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    auth = base64.b64encode(f"{user}:{password}".encode()).decode()
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Basic {auth}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} failed ({exc.code}): {detail}") from exc


def _fetch_snapshot(base_url: str, user: str, password: str, key: str) -> dict[str, Any]:
    body = _api_request(base_url, user, password, f"/api/snapshots/{key}")
    return body.get("dashboard") or body


def _delete_snapshot(base_url: str, user: str, password: str, key: str) -> None:
    try:
        _api_request(base_url, user, password, f"/api/snapshots/{key}", method="DELETE")
    except Exception:
        pass


def _create_snapshot(
    base_url: str, user: str, password: str, dashboard: dict[str, Any], name: str
) -> dict[str, Any]:
    return _api_request(
        base_url,
        user,
        password,
        "/api/snapshots",
        method="POST",
        body={"dashboard": dashboard, "name": name, "expires": 0},
    )


def _save_json(snapshot: dict[str, Any], path: str) -> str:
    path = os.path.abspath(path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=2)
    return path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="grafana-snapshots")
    sub = parser.add_subparsers(dest="command", required=True)

    export_p = sub.add_parser("export")
    export_p.add_argument("-u", "--uid", required=True, help="dashboard uid")
    export_p.add_argument("-n", "--name", required=True, help="snapshot name")
    export_p.add_argument("-f", "--from", dest="time_from", default="now-1h")
    export_p.add_argument("-t", "--to", dest="time_to", default="now")
    export_p.add_argument("-o", "--output", default=".", help="output directory")

    import_p = sub.add_parser("import")
    import_p.add_argument("-d", "--dir", required=True, help="directory of *.json files")

    args = parser.parse_args(argv)
    base_url = _env("GRAFANA_URL", "http://localhost:3000").rstrip("/")
    user = _env("GRAFANA_USER", "admin")
    password = _env("GRAFANA_PASSWORD", "admin")

    try:
        if args.command == "export":
            result = export_snapshot(
                args.uid,
                args.name,
                str(Path(args.output).expanduser().resolve()),
                time_from=args.time_from,
                time_to=args.time_to,
                base_url=base_url,
                user=user,
                password=password,
            )
            print(json.dumps(result))
        else:
            results = import_snapshots(
                str(Path(args.dir).expanduser().resolve()),
                base_url=base_url,
                user=user,
                password=password,
            )
            print(json.dumps({"imported": len(results), "snapshots": results}))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
