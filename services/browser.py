from __future__ import annotations

import json

from playwright.sync_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from cli import config
from services.grafana import Snapshot

PANEL_WAIT_MS = 35_000
PAGE_TIMEOUT_MS = 20_000
DASHBOARD_LOADING_MS = 8_000
ROWS_READY_MS = 8_000
CLICK_TIMEOUT_MS = 10_000
ROW_EXPAND_WAIT_MS = 300
ROW_EXPAND_MAX_ROUNDS = 12
SCROLL_STEP_PIXELS = 400
SCROLL_STEP_DELAY_MS = 80
VIEWPORT = {"width": 1920, "height": 1080}
BROWSER_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]


def capture_dashboard_snapshot(dashboard_url: str) -> Snapshot:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=BROWSER_ARGS)
        try:
            context = browser.new_context(
                viewport=VIEWPORT,
                ignore_https_errors=True,
                locale="en-US",
            )
            _login(context)
            page = context.new_page()
            page.goto(dashboard_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
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


def _login(context: BrowserContext) -> None:
    url = f"{config.GRAFANA_URL}/login"
    body = json.dumps({"user": config.GRAFANA_USER, "password": config.GRAFANA_PASSWORD})
    headers = {"Content-Type": "application/json"}
    response = context.request.post(url, data=body, headers=headers)
    if response.status >= 400:
        raise RuntimeError(f"login failed: {response.status}")


def _wait_dashboard_ready(page: Page) -> None:
    try:
        page.get_by_label("Loading Grafana").wait_for(state="hidden", timeout=DASHBOARD_LOADING_MS)
    except PlaywrightTimeoutError:
        pass


def _wait_rows_ready(page: Page) -> None:
    try:
        page.wait_for_function(
            """() =>
              document.querySelectorAll(
                'button[aria-label="Expand row"], button[aria-label="Collapse row"]'
              ).length > 0
              || document.querySelector('[data-testid*="panel"]') !== null""",
            timeout=ROWS_READY_MS,
        )
    except PlaywrightTimeoutError:
        pass


def _expand_rows(page: Page) -> None:
    for _ in range(ROW_EXPAND_MAX_ROUNDS):
        expand = page.get_by_role("button", name="Expand row")
        count = expand.count()
        if count == 0:
            break
        for index in range(count):
            try:
                button = expand.nth(index)
                button.scroll_into_view_if_needed(timeout=CLICK_TIMEOUT_MS)
                button.click(timeout=CLICK_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                pass
        page.wait_for_timeout(ROW_EXPAND_WAIT_MS)


def _scroll_dashboard(page: Page) -> None:
    page.evaluate(
        f"""async () => {{
          const el = document.querySelector('[data-testid="page-content"]')
            || document.querySelector('.dashboard-container');
          if (!el) return;
          const step = {SCROLL_STEP_PIXELS};
          for (let y = 0; y <= el.scrollHeight; y += step) {{
            el.scrollTop = y;
            await new Promise((r) => setTimeout(r, {SCROLL_STEP_DELAY_MS}));
          }}
          el.scrollTop = 0;
        }}"""
    )


def _wait_panels(page: Page) -> None:
    try:
        page.wait_for_function(
            """() => ['.panel-loading', '[aria-label="Panel loading bar"]']
                .every(s => document.querySelectorAll(s).length === 0)""",
            timeout=PANEL_WAIT_MS,
        )
    except PlaywrightTimeoutError as error:
        raise RuntimeError(f"panels still loading after {PANEL_WAIT_MS // 1000}s") from error


def _publish_snapshot(page: Page) -> Snapshot:
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
    share.click(timeout=CLICK_TIMEOUT_MS)
    page.get_by_role("menuitem", name="Share snapshot").click(timeout=CLICK_TIMEOUT_MS)

    with page.expect_response(
        lambda response: "/api/snapshots" in response.url and response.request.method == "POST",
        timeout=PAGE_TIMEOUT_MS,
    ) as pending:
        page.get_by_role("button", name="Publish snapshot").click(timeout=CLICK_TIMEOUT_MS)

    return Snapshot.from_api(pending.value.json())
