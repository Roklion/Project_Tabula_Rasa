"""Focused coverage for the generated Windows Codex environment setup."""

from __future__ import annotations

import base64
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
pytestmark = pytest.mark.skipif(
    os.name != "nt" or POWERSHELL is None,
    reason="Windows PowerShell is required for environment setup coverage",
)
requires_python312 = pytest.mark.skipif(
    sys.version_info[:2] != (3, 12),
    reason="The full setup harness requires a real Python 3.12 candidate",
)


def _setup_script() -> str:
    with (PROJECT_ROOT / ".codex" / "environments" / "environment.toml").open(
        "rb"
    ) as environment_file:
        return tomllib.load(environment_file)["setup"]["win32"]["script"]


def _discovery_script() -> str:
    script = _setup_script()
    script, replacements = re.subn(
        r"function Test-Python312 \{.*?\r?\n\}\r?\n\r?\nif \(",
        """function Test-Python312 {
    param(
        [string]$Executable,
        [string[]]$Arguments = @()
    )

    return $Executable -eq $env:EXPECTED_EXECUTABLE
}

if (""",
        script,
        count=1,
        flags=re.DOTALL,
    )
    if replacements != 1:
        raise AssertionError("Could not isolate the setup candidate discovery block")
    script = script.replace(
        "    $selectedArgs = $selected.Args",
        "    Write-Output (\"selected=\" + $selected.Path)\n    exit 0\n    $selectedArgs = $selected.Args",
        1,
    )
    return """
function Get-Command {
    [CmdletBinding()]
    param(
        [Parameter(Position = 0)]
        [string]$Name,
        [System.Management.Automation.CommandTypes]$CommandType,
        [switch]$All
    )

    if ($Name -eq "py.exe" -and -not [string]::IsNullOrEmpty($env:TEST_PY)) {
        return [pscustomobject]@{ Source = $env:TEST_PY; Path = $env:TEST_PY }
    }
    if ($Name -eq "python.exe" -and -not [string]::IsNullOrEmpty($env:TEST_PYTHON)) {
        $paths = @($env:TEST_PYTHON -split "\\|")
        if (-not $All) {
            $paths = @($paths[0])
        }
        foreach ($path in $paths) {
            Write-Output ([pscustomobject]@{ Source = $path; Path = $path })
        }
    }
}

if ([string]::IsNullOrEmpty($env:TEST_PROGRAMFILES)) {
    Remove-Item Env:ProgramFiles -ErrorAction SilentlyContinue
} else {
    $env:ProgramFiles = $env:TEST_PROGRAMFILES
}
if ([string]::IsNullOrEmpty($env:TEST_PUBLIC)) {
    Remove-Item Env:PUBLIC -ErrorAction SilentlyContinue
} else {
    $env:PUBLIC = $env:TEST_PUBLIC
}

""" + script


def _run_discovery(
    temporary_directory: Path,
    *,
    program_files: str | None = None,
    public: str | None = None,
    py: str | None = None,
    python: str | None = None,
    expected: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for variable in (
        "TEST_PROGRAMFILES",
        "TEST_PUBLIC",
        "TEST_PY",
        "TEST_PYTHON",
    ):
        environment.pop(variable, None)
    for variable, value in {
        "TEST_PROGRAMFILES": program_files,
        "TEST_PUBLIC": public,
        "TEST_PY": py,
        "TEST_PYTHON": python,
        "EXPECTED_EXECUTABLE": expected,
    }.items():
        if value is not None:
            environment[variable] = value

    encoded_script = base64.b64encode(
        _discovery_script().encode("utf-16-le")
    ).decode("ascii")
    return subprocess.run(
        [
            POWERSHELL,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded_script,
        ],
        cwd=temporary_directory,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _installer_shim(module_name: str) -> str:
    if module_name == "pip":
        stage_expression = '"requirements" if "-r" in sys.argv else "playwright-package"'
    else:
        stage_expression = '"chromium"'

    return f'''from pathlib import Path
import os
import sys

stage = {stage_expression}
with Path(os.environ["SETUP_TEST_LOG"]).open("a", encoding="utf-8") as log_file:
    log_file.write(stage + "\\n")
if os.environ.get("SETUP_TEST_FAIL") == stage:
    raise SystemExit(17)
'''


def _full_setup_script() -> str:
    return r'''
function Get-Command {
    [CmdletBinding()]
    param(
        [Parameter(Position = 0)]
        [string]$Name,
        [System.Management.Automation.CommandTypes]$CommandType,
        [switch]$All
    )

    if ($Name -eq "py.exe") {
        return $null
    }
    if ($Name -eq "python.exe") {
        return [pscustomobject]@{
            Source = $env:TEST_PYTHON
            Path = $env:TEST_PYTHON
        }
    }
}

Remove-Item Env:ProgramFiles -ErrorAction SilentlyContinue
Remove-Item Env:PUBLIC -ErrorAction SilentlyContinue

''' + _setup_script()


def _run_full_setup(
    temporary_directory: Path,
    *,
    fail_stage: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    workspace = temporary_directory / "workspace"
    workspace.mkdir()
    (workspace / "requirements-dev.txt").write_text("", encoding="utf-8")

    shim_root = temporary_directory / "shims"
    for module_name in ("pip", "playwright"):
        module_directory = shim_root / module_name
        module_directory.mkdir(parents=True)
        (module_directory / "__init__.py").write_text("", encoding="utf-8")
        (module_directory / "__main__.py").write_text(
            _installer_shim(module_name), encoding="utf-8"
        )

    candidate = sys.executable
    if fail_stage == "venv":
        candidate_file = temporary_directory / "python.cmd"
        candidate_file.write_text(
            "@echo off\n"
            'if "%1"=="-c" exit /b 0\n'
            'if "%1"=="-m" if "%2"=="venv" exit /b 17\n'
            "exit /b 0\n",
            encoding="ascii",
        )
        candidate = str(candidate_file)

    log_path = temporary_directory / "setup.log"
    environment = os.environ.copy()
    environment["TEST_PYTHON"] = candidate
    environment["SETUP_TEST_LOG"] = str(log_path)
    environment["PYTHONPATH"] = str(shim_root)
    if fail_stage is None:
        environment.pop("SETUP_TEST_FAIL", None)
    else:
        environment["SETUP_TEST_FAIL"] = fail_stage

    encoded_script = base64.b64encode(
        _full_setup_script().encode("utf-16-le")
    ).decode("ascii")
    result = subprocess.run(
        [
            POWERSHELL,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded_script,
        ],
        cwd=workspace,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    log_entries = (
        log_path.read_text(encoding="utf-8").splitlines()
        if log_path.exists()
        else []
    )
    return result, log_entries


@pytest.mark.parametrize(
    ("program_files", "public", "py", "python", "expected"),
    [
        pytest.param(
            r"C:\CodexEnvironmentTest\ProgramFiles",
            r"C:\CodexEnvironmentTest\Public",
            None,
            None,
            os.path.join(
                r"C:\CodexEnvironmentTest\ProgramFiles",
                "Python312",
                "python.exe",
            ),
            id="program-files-candidate",
        ),
        pytest.param(
            None,
            r"C:\CodexEnvironmentTest\Public",
            None,
            None,
            os.path.join(
                r"C:\CodexEnvironmentTest\Public",
                "Python312",
                "python.exe",
            ),
            id="public-candidate",
        ),
        pytest.param(
            None,
            None,
            r"C:\CodexEnvironmentTest\py.exe",
            None,
            r"C:\CodexEnvironmentTest\py.exe",
            id="python-launcher",
        ),
        pytest.param(
            None,
            None,
            None,
            r"C:\CodexEnvironmentTest\Python313\python.exe|"
            r"C:\CodexEnvironmentTest\Python312\python.exe",
            r"C:\CodexEnvironmentTest\Python312\python.exe",
            id="later-supported-python",
        ),
    ],
)
def test_setup_selects_first_supported_python_candidate(
    tmp_path: Path,
    program_files: str | None,
    public: str | None,
    py: str | None,
    python: str | None,
    expected: str,
) -> None:
    result = _run_discovery(
        tmp_path,
        program_files=program_files,
        public=public,
        py=py,
        python=python,
        expected=expected,
    )

    assert result.returncode == 0, result.stderr
    assert f"selected={expected}" in result.stdout


def test_setup_fails_clearly_without_python312_candidate(tmp_path: Path) -> None:
    result = _run_discovery(tmp_path)

    assert result.returncode != 0
    assert "A sandbox-readable Python 3.12 interpreter is required" in result.stderr


@requires_python312
def test_setup_runs_the_full_success_path_without_downloads(tmp_path: Path) -> None:
    result, log_entries = _run_full_setup(tmp_path)

    assert result.returncode == 0, result.stderr
    assert log_entries == ["requirements", "playwright-package", "chromium"]
    assert (tmp_path / "workspace" / ".venv" / "Scripts" / "python.exe").is_file()


def test_setup_reports_venv_creation_failure(tmp_path: Path) -> None:
    result, log_entries = _run_full_setup(tmp_path, fail_stage="venv")

    assert result.returncode != 0
    assert "Failed to create .venv." in result.stderr
    assert log_entries == []


@requires_python312
@pytest.mark.parametrize(
    ("fail_stage", "expected_error", "expected_log"),
    [
        ("requirements", "Failed to install requirements-dev.txt.", ["requirements"]),
        (
            "playwright-package",
            "Failed to install Playwright.",
            ["requirements", "playwright-package"],
        ),
        (
            "chromium",
            "Failed to install Playwright Chromium.",
            ["requirements", "playwright-package", "chromium"],
        ),
    ],
)
def test_setup_reports_installer_failures(
    tmp_path: Path,
    fail_stage: str,
    expected_error: str,
    expected_log: list[str],
) -> None:
    result, log_entries = _run_full_setup(tmp_path, fail_stage=fail_stage)

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert log_entries == expected_log
