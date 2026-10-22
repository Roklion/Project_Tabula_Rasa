"""Read-only business tenancy preflight; never converts or reassigns records."""

import json

from tabula_rasa.application.identity import IdentityError
from tabula_rasa.infrastructure.postgres.business_tenancy import tenancy_inventory
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.runtime import Database, DatabaseError


def main():
    database = None
    try:
        database = Database(DatabaseSettings.from_environment(required=True))
        result = tenancy_inventory(database)
        print(json.dumps(result, sort_keys=True))
        return 0 if result['ready_for_constraint'] else 2
    except (IdentityError, DatabaseError, ValueError):
        print(json.dumps({'error': 'tenancy_preflight_unavailable'}))
        return 1
    finally:
        if database is not None:
            database.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
