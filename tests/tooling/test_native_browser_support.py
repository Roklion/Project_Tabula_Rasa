"""Process reuse must preserve per-test browser state and failure cleanup."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.postgres.browser_support import NativeBrowsers


@pytest.fixture
def engines(tmp_path):
    executable = tmp_path / 'synthetic-browser'
    executable.touch()
    browsers = [Mock(contexts=[]), Mock(contexts=[])]
    launchers = [Mock(executable_path=str(executable), launch=Mock(return_value=b))
                 for b in browsers]
    return SimpleNamespace(chromium=launchers[0], firefox=launchers[1]), browsers


def test_reuses_engine_and_closes_each_context_after_success_and_failure(engines):
    playwright, (chromium, firefox) = engines
    with NativeBrowsers(playwright) as pool:
        with pool.open() as first:
            assert first is chromium
            contexts = [Mock(), Mock()]
            chromium.contexts = contexts
        for context in contexts:
            context.close.assert_called_once()
        chromium.contexts = []
        with pytest.raises(AssertionError, match='synthetic failure'):
            with pool.open() as reused:
                assert reused is first
                failed_context = Mock()
                chromium.contexts = [failed_context]
                raise AssertionError('synthetic failure')
        failed_context.close.assert_called_once()
        with pool.open('firefox') as other:
            assert other is firefox and other is not first
        playwright.chromium.launch.assert_called_once_with()
        playwright.firefox.launch.assert_called_once_with()
        chromium.close.assert_not_called()
    chromium.close.assert_called_once()
    firefox.close.assert_called_once()


def test_cleanup_attempts_every_context_and_engine_even_if_close_fails(engines):
    playwright, (chromium, firefox) = engines
    with pytest.raises(RuntimeError, match='synthetic close failure'):
        with NativeBrowsers(playwright) as pool:
            with pool.open('firefox'):
                pass
            with pool.open():
                kept = Mock()
                failed = Mock(close=Mock(side_effect=RuntimeError('synthetic close failure')))
                chromium.contexts = [kept, failed]
    kept.close.assert_called_once()
    failed.close.assert_called_once()
    chromium.close.assert_called_once()
    firefox.close.assert_called_once()


@pytest.mark.parametrize('required', [False, True])
def test_missing_engine_fails_required_gate_and_skips_optional_runs(tmp_path, monkeypatch, required):
    monkeypatch.setenv('TABULA_RASA_REQUIRE_BROWSER_TESTS', '1' if required else '0')
    launcher = Mock(executable_path=str(tmp_path / 'missing'))
    with NativeBrowsers(SimpleNamespace(chromium=launcher)) as pool:
        with pytest.raises(pytest.fail.Exception if required else pytest.skip.Exception):
            with pool.open():
                pytest.fail('A missing engine must not run a test')
    launcher.launch.assert_not_called()
