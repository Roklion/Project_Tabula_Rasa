"""Coordinator for the Data & backup page renderers."""

from __future__ import annotations

from tabula_rasa.page_renderers.data_backup.cloud_recovery import (
    render_cloud_backup,
    render_recovery_status,
)
from tabula_rasa.page_renderers.data_backup.context import DataBackupContext
from tabula_rasa.page_renderers.data_backup.exports import render_exports
from tabula_rasa.page_renderers.data_backup.imports import render_imports
from tabula_rasa.presentation import render_page_header


def render_data_backup(context: DataBackupContext) -> None:
    """Render cloud backup, recovery, export, and import workflows in order."""
    render_page_header(
        "Data & backup",
        "Your live records are stored in the private Google Sheets workbook.",
    )
    render_cloud_backup(context)
    render_recovery_status(context)
    render_exports(context)
    render_imports(context)
