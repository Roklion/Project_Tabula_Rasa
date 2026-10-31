"""Synthetic secret-file and Drive fixtures for the hosted composition contract."""

import hashlib

import toml

from tabula_rasa.google_drive import DRIVE_SCOPE
from tests.drive_fixtures import receipt_drive_file


def binding(environment="staging", profile="stage-receipts"):
    return {
        "environment": environment,
        "public_origin": f"https://{environment}.example.test",
        "entity_id": "alpha-synthetic",
        "profile_key": profile,
        "google_drive_oauth": {"client_id": "synthetic-client", "client_secret": "synthetic-secret",
                               "redirect_uris": ["http://localhost:8501/"]},
        "google_drive": {"refresh_token": "synthetic-" + profile, "token_uri": "https://oauth2.googleapis.com/token",
                         "scopes": [DRIVE_SCOPE],
                         **{key: {"id": profile + "-" + key, "name": key}
                            for key in ("storage_root", "receipt_folder", "backup_folder")}},
    }


def write_binding(tmp_path, values=None):
    values = values or binding()
    path = tmp_path / (values["environment"] + ".toml")
    path.write_text(toml.dumps(values), encoding="utf-8")
    return str(path)


class SyntheticDrive:
    """Durable across runtime restarts, explicitly scoped provider test fixture."""

    def __init__(self, profile):
        self.profile = profile
        self.files = {}
        self.bytes = {}
        self.uploads = 0
        self.deletes = 0

    def validate_storage_configuration(self, profile):
        assert profile == self.profile

    def list_profile_receipts(self, *, profile_key, folder_id, _force_refresh):
        assert profile_key == self.profile and folder_id == self.profile + "-receipt_folder"
        return list(self.files.values())

    def receipt_file(self, *, profile_key, folder_id, file_id):
        from tabula_rasa.google_drive import GoogleDriveAccessError
        assert profile_key == self.profile
        assert folder_id == getattr(self, 'folder', self.profile + '-receipt_folder')
        if getattr(self, 'fail', False) or file_id not in self.files:
            raise GoogleDriveAccessError('The receipt is not in this selected receipt folder.')
        return self.files[file_id]

    def upload_receipt(self, *, profile_key, folder_id, original_name, content, mime_type, receipt_id):
        self.list_profile_receipts(profile_key=profile_key, folder_id=folder_id, _force_refresh=True)
        self.uploads += 1
        key = "provider-" + receipt_id
        item = receipt_drive_file(key, original_name, profile_key=profile_key, receipt_id=receipt_id,
            sha256=hashlib.sha256(content).hexdigest(), original_name=original_name, size=len(content), parent_id=folder_id)
        item["mimeType"] = mime_type
        self.files[key], self.bytes[key] = item, content
        return item

    def download_file(self, key):
        return self.bytes[key]

    def delete_file(self, key):
        self.deletes += 1
        raise AssertionError("Unlink must retain bytes")
