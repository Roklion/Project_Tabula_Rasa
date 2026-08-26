"""Focused coverage for the generated Windows Codex environment setup."""

from __future__ import annotations

import base64
import os
from pathlib import Path
import re
import shutil
import subprocess
import tomllib

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
pytestmark = pytest.mark.skipif(
    os.name != "nt" or POWERSHELL is None,
    reason="Windows PowerShell is required for environment setup coverage",
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
        [string]$Name
    )

    if ($Name -eq "py.exe" -and -not [string]::IsNullOrEmpty($env:TEST_PY)) {
        return [pscustomobject]@{ Source = $env:TEST_PY; Path = $env:TEST_PY }
    }
    if ($Name -eq "python.exe" -and -not [string]::IsNullOrEmpty($env:TEST_PYTHON)) {
        return [pscustomobject]@{ Source = $env:TEST_PYTHON; Path = $env:TEST_PYTHON }
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


def test_setup_selects_existing_shared_python_candidate() -> None:
    setup = _setup_script()
    assert "LocalAppData" not in setup
    assert setup.index("$candidates = @()") < setup.index("Get-Command py.exe")

    temporary_directory = PROJECT_ROOT
    program_files = r"C:\CodexEnvironmentTest\ProgramFiles"
    expected = os.path.join(program_files, "Python312", "python.exe")

    result = _run_discovery(
        temporary_directory,
        program_files=program_files,
        public=r"C:\CodexEnvironmentTest\Public",
        expected=expected,
    )

    assert result.returncode == 0, result.stderr
    assert f"selected={expected}" in result.stdout


def test_setup_skips_absent_programfiles_and_uses_public_candidate() -> None:
    temporary_directory = PROJECT_ROOT
    public = r"C:\CodexEnvironmentTest\Public"
    expected = os.path.join(public, "Python312", "python.exe")

    result = _run_discovery(temporary_directory, public=public, expected=expected)

    assert result.returncode == 0, result.stderr
    assert f"selected={expected}" in result.stdout


def test_setup_skips_absent_public_and_uses_programfiles_candidate() -> None:
    temporary_directory = PROJECT_ROOT
    program_files = r"C:\CodexEnvironmentTest\ProgramFiles"
    expected = os.path.join(program_files, "Python312", "python.exe")

    result = _run_discovery(
        temporary_directory, program_files=program_files, expected=expected
    )

    assert result.returncode == 0, result.stderr
    assert f"selected={expected}" in result.stdout


def test_setup_uses_py_when_both_shared_locations_are_absent() -> None:
    temporary_directory = PROJECT_ROOT
    py = r"C:\CodexEnvironmentTest\py.exe"

    result = _run_discovery(temporary_directory, py=py, expected=py)

    assert result.returncode == 0, result.stderr
    assert f"selected={py}" in result.stdout


def test_setup_fails_clearly_without_python312_candidate() -> None:
    result = _run_discovery(PROJECT_ROOT)

    assert result.returncode != 0
    assert "A sandbox-readable Python 3.12 interpreter is required" in result.stderr
