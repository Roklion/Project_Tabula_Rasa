"""Keep provider implementation access at documented infrastructure seams."""

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "tabula_rasa"

# Keep this list aligned with docs/ARCHITECTURE.md. New exceptions require an
# ownership decision, rather than adding storage access to another UI module.
SHEETS_EXCEPTIONS = {
    "google_drive_admin.py",
    "local_profile_admin_readiness.py",
    "local_profile_admin_support.py",
    "receipt_backfill.py",
    "receipt_recovery.py",
}


def imported_modules(source: str, module: str) -> set[str]:
    """Resolve ordinary absolute and relative imports, including facade access."""
    imports = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = node.module or ""
            if node.level:
                parent = module.split(".")[:-node.level]
                prefix = ".".join((*parent, *prefix.split("."))).rstrip(".")
            imports.add(prefix)
            imports.update(f"{prefix}.{alias.name}" for alias in node.names)
    return imports


def test_only_documented_infrastructure_and_admin_import_sheets() -> None:
    violations = []
    for path in PACKAGE.rglob("*.py"):
        relative = path.relative_to(PACKAGE).as_posix()
        if relative.startswith(("storage/", "infrastructure/")) or relative in SHEETS_EXCEPTIONS:
            continue
        module = ".".join(path.relative_to(ROOT).with_suffix("").parts)
        imports = imported_modules(path.read_text(encoding="utf-8"), module)
        forbidden = {
            name for name in imports
            if name == "tabula_rasa.storage" or name.startswith("tabula_rasa.storage.")
        }
        if relative.startswith(("application/",)):
            forbidden.update(
                name for name in imports
                if name == "tabula_rasa.infrastructure" or name.startswith("tabula_rasa.infrastructure.")
            )
        if forbidden:
            violations.append(f"{relative}: {', '.join(sorted(forbidden))}")
    assert not violations, "Provider imports outside sanctioned boundaries:\n" + "\n".join(violations)


@pytest.mark.parametrize("source,module", [
    ("import tabula_rasa.storage.google_sheets as sheets", "tabula_rasa.app"),
    ("from tabula_rasa.storage import GoogleSheetsStorage", "tabula_rasa.app"),
    ("from tabula_rasa import storage", "tabula_rasa.app"),
    ("from ..storage.google_sheets import GoogleSheetsStorage", "tabula_rasa.application.sample"),
])
def test_guard_recognizes_provider_and_facade_imports(source, module) -> None:
    assert any(
        name == "tabula_rasa.storage" or name.startswith("tabula_rasa.storage.")
        for name in imported_modules(source, module)
    )
