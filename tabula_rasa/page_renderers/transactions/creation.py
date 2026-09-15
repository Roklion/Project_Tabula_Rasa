"""Transaction creation controls."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from uuid import uuid4

import streamlit as st

from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.page_renderers.transactions.transaction_form import (
    render_transaction_fields,
    render_transaction_type,
    transaction_payload_from_draft,
    validate_transaction_draft,
)
from tabula_rasa.page_renderers.transactions.receipts import (
    handle_confirmed_transaction_receipts,
    prepare_receipt_uploads,
    receipt_creation_workflow_key,
    creation_receipt_workflow,
    render_receipt_creation_recovery,
    render_receipt_uploader,
)
from tabula_rasa.page_renderers.transactions.recurrence_controls import (
    edit_defaults_with_pending_payload,
    render_recurrence_controls,
    restore_recurrence_controls,
)
from tabula_rasa.recurrence_state import transaction_create_pending_state
from tabula_rasa.page_renderers.tag_selector import (
    inline_tag_name_error,
    tag_selector_error,
)
from tabula_rasa.storage import StorageConflictError, StorageValidationError


def render_add_transaction(
    context: TransactionsContext,
    *,
    account_map: Mapping[str, str],
    categories: Sequence[Mapping[str, object]],
    category_paths: Mapping[str, str],
    payees: Sequence[Mapping[str, object]],
    tags: Sequence[Mapping[str, object]],
) -> None:
    """Render the existing profile-scoped transaction creation workflow."""
    recovery = creation_receipt_workflow(context)
    if isinstance(recovery, Mapping) and recovery.get("mixed_use_source_id"):
        # Mixed-use recovery is rendered by its source-aware tab; rendering it
        # here as well would register the same retry widget twice.
        return
    if render_receipt_creation_recovery(context):
        return
    st.subheader("Add transaction")
    st.caption("Record income, expenses, or transfers in the active account set.")
    transaction_form_keys = (
        "add_transaction_date",
        "add_transaction_amount",
        "add_transaction_category_income",
        "add_transaction_category_expense",
        "add_transaction_category_transfer",
        "add_transaction_account_income",
        "add_transaction_account_expense",
        "add_transaction_account_transfer",
        "add_transaction_to_account",
        "add_transaction_payee",
        "add_transaction_tags",
        "add_transaction_reference",
        "add_transaction_description",
        "add_transaction_receipts",
        "add_transaction_recurring",
        "add_transaction_recurrence_unit",
        "add_transaction_recurrence_interval",
        "add_transaction_recurrence_name",
        "add_transaction_recurrence_end",
    )
    context.reset_widget_state_if_requested(
        "reset_add_transaction_form",
        keys=transaction_form_keys,
    )
    pending_recurrence = transaction_create_pending_state(context.profile_key)
    pending_payload = pending_recurrence.payload(st.session_state)
    kind = render_transaction_type(
        default=str(
            pending_payload.get("kind", "Expense")
            if pending_payload is not None
            else "Expense"
        )
    )
    if not account_map:
        st.warning("Create an active account before recording transactions.")
        return

    categories_for_kind = [
        category for category in categories if category["kind"] == kind
    ]
    if kind != "Transfer" and not categories_for_kind:
        st.warning(f"Create a {kind.lower()} category first.")
        return
    account_paths = {
        str(account_id): str(account_path)
        for account_path, account_id in account_map.items()
    }

    with st.form("add_transaction", clear_on_submit=False):
        draft = render_transaction_fields(
            mode="add",
            defaults=edit_defaults_with_pending_payload(
                {"kind": kind}, pending_payload
            ),
            account_ids=list(account_map.values()),
            categories=categories,
            account_paths=account_paths,
            category_paths=category_paths,
            payees=payees,
            tags=tags,
            key_prefix="add_transaction",
        )
        recurrence = None
        if kind == "Expense":
            restore_recurrence_controls(
                st.session_state,
                pending_payload,
                key_prefix="add_transaction",
            )
            recurrence = render_recurrence_controls(
                label="Repeat this Expense",
                key_prefix="add_transaction",
                help_text=(
                    "Create a profile-local schedule and this transaction "
                    "as its initial occurrence."
                ),
            )
        recurring = bool(recurrence and recurrence.enabled)
        receipt_uploads = render_receipt_uploader(
            key="add_transaction_receipts",
        )
        save_error = st.empty()
        submitted = st.form_submit_button(
            "Save transaction", type="primary", width="stretch"
        )
        if submitted:
            if draft_error := validate_transaction_draft(draft):
                save_error.error(draft_error)
            elif tag_error := tag_selector_error("add_transaction_tags"):
                save_error.error(tag_error)
            elif tag_error := inline_tag_name_error(draft["new_tag_name"]):
                save_error.error(tag_error)
            elif (
                kind == "Expense"
                and not recurring
                and pending_recurrence.has_pending(st.session_state)
            ):
                save_error.error(
                    "A previous recurring save is incomplete. Re-enable "
                    "Repeat this Expense to retry it before recording a "
                    "different expense."
                )
            else:
                payload = transaction_payload_from_draft(draft)
                try:
                    prepared_receipts = prepare_receipt_uploads(receipt_uploads or [])
                except Exception as error:  # noqa: BLE001 - show safe validation
                    save_error.error(f"Receipt validation failed: {error}")
                else:
                    receipt_folder = None
                    drive_settings = context.profile_secrets.get("google_drive")
                    if isinstance(drive_settings, Mapping):
                        receipt_folder = drive_settings.get("receipt_folder")
                    if prepared_receipts and not (
                        isinstance(receipt_folder, Mapping) and receipt_folder.get("id")
                    ):
                        save_error.error(
                            "Configure a Google Drive receipt folder for this "
                            "profile before saving a transaction with receipts."
                        )
                    else:

                        def clear_pending_recurring_if_active() -> None:
                            if kind == "Expense" and recurring:
                                pending_recurrence.clear(st.session_state)

                        if kind == "Expense" and recurring:
                            pending_ids = pending_recurrence.ensure_ids(
                                st.session_state,
                                configuration_revision=str(
                                    context.profile_secrets.get("spreadsheet_id")
                                    or context.configuration_revision
                                ),
                            )
                            payload.update(
                                recurrence.schedule_fields(
                                    description=draft["description"],
                                    fallback_name="Recurring expense",
                                )
                            )
                            payload = pending_recurrence.remember_payload(
                                st.session_state,
                                {**payload, **pending_ids},
                            )

                        # Keep the existing submission fingerprint independent of the UUID.
                        transaction_id = str(uuid4())

                        def operation():
                            try:
                                return (
                                    context.storage.create_recurring_expense(**payload)[
                                        "transaction"
                                    ]
                                    if kind == "Expense" and recurring
                                    else context.storage.create_transaction(
                                        transaction_id=transaction_id, **payload
                                    )
                                )
                            except (StorageConflictError, StorageValidationError):
                                if kind == "Expense" and recurring:
                                    pending_recurrence.clear(st.session_state)
                                raise

                        context.confirmed_write(
                            "create_transaction",
                            payload,
                            operation,
                            lambda _result: (
                                st.session_state.get("write_success_notice")
                                or (
                                    "Transaction saved. Receipt processing needs "
                                    "attention; use the recovery controls above."
                                    if prepared_receipts
                                    and st.session_state.get(
                                        receipt_creation_workflow_key(
                                            context.profile_key
                                        )
                                    )
                                    else "Transaction saved."
                                )
                            ),
                            on_success=(
                                lambda: (
                                    (
                                        clear_pending_recurring_if_active(),
                                        context.schedule_widget_reset(
                                            "reset_add_transaction_form"
                                        ),
                                    )
                                    if not prepared_receipts
                                    else None
                                )
                            ),
                            on_confirmed=(
                                lambda result: (
                                    (
                                        clear_pending_recurring_if_active(),
                                        handle_confirmed_transaction_receipts(
                                            context,
                                            result,
                                            prepared_receipts,
                                        ),
                                    )
                                    if prepared_receipts
                                    else None
                                )
                            ),
                            report_error=save_error.error,
                        )
