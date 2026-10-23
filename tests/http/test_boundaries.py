"""Prevent transport code from becoming an alternate domain/storage layer."""

import ast
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_handlers_have_no_infrastructure_sql_or_streamlit_imports():
    for path in (ROOT / "tabula_rasa/http/routes").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            assert not any(name.startswith((
                "sqlalchemy", "psycopg", "streamlit", "tabula_rasa.infrastructure",
                "tabula_rasa.storage", "tabula_rasa.reference_data",
            )) for name in modules), str(path)
        assert "execute(" not in source


def test_api_schema_import_does_not_load_legacy_ui_or_google_clients():
    result = subprocess.run([sys.executable, "-c",
        "import sys; from tabula_rasa.http.app import create_app; create_app(schema_only=True).openapi(); "
        "assert not {'streamlit', 'gspread', 'tabula_rasa.storage'}.intersection(sys.modules)"],
        cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_migrated_startup_checks_work_without_legacy_runtime_dependencies():
    result = subprocess.run([sys.executable, '-m', 'tests.http.migrated_runtime_probe'],
        cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
