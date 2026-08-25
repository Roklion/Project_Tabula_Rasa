from __future__ import annotations

import http.client
import socket
from pathlib import Path

import pytest

from scripts import smoke_transactions


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

    monkeypatch.setattr(smoke_transactions.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(smoke_transactions.time, "sleep", lambda seconds: None)

    smoke_transactions.wait_for_server(
        "http://127.0.0.1:8501/", RunningProcess()  # type: ignore[arg-type]
    )


def test_screenshot_failure_does_not_mask_primary_failure(tmp_path: Path) -> None:
    class FailingPage:
        def screenshot(self, **kwargs: object) -> None:
            del kwargs
            raise RuntimeError("browser disconnected")

    failure = smoke_transactions.capture_failure_screenshot(
        FailingPage(), tmp_path, (390, 844)  # type: ignore[arg-type]
    )

    assert failure == "390x844: diagnostic screenshot failed (RuntimeError)"
