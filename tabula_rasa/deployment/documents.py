"""Read-only provider preflight using the same binding as HTTP startup."""

import os

from tabula_rasa.http.alpha_documents import load_alpha_document_store
from tabula_rasa.http.config import HttpSettings


def check(environment):
    settings = HttpSettings(
        environment.get("TABULA_RASA_ENVIRONMENT", ""),
        environment.get("TABULA_RASA_PUBLIC_ORIGIN", ""),
        environment.get("TABULA_RASA_RELEASE_ID", "development"),
        environment.get("TABULA_RASA_TRUSTED_ENTITY_ID") or None,
        environment.get("TABULA_RASA_ALPHA_USERNAME", ""),
        environment.get("TABULA_RASA_ALPHA_PASSWORD_HASH", ""),
    )
    store = load_alpha_document_store(settings, environment)
    if store is None:
        raise ValueError("An explicit alpha document binding is required.")
    # Exercise fresh profile/folder-scoped receipt reads without exposing data.
    inventory = store.inventory(settings.trusted_entity_id, fresh=True)
    if inventory.needing_integrity:
        raise ValueError("Inspect receipt integrity before alpha acceptance.")


def main():
    try:
        check(dict(os.environ))
    except Exception:
        pass
    else:
        print("alpha_documents_readable")
        return
    raise SystemExit("Alpha document preflight failed. Inspect private target, grant, folders and receipt integrity.")


if __name__ == "__main__":
    main()
