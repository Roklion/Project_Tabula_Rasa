"""Transaction creation controls."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import uuid4

import streamlit as st

from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.page_renderers.transactions.transaction_form import (
    render_transaction_fields,
    render_transaction_type,
    validate_transaction_draft,
)
from tabula_rasa.page_renderers.transactions.receipts import (
    handle_confirmed_transaction_receipts,
    prepare_receipt_uploads,
    receipt_creation_workflow_key,
    render_receipt_creation_recovery,
    render_receipt_uploader,
)
from tabula_rasa.page_renderers.transactions.recurrence_controls import (
    render_recurrence_controls,
)
from tabula_rasa.page_renderers.tag_selector import (
    inline_tag_name_error,
    tag_selector_error,
)
from tabula_rasa.storage import StorageConflictError, StorageValidationError


def _pending_recurring_ids(
    state: dict[str, object],
    profile: str,
    configuration_revision: str | None = None,
) -> tuple[str, str]:
    """Keep a recurring schedule and initial transaction ID stable on retry."""
    schedule_key = f"recurring_pending_schedule_id_{profile}"
    transaction_key = f"recurring_pending_transaction_id_{profile}"
    schedule_id = str(state.get(schedule_key) or uuid4())
    transaction_id = str(state.get(transaction_key) or uuid4())
    state[schedule_key] = schedule_id
    state[transaction_key] = transaction_id
    if configuration_revision is not None:
        state[f"recurring_pending_configuration_revision_{profile}"] = (
            configuration_revision
        )
    return schedule_id, transaction_id


def _pending_recurring_create_exists(state: dict[str, object], profile: str) -> bool:
    """Keep an incomplete recurring create on its convergence path."""
    return bool(
        state.get(f"recurring_pending_schedule_id_{profile}")
        or state.get(f"recurring_pending_transaction_id_{profile}")
    )


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
    recovery = st.session_state.get(receipt_creation_workflow_key(context.profile_key))
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
    kind = render_transaction_type()
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
            defaults={"kind": kind},
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
            recurrence = render_recurrence_controls(
                label="Repeat this Expense",
                key_prefix="add_transaction",
                help_text=(
                    "Create a profile-local schedule and this transaction "
                    "as its initial occurrence."
                ),
            )
        recurring = bool(recurrence and recurrence.enabled)
        pending_schedule_key = f"recurring_pending_schedule_id_{context.profile_key}"
        pending_transaction_key = (
            f"recurring_pending_transaction_id_{context.profile_key}"
        )
        pending_payload_key = f"recurring_pending_payload_{context.profile_key}"
        pending_schedule_id = str(st.session_state.get(pending_schedule_key) or "")
        pending_transaction_id = str(
            st.session_state.get(pending_transaction_key) or ""
        )
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
                and _pending_recurring_create_exists(
                    st.session_state, context.profile_key
                )
            ):
                save_error.error(
                    "A previous recurring save is incomplete. Re-enable "
                    "Repeat this Expense to retry it before recording a "
                    "different expense."
                )
            else:
                payload = {
                    "txn_date": draft["txn_date"],
                    "kind": draft["kind"],
                    "amount": draft["amount"],
                    "account_id": draft["account_id"],
                    "to_account_id": draft["to_account_id"],
                    "category_id": draft["category_id"],
                    "payee_id": draft["payee_id"],
                    "new_payee_name": draft["new_payee_name"],
                    "tag_ids": draft["tag_ids"],
                    "new_tag_name": draft["new_tag_name"] or "",
                    "description": draft["description"],
                    "reference": draft["reference"],
                }
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

                        def clear_pending_recurring_ids() -> None:
                            st.session_state.pop(pending_schedule_key, None)
                            st.session_state.pop(pending_transaction_key, None)
                            st.session_state.pop(pending_payload_key, None)
                            st.session_state.pop(
                                f"recurring_pending_configuration_revision_{context.profile_key}",
                                None,
                            )

                        def clear_pending_recurring_if_active() -> None:
                            if kind == "Expense" and recurring:
                                clear_pending_recurring_ids()

                        if kind == "Expense" and recurring:
                            pending_schedule_id, pending_transaction_id = (
                                _pending_recurring_ids(
                                    st.session_state,
                                    context.profile_key,
                                    str(
                                        context.profile_secrets.get("spreadsheet_id")
                                        or context.configuration_revision
                                    ),
                                )
                            )
                            payload.update({
                                "schedule_id": pending_schedule_id,
                                "transaction_id": pending_transaction_id,
                                **recurrence.schedule_fields(
                                    description=draft["description"],
                                    fallback_name="Recurring expense",
                                ),
                            })
                            previous_payload = st.session_state.get(pending_payload_key)
                            if isinstance(previous_payload, Mapping):
                                payload = {
                                    **previous_payload,
                                    "schedule_id": pending_schedule_id,
                                    "transaction_id": pending_transaction_id,
                                }
                            else:
                                st.session_state[pending_payload_key] = dict(payload)

                        def operation():
                            try:
                                return (
                                    context.storage.create_recurring_expense(**payload)[
                                        "transaction"
                                    ]
                                    if kind == "Expense" and recurring
                                    else context.storage.create_transaction(**payload)
                                )
                            except (StorageConflictError, StorageValidationError):
                                if kind == "Expense" and recurring:
                                    clear_pending_recurring_ids()
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
