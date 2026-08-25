"""Run the opt-in Transactions viewport smoke check.

This is intentionally separate from pytest: it starts the real Streamlit
entrypoint and uses a browser to check layout/rendering health at the viewports
recorded in the interface specification. Behavioral transaction and receipt
coverage belongs in the AppTest suite.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError as error:  # pragma: no cover - opt-in dependency
    raise SystemExit(
        "Playwright is required for the viewport smoke check. Install the "
        "development dependencies and run `python -m playwright install chromium`."
    ) from error


REPOSITORY = Path(__file__).resolve().parents[1]
FIXTURE_DIRECTORY = REPOSITORY / ".smoke_local"
FIXTURE_ENTRYPOINT = FIXTURE_DIRECTORY / "smoke_app.py"
PASSWORD = "test-password-123"
VIEWPORTS: tuple[tuple[int, int], ...] = (
    (1440, 1000),
    (1200, 900),
    (900, 900),
    (390, 844),
)


class SmokeCheckFailure(AssertionError):
    """A viewport-specific rendering assertion failed."""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check Transactions rendering at the supported viewports."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8501,
        help="Local Streamlit port to use (default: 8501).",
    )
    parser.add_argument(
        "--screenshots-dir",
        type=Path,
        help="Optionally save a screenshot for each failed viewport.",
    )
    return parser.parse_args(argv)


def server_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/"


def wait_for_server(url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SmokeCheckFailure(
                f"Streamlit exited before becoming ready (code {process.returncode})."
            )
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.25)
    raise SmokeCheckFailure(f"Streamlit did not become ready at {url}.")


def require_visible_text(page: Page, label: str) -> None:
    locator = page.get_by_text(label, exact=True).first
    try:
        locator.wait_for(state="visible", timeout=30000)
    except PlaywrightTimeoutError as error:
        raise SmokeCheckFailure(f"Expected visible text: {label}") from error


def require_input(page: Page, label: str) -> None:
    control = page.get_by_label(label, exact=True)
    try:
        control.first.wait_for(state="visible", timeout=30000)
    except PlaywrightTimeoutError as error:
        raise SmokeCheckFailure(f"Expected visible control: {label}") from error


def require_role(page: Page, role: str, name: str) -> None:
    control = page.get_by_role(role, name=name, exact=True)
    try:
        control.first.wait_for(state="visible", timeout=30000)
    except PlaywrightTimeoutError as error:
        raise SmokeCheckFailure(f"Expected visible {role}: {name}") from error


def assert_no_page_overflow(page: Page) -> None:
    metrics: dict[str, Any] = page.evaluate(
        """() => ({
          viewportWidth: window.innerWidth,
          documentScrollWidth: document.documentElement.scrollWidth,
          bodyScrollWidth: document.body.scrollWidth,
        })"""
    )
    width = int(metrics["viewportWidth"])
    overflowing_widths = {
        name: int(value)
        for name, value in metrics.items()
        if name.endswith("ScrollWidth") and int(value) > width + 1
    }
    if overflowing_widths:
        details = ", ".join(
            f"{name}={value}px (viewport={width}px)"
            for name, value in overflowing_widths.items()
        )
        raise SmokeCheckFailure(f"Unexpected page-level horizontal overflow: {details}")


def check_viewport(page: Page, url: str, viewport: tuple[int, int]) -> None:
    width, height = viewport
    page.set_viewport_size({"width": width, "height": height})
    page.goto(url)
    page.get_by_label("Password", exact=True).wait_for(state="visible")
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("heading", name="Transactions", exact=True).wait_for(state="visible")

    add_tab = page.get_by_role("tab", name="Add transaction", exact=True)
    if add_tab.count() == 0 or not add_tab.first.is_visible():
        raise SmokeCheckFailure("Expected the Add transaction tab.")
    add_tab.first.click()
    require_visible_text(page, "Add transaction")
    require_role(page, "radiogroup", "Transaction type")
    require_input(page, "Select a date.")
    require_role(page, "region", "Receipt (optional)")
    save_button = page.get_by_role("button", name="Save transaction", exact=True)
    if save_button.count() == 0:
        raise SmokeCheckFailure("Expected visible control: Save transaction")
    save_button.first.wait_for(state="visible", timeout=10000)
    assert_no_page_overflow(page)


def run_smoke_check(screenshots_dir: Path | None, port: int) -> list[str]:
    environment = os.environ.copy()
    environment["TABULA_LOCAL_PROFILE_ADMIN"] = "1"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(FIXTURE_ENTRYPOINT),
            "--server.address",
            "127.0.0.1",
            "--server.port",
            str(port),
            "--server.headless",
            "true",
        ],
        cwd=FIXTURE_DIRECTORY,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    failures: list[str] = []
    try:
        url = server_url(port)
        wait_for_server(url, process)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                for viewport in VIEWPORTS:
                    page = browser.new_page(
                        viewport={"width": viewport[0], "height": viewport[1]}
                    )
                    try:
                        check_viewport(page, url, viewport)
                    except Exception as error:  # noqa: BLE001 - report every viewport
                        failure = f"{viewport[0]}x{viewport[1]}: {error}"
                        failures.append(failure)
                        if screenshots_dir is not None:
                            screenshots_dir.mkdir(parents=True, exist_ok=True)
                            page.screenshot(
                                path=screenshots_dir
                                / f"transactions-{viewport[0]}x{viewport[1]}.png",
                                full_page=True,
                            )
                    finally:
                        page.close()
            finally:
                browser.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        failures = run_smoke_check(args.screenshots_dir, args.port)
    except SmokeCheckFailure as error:
        print(f"Smoke check failed: {error}", file=sys.stderr)
        return 1
    if failures:
        print("Transactions viewport smoke check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(
        "Transactions viewport smoke check passed at "
        + ", ".join(f"{width}x{height}" for width, height in VIEWPORTS)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
