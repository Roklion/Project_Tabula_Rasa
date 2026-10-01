"""Google Picker component for explicit folder and spreadsheet authorization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import streamlit as st


_PICKER_HTML = """
<button id="drive-folder-picker" type="button">Choose Google file</button>
<span id="drive-folder-status" role="status"></span>
"""

_PICKER_CSS = """
#drive-folder-picker {
    background: var(--st-primary-color);
    border: 1px solid var(--st-primary-color);
    border-radius: .5rem;
    color: white;
    cursor: pointer;
    font: inherit;
    font-weight: 600;
    padding: .55rem .9rem;
}
#drive-folder-picker:disabled { cursor: wait; opacity: .65; }
#drive-folder-status { margin-left: .65rem; color: var(--st-text-color); }
"""

_PICKER_JS = """
export default function(component) {
    const {data, parentElement, setTriggerValue} = component;
    const button = parentElement.querySelector('#drive-folder-picker');
    const status = parentElement.querySelector('#drive-folder-status');
    button.textContent = data.kind === 'spreadsheet'
        ? 'Choose ledger spreadsheet' : 'Choose Google Drive folder';

    function loadPickerLibrary() {
        if (window.google && window.google.picker) return Promise.resolve();
        if (window.__tabulaRasaPickerPromise) return window.__tabulaRasaPickerPromise;
        window.__tabulaRasaPickerPromise = new Promise((resolve, reject) => {
            if (window.gapi) {
                window.gapi.load('picker', {callback: resolve});
                return;
            }
            const existing = document.querySelector('script[data-tabula-rasa-picker]');
            if (existing) {
                existing.addEventListener('load', () => {
                    window.gapi.load('picker', {callback: resolve});
                }, {once: true});
                existing.addEventListener('error', reject, {once: true});
                return;
            }
            const script = document.createElement('script');
            script.src = 'https://apis.google.com/js/api.js';
            script.async = true;
            script.defer = true;
            script.dataset.tabulaRasaPicker = 'true';
            script.onload = () => window.gapi.load('picker', {callback: resolve});
            script.onerror = reject;
            document.head.appendChild(script);
        });
        return window.__tabulaRasaPickerPromise;
    }

    async function openPicker() {
        button.disabled = true;
        status.textContent = 'Opening Google Drive…';
        try {
            await loadPickerLibrary();
            const isSpreadsheet = data.kind === 'spreadsheet';
            const view = new google.picker.DocsView(isSpreadsheet
                ? google.picker.ViewId.SPREADSHEETS : google.picker.ViewId.FOLDERS);
            view.setIncludeFolders(!isSpreadsheet);
            view.setSelectFolderEnabled(!isSpreadsheet);
            view.setMimeTypes(isSpreadsheet ? 'application/vnd.google-apps.spreadsheet'
                : 'application/vnd.google-apps.folder');
            const picker = new google.picker.PickerBuilder()
                .setOAuthToken(data.accessToken)
                .setDeveloperKey(data.apiKey)
                .setAppId(data.appId)
                .setOrigin(window.location.origin)
                .addView(view)
                .setCallback((result) => {
                    if (result.action === google.picker.Action.PICKED) {
                        const folders = result[google.picker.Response.DOCUMENTS];
                        const folder = folders[0];
                        setTriggerValue('selected', {
                            id: folder[google.picker.Document.ID],
                            name: folder[google.picker.Document.NAME]
                        });
                        status.textContent =
                            `Selected: ${folder[google.picker.Document.NAME]}`;
                    } else if (result.action === google.picker.Action.CANCEL) {
                        status.textContent = 'No file selected.';
                    }
                    button.disabled = false;
                })
                .build();
            picker.setVisible(true);
        } catch (error) {
            status.textContent = 'Google Picker could not be opened.';
            button.disabled = false;
            setTriggerValue('failed', true);
        }
    }

    button.onclick = openPicker;
}
"""

_folder_picker_component = st.components.v2.component(
    "google_drive_folder_picker",
    html=_PICKER_HTML,
    css=_PICKER_CSS,
    js=_PICKER_JS,
)


def _file_picker(
    *,
    access_token: str,
    api_key: str,
    project_number: str,
    key: str,
    kind: str,
) -> Mapping[str, Any] | None:
    """Render Google Picker and return a newly selected file."""
    result = _folder_picker_component(
        data={
            "accessToken": access_token,
            "apiKey": api_key,
            "appId": project_number,
            "kind": kind,
        },
        key=key,
        on_selected_change=lambda: None,
        on_failed_change=lambda: None,
    )
    selected = getattr(result, "selected", None)
    return selected if isinstance(selected, Mapping) else None


def folder_picker(**kwargs) -> Mapping[str, Any] | None:
    """Select a Drive storage folder."""
    return _file_picker(kind="folder", **kwargs)


def spreadsheet_picker(**kwargs) -> Mapping[str, Any] | None:
    """Grant drive.file access by explicitly selecting a Google spreadsheet."""
    return _file_picker(kind="spreadsheet", **kwargs)
