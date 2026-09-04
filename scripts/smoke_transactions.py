"""Run the opt-in Transactions viewport smoke check.

This is intentionally separate from pytest: it starts the real Streamlit
entrypoint and uses a browser to check layout/rendering health at the viewports
recorded in the interface specification. Behavioral transaction and receipt
coverage belongs in the AppTest suite.
"""

from __future__ import annotations

import argparse
import http.client
import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover - opt-in dependency
    HAS_PLAYWRIGHT = False

    class Page:  # type: ignore[no-redef]
        """Fallback type that keeps the optional smoke module importable."""

    class PlaywrightTimeoutError(Exception):  # type: ignore[no-redef]
        """Fallback timeout type used when Playwright is not installed."""

    def sync_playwright() -> Any:  # type: ignore[no-redef]
        raise RuntimeError("Playwright is not installed")
else:
    HAS_PLAYWRIGHT = True


REPOSITORY = Path(__file__).resolve().parents[1]
FIXTURE_DIRECTORY = REPOSITORY / ".smoke_local"
FIXTURE_ENTRYPOINT = FIXTURE_DIRECTORY / "smoke_app.py"
PRODUCTION_THEME = REPOSITORY / ".streamlit" / "config.toml"
FIXTURE_THEME = FIXTURE_DIRECTORY / ".streamlit" / "config.toml"
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


def ensure_port_available(port: int) -> None:
    """Reject a port already owned by another local process."""
    if not 1 <= port <= 65535:
        raise SmokeCheckFailure("Port must be between 1 and 65535.")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", port))
    except OSError as error:
        raise SmokeCheckFailure(
            f"Port {port} is unavailable on 127.0.0.1; choose an unused port."
        ) from error


def ensure_fixture_theme_is_current() -> None:
    """Fail rather than exercise a stale copy of the production theme."""
    try:
        fixture_theme = FIXTURE_THEME.read_bytes()
    except FileNotFoundError as error:
        raise SmokeCheckFailure(
            f"Smoke fixture theme configuration file is missing: {FIXTURE_THEME}"
        ) from error
    try:
        production_theme = PRODUCTION_THEME.read_bytes()
    except FileNotFoundError as error:
        raise SmokeCheckFailure(
            f"Production theme configuration file is missing: {PRODUCTION_THEME}"
        ) from error
    if fixture_theme != production_theme:
        raise SmokeCheckFailure(
            "The smoke fixture theme differs from .streamlit/config.toml; "
            "synchronize .smoke_local/.streamlit/config.toml before running."
        )


def wait_for_server(url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SmokeCheckFailure(
                f"Streamlit exited before becoming ready (code {process.returncode})."
            )
        try:
            with opener.open(url, timeout=2):
                return
        except (OSError, http.client.HTTPException):
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
          viewportWidth: document.documentElement.clientWidth,
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


def open_sidebar_for_narrow_view(page: Page, width: int) -> None:
    if width > 600:
        return

    sidebar_menu = page.get_by_role("button", name="Main menu", exact=True)
    try:
        sidebar_menu.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError as error:
        raise SmokeCheckFailure(
            "Expected the collapsed-sidebar Main menu at narrow width."
        ) from error
    sidebar_menu.click()


def check_viewport(page: Page, url: str, viewport: tuple[int, int]) -> None:
    width, height = viewport
    page.set_viewport_size({"width": width, "height": height})
    page.goto(url)
    page.get_by_label("Password", exact=True).wait_for(state="visible")
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role(
        "heading", name="Your books at a glance", exact=True
    ).wait_for(state="visible")

    open_sidebar_for_narrow_view(page, width)

    dashboard_route = page.get_by_role("radio", name="Dashboard", exact=True)
    try:
        dashboard_route.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError as error:
        raise SmokeCheckFailure("Expected the Dashboard navigation route.") from error
    if not dashboard_route.is_checked():
        raise SmokeCheckFailure(
            "Dashboard content is visible but the Dashboard route is not selected."
        )

    transactions_route = page.get_by_role("radio", name="Transactions", exact=True)
    try:
        transactions_route.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError as error:
        raise SmokeCheckFailure("Expected the Transactions navigation route.") from error
    if width <= 600:
        transactions_route.evaluate("element => element.click()")
    else:
        page.get_by_text("Transactions", exact=True).first.click()
    page.get_by_role("heading", name="Transactions", exact=True).wait_for(
        state="visible"
    )

    add_tab = page.get_by_role("tab", name="Add transaction", exact=True).first
    try:
        add_tab.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError as error:
        raise SmokeCheckFailure("Expected the Add transaction tab.") from error
    add_tab.click()
    require_visible_text(page, "Add transaction")
    require_role(page, "radiogroup", "Transaction type")
    require_input(page, "Select a date.")
    require_role(page, "region", "Receipt (optional)")
    save_button = page.get_by_role(
        "button", name="Save transaction", exact=True
    ).first
    try:
        save_button.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError as error:
        raise SmokeCheckFailure("Expected visible control: Save transaction") from error
    assert_no_page_overflow(page)

    ledger_tab = page.get_by_role(
        "tab", name="View & edit ledger", exact=True
    ).first
    try:
        ledger_tab.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError as error:
        raise SmokeCheckFailure("Expected the View & edit ledger tab.") from error
    ledger_tab.click()
    require_visible_text(page, "View & edit ledger")
    edit_expander = page.get_by_text("Edit transaction", exact=True).first
    try:
        edit_expander.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError as error:
        raise SmokeCheckFailure("Expected the Edit transaction expander.") from error
    edit_expander.click()
    require_input(page, "Transaction to edit")
    require_input(page, "Upload receipt")
    receipt_upload = page.locator('input[type="file"]').last
    try:
        receipt_upload.wait_for(state="attached", timeout=10000)
    except PlaywrightTimeoutError as error:
        raise SmokeCheckFailure(
            "Expected the saved-transaction receipt file input."
        ) from error
    if not receipt_upload.evaluate("element => element.multiple === true"):
        raise SmokeCheckFailure(
            "Expected the saved-transaction receipt uploader to accept multiple files."
        )
    assert_no_page_overflow(page)

    mixed_tab = page.get_by_role(
        "tab", name="Mixed-use expenses", exact=True
    ).first
    try:
        mixed_tab.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError as error:
        raise SmokeCheckFailure("Expected the Mixed-use expenses tab.") from error
    mixed_tab.click()
    require_visible_text(page, "Mixed-use expenses")
    require_input(page, "Total Expense")
    require_input(page, "Business Use %")
    require_input(page, "Allocation Rationale (required)")
    require_visible_text(page, "Ledger Result (read-only)")
    require_visible_text(page, "Mixed-use Expense Log")
    require_visible_text(page, "Add mixed-use expense")
    mixed_log = page.locator(
        '[data-testid="stDataFrameGlideDataEditor"]'
    ).last
    try:
        mixed_log.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError as error:
        raise SmokeCheckFailure(
            "Expected the selectable Mixed-use Expense Log table."
        ) from error
    assert_no_page_overflow(page)


def capture_failure_screenshot(
    page: Page, screenshots_dir: Path, viewport: tuple[int, int]
) -> str | None:
    """Capture optional diagnostics without masking the viewport failure."""
    try:
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(
            path=screenshots_dir
            / f"transactions-{viewport[0]}x{viewport[1]}.png",
            full_page=True,
            timeout=5000,
        )
    except Exception as error:  # noqa: BLE001 - diagnostics must not mask failure
        return (
            f"{viewport[0]}x{viewport[1]}: diagnostic screenshot failed "
            f"({type(error).__name__})"
        )
    return None


def launch_browser(playwright: Any) -> Any:
    """Convert missing-browser errors into an actionable smoke failure."""
    try:
        return playwright.chromium.launch()
    except Exception as error:  # noqa: BLE001 - normalize external tool errors
        raise SmokeCheckFailure(
            "Failed to launch Chromium. Ensure you have run "
            "`python -m playwright install chromium`."
        ) from error


def close_page(page: Page, viewport: tuple[int, int], failures: list[str]) -> None:
    """Keep cleanup errors from replacing the viewport result."""
    try:
        page.close()
    except Exception as error:  # noqa: BLE001 - cleanup must not abort the run
        failures.append(
            f"{viewport[0]}x{viewport[1]}: page cleanup failed "
            f"({type(error).__name__})"
        )


def close_browser(browser: Any, failures: list[str]) -> None:
    """Keep browser cleanup errors from replacing viewport diagnostics."""
    try:
        browser.close()
    except Exception as error:  # noqa: BLE001 - cleanup must not abort the run
        failures.append(f"Browser cleanup failed ({type(error).__name__})")


def _exit_playwright_context(
    playwright_context: Any,
    failures: list[str],
    exception_info: tuple[Any, Any, Any],
) -> None:
    try:
        playwright_context.__exit__(*exception_info)
    except Exception as error:  # noqa: BLE001 - normalize cleanup failures
        failure = f"Playwright shutdown failed ({type(error).__name__})"
        if failures:
            failures.append(failure)
            return
        primary_error = exception_info[1]
        if primary_error is not None:
            raise SmokeCheckFailure(f"{primary_error}; {failure}") from primary_error
        raise SmokeCheckFailure(failure) from error


def run_smoke_check(screenshots_dir: Path | None, port: int) -> list[str]:
    if not HAS_PLAYWRIGHT:
        raise SmokeCheckFailure(
            "Playwright is required for the viewport smoke check. Install the "
            "development dependencies and run `python -m playwright install chromium`."
        )
    ensure_port_available(port)
    ensure_fixture_theme_is_current()
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
    )
    failures: list[str] = []
    try:
        url = server_url(port)
        wait_for_server(url, process)
        playwright_context = sync_playwright()
        try:
            playwright = playwright_context.__enter__()
        except Exception as error:  # noqa: BLE001 - normalize startup failures
            raise SmokeCheckFailure(
                "Failed to initialize Playwright. Ensure the Playwright "
                "installation is available and healthy."
            ) from error
        try:
            browser = launch_browser(playwright)
            try:
                for viewport in VIEWPORTS:
                    page: Page | None = None
                    try:
                        page = browser.new_page(
                            viewport={"width": viewport[0], "height": viewport[1]}
                        )
                        check_viewport(page, url, viewport)
                    except Exception as error:  # noqa: BLE001 - report every viewport
                        failure = f"{viewport[0]}x{viewport[1]}: {error}"
                        failures.append(failure)
                        if screenshots_dir is not None and page is not None:
                            screenshot_failure = capture_failure_screenshot(
                                page, screenshots_dir, viewport
                            )
                            if screenshot_failure is not None:
                                failures.append(screenshot_failure)
                    finally:
                        if page is not None:
                            close_page(page, viewport, failures)
            finally:
                close_browser(browser, failures)
        except SmokeCheckFailure:
            raise
        except Exception as error:  # noqa: BLE001 - normalize startup failures
            raise SmokeCheckFailure(
                "Failed to initialize Playwright. Ensure the Playwright "
                "installation is available and healthy."
            ) from error
        finally:
            _exit_playwright_context(playwright_context, failures, sys.exc_info())
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
