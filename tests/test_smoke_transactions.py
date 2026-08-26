from __future__ import annotations

import http.client
import socket
from pathlib import Path

import pytest

from scripts import smoke_transactions


def test_overflow_check_uses_scrollbar_independent_viewport_width() -> None:
    class RecordingPage:
        script = ""

        def evaluate(self, script: str) -> dict[str, int]:
            self.script = script
            return {
                "viewportWidth": 1000,
                "documentScrollWidth": 1005,
                "bodyScrollWidth": 1000,
            }

    page = RecordingPage()
    with pytest.raises(
        smoke_transactions.SmokeCheckFailure,
        match="horizontal overflow",
    ):
        smoke_transactions.assert_no_page_overflow(page)  # type: ignore[arg-type]

    assert "document.documentElement.clientWidth" in page.script
    assert "window.innerWidth" not in page.script


def test_ensure_port_available_rejects_an_existing_listener() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]

        with pytest.raises(
            smoke_transactions.SmokeCheckFailure,
            match=rf"Port {port} is unavailable",
        ):
            smoke_transactions.ensure_port_available(port)


def test_ensure_fixture_theme_is_current_rejects_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    production_theme = tmp_path / "production.toml"
    fixture_theme = tmp_path / "fixture.toml"
    production_theme.write_text("primaryColor = 'blue'", encoding="utf-8")
    fixture_theme.write_text("primaryColor = 'red'", encoding="utf-8")
    monkeypatch.setattr(smoke_transactions, "PRODUCTION_THEME", production_theme)
    monkeypatch.setattr(smoke_transactions, "FIXTURE_THEME", fixture_theme)

    with pytest.raises(
        smoke_transactions.SmokeCheckFailure,
        match="fixture theme differs",
    ):
        smoke_transactions.ensure_fixture_theme_is_current()


def test_wait_for_server_retries_transient_protocol_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = iter((http.client.RemoteDisconnected(), object()))

    class ReadyResponse:
        def __enter__(self) -> ReadyResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_urlopen(url: str, timeout: int) -> ReadyResponse:
        del url, timeout
        outcome = next(attempts)
        if isinstance(outcome, Exception):
            raise outcome
        return ReadyResponse()

    class RunningProcess:
        returncode = None

        def poll(self) -> None:
            return None

    class FakeOpener:
        def open(self, url: str, timeout: int) -> ReadyResponse:
            return fake_urlopen(url, timeout)

    monkeypatch.setattr(
        smoke_transactions.urllib.request,
        "build_opener",
        lambda handler: FakeOpener(),
    )
    monkeypatch.setattr(smoke_transactions.time, "sleep", lambda seconds: None)

    smoke_transactions.wait_for_server(
        "http://127.0.0.1:8501/", RunningProcess()  # type: ignore[arg-type]
    )


def test_screenshot_failure_does_not_mask_primary_failure(tmp_path: Path) -> None:
    class FailingPage:
        screenshot_kwargs: dict[str, object] = {}

        def screenshot(self, **kwargs: object) -> None:
            self.screenshot_kwargs = kwargs
            raise RuntimeError("browser disconnected")

    page = FailingPage()
    failure = smoke_transactions.capture_failure_screenshot(page, tmp_path, (390, 844))

    assert failure == "390x844: diagnostic screenshot failed (RuntimeError)"
    assert page.screenshot_kwargs["timeout"] == 5000


def test_browser_launch_failure_is_actionable() -> None:
    class FailingChromium:
        def launch(self) -> None:
            raise RuntimeError("browser binary missing")

    with pytest.raises(
        smoke_transactions.SmokeCheckFailure,
        match="Failed to launch Chromium",
    ):
        smoke_transactions.launch_browser(type("Playwright", (), {"chromium": FailingChromium()})())


def test_page_cleanup_failure_is_recorded_without_raising() -> None:
    class FailingPage:
        def close(self) -> None:
            raise RuntimeError("browser disconnected")

    failures: list[str] = []
    smoke_transactions.close_page(FailingPage(), (390, 844), failures)  # type: ignore[arg-type]

    assert failures == ["390x844: page cleanup failed (RuntimeError)"]


def test_browser_cleanup_failure_is_recorded_without_raising() -> None:
    class FailingBrowser:
        def close(self) -> None:
            raise RuntimeError("browser disconnected")

    failures: list[str] = []
    smoke_transactions.close_browser(FailingBrowser(), failures)

    assert failures == ["Browser cleanup failed (RuntimeError)"]


def test_run_smoke_check_skips_screenshot_without_a_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RunningProcess:
        returncode = None

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            return None

        def wait(self, timeout: int | None = None) -> None:
            del timeout
            return None

    class FailingBrowser:
        def new_page(self, **kwargs: object) -> None:
            del kwargs
            raise RuntimeError("browser disconnected")

        def close(self) -> None:
            return None

    class PlaywrightContext:
        def __enter__(self) -> object:
            return type(
                "Playwright",
                (),
                {"chromium": type("Chromium", (), {"launch": lambda self: FailingBrowser()})()},
            )()

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(smoke_transactions, "ensure_port_available", lambda port: None)
    monkeypatch.setattr(smoke_transactions, "ensure_fixture_theme_is_current", lambda: None)
    monkeypatch.setattr(smoke_transactions, "wait_for_server", lambda url, process: None)
    monkeypatch.setattr(
        smoke_transactions.subprocess,
        "Popen",
        lambda *args, **kwargs: RunningProcess(),
    )
    monkeypatch.setattr(
        smoke_transactions,
        "sync_playwright",
        lambda: PlaywrightContext(),
    )

    def unexpected_screenshot(*args: object, **kwargs: object) -> None:
        del args, kwargs
        pytest.fail("screenshot capture should not run without a page")

    monkeypatch.setattr(
        smoke_transactions,
        "capture_failure_screenshot",
        unexpected_screenshot,
    )

    failures = smoke_transactions.run_smoke_check(Path("screenshots"), 8501)

    assert len(failures) == len(smoke_transactions.VIEWPORTS)
    assert all("browser disconnected" in failure for failure in failures)


def test_run_smoke_check_normalizes_playwright_context_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RunningProcess:
        returncode = None

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            return None

        def wait(self, timeout: int | None = None) -> None:
            del timeout
            return None

    class FailingPlaywrightContext:
        def __enter__(self) -> None:
            raise RuntimeError("driver unavailable")

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(smoke_transactions, "ensure_port_available", lambda port: None)
    monkeypatch.setattr(smoke_transactions, "ensure_fixture_theme_is_current", lambda: None)
    monkeypatch.setattr(smoke_transactions, "wait_for_server", lambda url, process: None)
    monkeypatch.setattr(
        smoke_transactions.subprocess,
        "Popen",
        lambda *args, **kwargs: RunningProcess(),
    )
    monkeypatch.setattr(
        smoke_transactions,
        "sync_playwright",
        lambda: FailingPlaywrightContext(),
    )

    with pytest.raises(
        smoke_transactions.SmokeCheckFailure,
        match="Failed to initialize Playwright",
    ):
        smoke_transactions.run_smoke_check(None, 8501)
