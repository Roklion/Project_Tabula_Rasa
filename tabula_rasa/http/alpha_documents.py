"""Explicit server-only synthetic Drive binding; no ambient profile fallback."""

from pathlib import Path
import tomllib

from tabula_rasa.google_drive import DRIVE_SCOPE, GoogleDriveClient, load_oauth_config, validate_drive_profile_settings
from tabula_rasa.google_drive.errors import PROFILE_KEY_PATTERN
from tabula_rasa.infrastructure.drive_composition import create_drive_document_store
from tabula_rasa.infrastructure.entity_documents import EntityDocumentStore

FILE_ENV = "TABULA_RASA_ALPHA_DOCUMENTS_FILE"
ERROR = "Alpha document binding failed. Check the private file, target, grant and managed folders."


def load_alpha_document_store(settings, environment):
    """Validate one configured hosted binding, including fresh folder ownership.

    Missing configuration preserves the explicit unavailable receipt surface.
    Supplied invalid configuration stops startup, never falls back. Reads only:
    no OAuth callback, folder provision, workbook access or authority activation.
    """
    path = environment.get(FILE_ENV)
    if path is None:
        return None
    try:
        if (not settings.hosted_alpha or settings.environment not in {"development", "staging"}
                or settings.trusted_entity_id != "alpha-synthetic" or not path
                or not Path(path).is_absolute()):
            raise ValueError
        with Path(path).open("rb") as source:
            content = source.read(65537)
        if len(content) > 65536:
            raise ValueError
        binding = tomllib.loads(content.decode("utf-8"))
        if (set(binding) != {"environment", "public_origin", "entity_id", "profile_key", "google_drive_oauth", "google_drive"}
                or binding["environment"] != settings.environment
                or binding["public_origin"] != settings.public_origin
                or binding["entity_id"] != settings.trusted_entity_id
                or not isinstance(binding["profile_key"], str)
                or not PROFILE_KEY_PATTERN.fullmatch(binding["profile_key"])):
            raise ValueError
        config = load_oauth_config(binding)
        grant = validate_drive_profile_settings(binding["google_drive"])
        if grant["scopes"] != [DRIVE_SCOPE]:
            raise ValueError
        folders = [grant.get(name, {}).get("id") for name in ("storage_root", "receipt_folder", "backup_folder")]
        if not all(folders) or len(set(folders)) != 3:
            raise ValueError
        profile = binding["profile_key"]
        # Existing owner checks fresh parents, kind, profile and root metadata.
        GoogleDriveClient(config, grant).validate_storage_configuration(profile)
        store = create_drive_document_store(profile, {"google_drive": grant}, binding)
        return EntityDocumentStore(binding["entity_id"], profile, store)
    except Exception:
        pass
    # No raw TOML/provider/secret exception survives in the exception context.
    raise RuntimeError(ERROR)
