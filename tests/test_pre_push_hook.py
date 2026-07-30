from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_OID = "1" * 40
REMOTE_OID = "0" * 40


def run_pre_push_hook(remote_ref: str) -> subprocess.CompletedProcess[str]:
    hook_input = (
        f"refs/heads/feature/test {LOCAL_OID} {remote_ref} {REMOTE_OID}\n"
    )
    with tempfile.TemporaryDirectory() as temporary_directory:
        stdin_path = Path(temporary_directory) / "pre-push-input"
        stdin_path.write_text(hook_input, encoding="utf-8")
        return subprocess.run(
            [
                "git",
                "-c",
                "core.hooksPath=.githooks",
                "hook",
                "run",
                f"--to-stdin={stdin_path}",
                "pre-push",
                "--",
                "origin",
                "https://github.com/example/repository.git",
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )


def test_pre_push_hook_allows_feature_branch() -> None:
    result = run_pre_push_hook("refs/heads/feature/test")

    assert result.returncode == 0
    assert result.stderr == ""


def test_pre_push_hook_blocks_main() -> None:
    result = run_pre_push_hook("refs/heads/main")

    assert result.returncode != 0
    assert "Direct pushes to main are blocked." in result.stderr
