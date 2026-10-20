"""Server-only migration bindings; grants remain in tenant secret custody."""

import json
from pathlib import Path
import re


FILE_ENV = 'TABULA_RASA_MIGRATED_BINDINGS_FILE'


def load_migrated_bindings(settings, environment):
    """Return explicit binding metadata, or None for the ordinary native runtime.

    A configured but invalid file always stops startup. It cannot select a
    resolver, load a grant, migrate data or activate bookkeeping authority.
    """
    if FILE_ENV not in environment:
        return None
    try:
        if settings.access_mode != 'named_user' or settings.trusted_entity_id:
            raise ValueError
        path = environment[FILE_ENV]
        if not isinstance(path, str) or not path.strip():
            raise ValueError
        with Path(path).open('rb') as source:
            content = source.read(131073)
        if len(content) > 131072:
            raise ValueError
        payload = json.loads(content)
        if not isinstance(payload, dict) or set(payload) != {'profiles'}:
            raise ValueError
        rows = payload['profiles']
        if not isinstance(rows, list) or not rows:
            raise ValueError
        entities, profiles, backends = {}, {}, {}
        fields = {'entity_id', 'profile_key', 'spreadsheet_id', 'receipt_folder_id', 'mode'}
        for row in rows:
            if not isinstance(row, dict) or set(row) != fields:
                raise ValueError
            if any(not isinstance(value, str) or value != value.strip() for value in row.values()):
                raise ValueError
            entity, profile = row['entity_id'], row['profile_key']
            if (not entity or len(entity) > 256 or entity in entities or profile in profiles
                    or not re.fullmatch(r'[a-z][a-z0-9_-]{0,47}', profile)
                    or not row['spreadsheet_id']
                    or row['mode'] not in {'rehearsal', 'commercial_production'}):
                raise ValueError
            entities[entity] = profile
            profiles[profile] = {'name': profile, 'spreadsheet_id': row['spreadsheet_id'],
                                 'google_drive': {'receipt_folder': {'id': row['receipt_folder_id']}}}
            backends[profile] = {'backend': 'postgres', 'entity_id': entity, 'mode': row['mode']}
        return entities, {'business_profiles': profiles, 'bookkeeping_backends': backends}
    except Exception:
        pass
    # Paths, source identities and accidentally supplied secrets stay private.
    raise RuntimeError('Invalid migrated runtime configuration.')
