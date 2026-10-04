"""Selected-profile workflow services for shell and transitional test contexts."""


def recurring_service(context):
    services = getattr(context, "services", None)
    service = getattr(services, "recurring", None)
    if service is not None:
        return service
    from tabula_rasa.infrastructure.google_sheets_recurring import (
        recurring_service_for_storage,
    )

    return recurring_service_for_storage(context.storage)


def mixed_use_service(context):
    services = getattr(context, "services", None)
    service = getattr(services, "mixed_use", None)
    if service is not None:
        return service
    from tabula_rasa.infrastructure.google_sheets_mixed_use import (
        mixed_use_service_for_storage,
    )

    return mixed_use_service_for_storage(context.storage)


def asset_service(context):
    services = getattr(context, "services", None)
    service = getattr(services, "assets", None)
    if service is not None:
        return service
    return context.storage._asset_service()
