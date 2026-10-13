"""Explicit operator rotation of a drained named-user environment."""

import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tabula_rasa.http.config import HttpSettings
from tabula_rasa.infrastructure.oidc import OidcSettings
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.runtime import Database
from tabula_rasa.infrastructure.postgres.sessions import PostgresSessionRepository


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-epoch', type=int, required=True)
    args = parser.parse_args(argv)
    database = None
    failed = False
    try:
        settings = HttpSettings.from_environment()
        if settings.access_mode != 'named_user':
            raise ValueError('Named-user mode required.')
        oidc = OidcSettings.from_environment(settings, os.environ)
        # Explicit process mapping avoids an unrelated .env.local database.
        database = Database(DatabaseSettings.from_environment(os.environ, required=True))
        PostgresSessionRepository(database, settings.environment, oidc.configuration_hash).rotate_configuration(args.expected_epoch)
    except Exception:
        failed = True
    finally:
        if database is not None:
            try:
                database.dispose()
            except Exception:
                failed = True
    if failed:
        print('Identity rotation failed; verify the environment and current epoch.')
        return 1
    print('Identity configuration rotated; start only workers with the new configuration.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
