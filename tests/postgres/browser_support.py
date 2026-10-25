"""Native browser process reuse with context lifetime confined to each test."""

from contextlib import contextmanager, ExitStack
import os
from pathlib import Path

import pytest


class NativeBrowsers:
    def __init__(self, playwright):
        self.playwright = playwright
        self.browsers = {}
        self.cleanup = ExitStack()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self.cleanup.__exit__(*exc)

    @contextmanager
    def open(self, engine='chromium'):
        if engine not in self.browsers:
            launcher = getattr(self.playwright, engine)
            if not Path(launcher.executable_path).is_file():
                if os.environ.get('TABULA_RASA_REQUIRE_BROWSER_TESTS') == '1':
                    pytest.fail(f'Install {engine} for required native browser tests.')
                pytest.skip(f'Install {engine} for native browser tests.')
            browser = launcher.launch()
            self.cleanup.callback(browser.close)
            self.browsers[engine] = browser
        browser = self.browsers[engine]
        try:
            yield browser
        finally:
            # Context closure clears cookies, storage, routes, pages and downloads,
            # including when an assertion fails. Attempt every context's cleanup.
            with ExitStack() as contexts:
                for context in browser.contexts:
                    contexts.callback(context.close)
