"""Workflow capabilities supplied by the selected-profile application graph."""


def recurring_service(context):
    return context.services.recurring


def mixed_use_service(context):
    return context.services.mixed_use


def asset_service(context):
    return context.services.assets
