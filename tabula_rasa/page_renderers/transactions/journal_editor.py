"""Create and edit complete balanced journal entries."""

from __future__ import annotations

from collections.abc import Collection, Mapping, MutableMapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import uuid4

import streamlit as st

from tabula_rasa.journal import JournalValidationError, normalize_journal_postings
from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.page_renderers.transactions.payee_selector import (
    render_payee_selector,
)


JournalEditorMode = Literal["create", "edit"]


@dataclass(frozen=True)
class JournalCreationState:
    """Mode-specific values used by the creation-mode discard guard."""

    draft: Mapping[str, object]


def _journal_key(profile_key: str, mode: JournalEditorMode, name: str) -> str:
    return f"journal_{mode}_{name}_{profile_key}"


def _scope_prefix(
    profile_key: str,
    mode: JournalEditorMode,
    scope: str,
) -> str:
    return f"journal_{mode}_{profile_key}_{scope}"


def _line_key(prefix: str, line_id: str, field: str) -> str:
    return f"{prefix}_{line_id}_{field}"


def _is_active(item: Mapping[str, object]) -> bool:
    value = item.get("active", True)
    return str(value).strip().casefold() in {"true", "1"}


def _journal_target_options(
    accounts: Sequence[Mapping[str, object]],
    categories: Sequence[Mapping[str, object]],
    account_paths: Mapping[str, str],
    category_paths: Mapping[str, str],
    *,
    retained_tokens: Collection[str] = (),
) -> tuple[list[str], dict[str, str]]:
    """Return typed target tokens and unambiguous managed display labels."""
    tokens: list[str] = []
    labels: dict[str, str] = {}
    for account in accounts:
        account_id = str(account.get("id") or "").strip()
        token = f"account:{account_id}"
        if not account_id or (not _is_active(account) and token not in retained_tokens):
            continue
        classification = str(account.get("classification") or "Account")
        status = " · inactive" if not _is_active(account) else ""
        labels[token] = (
            f"{account_paths.get(account_id, account.get('name', account_id))} "
            f"· {classification} account{status}"
        )
        tokens.append(token)
    for category in categories:
        category_id = str(category.get("id") or "").strip()
        if not category_id:
            continue
        token = f"category:{category_id}"
        kind = str(category.get("kind") or "Category")
        labels[token] = (
            f"{category_paths.get(category_id, category.get('name', category_id))} "
            f"· {kind} category"
        )
        tokens.append(token)
    return tokens, labels


def _line_target_options(
    target_options: Sequence[str],
    target_labels: Mapping[str, str],
    current_target: str,
) -> tuple[list[str], dict[str, str]]:
    options = list(target_options)
    labels = dict(target_labels)
    if current_target and current_target not in options:
        options.append(current_target)
        labels[current_target] = f"{current_target} · unavailable"
    return options, labels


def _target_token(posting: Mapping[str, object]) -> str:
    target_type = str(posting.get("target_type") or "").strip().casefold()
    target_id = str(posting.get("target_id") or "").strip()
    return f"{target_type}:{target_id}" if target_type and target_id else ""


def _posting_defaults(posting: Mapping[str, object]) -> dict[str, object]:
    side = str(posting.get("side") or "").strip().casefold()
    try:
        amount = float(posting.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0.0
    return {
        "target": _target_token(posting),
        "debit": amount if side == "debit" else 0.0,
        "credit": amount if side == "credit" else 0.0,
        "payee": str(posting.get("payee_id") or ""),
        "description": str(posting.get("description") or ""),
    }


def _initialize_lines(
    *,
    profile_key: str,
    mode: JournalEditorMode,
    scope: str,
    postings: Sequence[Mapping[str, object]],
) -> tuple[str, ...]:
    line_ids_key = _journal_key(profile_key, mode, f"line_ids_{scope}")
    existing = st.session_state.get(line_ids_key)
    if isinstance(existing, (list, tuple)) and len(existing) >= 2:
        return tuple(str(value) for value in existing)

    normalized_postings = list(postings)
    while len(normalized_postings) < 2:
        normalized_postings.append({})
    line_ids = tuple(
        str(posting.get("id") or uuid4()) for posting in normalized_postings
    )
    st.session_state[line_ids_key] = list(line_ids)
    prefix = _scope_prefix(profile_key, mode, scope)
    for line_id, posting in zip(line_ids, normalized_postings, strict=True):
        defaults = _posting_defaults(posting)
        for field, value in defaults.items():
            if field == "payee":
                # The managed selector owns its initial default. Supplying both
                # a session value and a nonzero index triggers a visible warning.
                continue
            st.session_state.setdefault(_line_key(prefix, line_id, field), value)
    return line_ids


def _clear_line_widget_state(prefix: str, line_id: str) -> None:
    for field in ("target", "debit", "credit", "payee", "description", "remove"):
        st.session_state.pop(_line_key(prefix, line_id, field), None)


def _add_line(profile_key: str, mode: JournalEditorMode, scope: str) -> None:
    line_ids_key = _journal_key(profile_key, mode, f"line_ids_{scope}")
    line_ids = list(st.session_state.get(line_ids_key, ()))
    line_ids.append(str(uuid4()))
    st.session_state[line_ids_key] = line_ids


def _remove_line(
    profile_key: str,
    mode: JournalEditorMode,
    scope: str,
    line_id: str,
) -> None:
    line_ids_key = _journal_key(profile_key, mode, f"line_ids_{scope}")
    line_ids = [
        str(value) for value in st.session_state.get(line_ids_key, ())
    ]
    if len(line_ids) <= 2 or line_id not in line_ids:
        return
    st.session_state[line_ids_key] = [
        existing for existing in line_ids if existing != line_id
    ]
    _clear_line_widget_state(_scope_prefix(profile_key, mode, scope), line_id)


def _split_target(value: object) -> tuple[str, str]:
    target_type, separator, target_id = str(value or "").partition(":")
    return (target_type, target_id) if separator else ("", "")


def _render_posting_lines(
    *,
    profile_key: str,
    mode: JournalEditorMode,
    scope: str,
    postings: Sequence[Mapping[str, object]],
    accounts: Sequence[Mapping[str, object]],
    categories: Sequence[Mapping[str, object]],
    account_paths: Mapping[str, str],
    category_paths: Mapping[str, str],
    payees: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    line_ids = _initialize_lines(
        profile_key=profile_key,
        mode=mode,
        scope=scope,
        postings=postings,
    )
    original_by_id = {str(posting.get("id") or ""): posting for posting in postings}
    target_options, target_labels = _journal_target_options(
        accounts,
        categories,
        account_paths,
        category_paths,
        retained_tokens={
            token
            for posting in postings
            if (token := _target_token(posting))
        },
    )
    prefix = _scope_prefix(profile_key, mode, scope)
    rows: list[dict[str, object]] = []
    st.caption(
        "Each line needs one managed account or category and an amount on "
        "exactly one side."
    )
    grid = st.container(key=f"journal_{mode}_posting_grid")
    for position, line_id in enumerate(line_ids, start=1):
        with grid.container(
            border=True,
            key=f"journal_line_card_{profile_key}_{mode}_{line_id}",
        ):
            st.markdown(f"**Line {position}**")
            account_column, debit_column, credit_column = st.columns(
                [2.4, 1, 1], gap="small"
            )
            target_key = _line_key(prefix, line_id, "target")
            current_target = str(st.session_state.get(target_key) or "")
            line_target_options, line_target_labels = _line_target_options(
                target_options, target_labels, current_target
            )
            target = account_column.selectbox(
                "Account",
                [""] + line_target_options,
                format_func=lambda value: line_target_labels.get(
                    value, "Choose an account or category" if not value else value
                ),
                key=target_key,
            )
            debit = debit_column.number_input(
                "Debit",
                min_value=0.0,
                step=1.0,
                format="%.2f",
                key=_line_key(prefix, line_id, "debit"),
            )
            credit = credit_column.number_input(
                "Credit",
                min_value=0.0,
                step=1.0,
                format="%.2f",
                key=_line_key(prefix, line_id, "credit"),
            )
            description_column, payee_column, remove_column = st.columns(
                [2.4, 2, 0.7],
                gap="small",
                vertical_alignment="bottom",
            )
            description = description_column.text_input(
                "Description",
                key=_line_key(prefix, line_id, "description"),
            )
            payee_id, _new_payee_name = render_payee_selector(
                payees,
                key=_line_key(prefix, line_id, "payee"),
                selected_id=str(
                    st.session_state.get(
                        _line_key(prefix, line_id, "payee"),
                        original_by_id.get(line_id, {}).get("payee_id", ""),
                    ) or ""
                ),
                preserve_selected_id=mode == "edit",
                accept_new_options=False,
                container=payee_column,
            )
            remove_column.button(
                "Remove",
                key=_line_key(prefix, line_id, "remove"),
                disabled=len(line_ids) <= 2,
                help=(
                    "A journal editor keeps at least two rows."
                    if len(line_ids) <= 2
                    else f"Remove journal line {position}"
                ),
                width="stretch",
                on_click=_remove_line,
                args=(profile_key, mode, scope, line_id),
            )
        target_type, target_id = _split_target(target)
        rows.append(
            {
                "id": line_id,
                "target_type": target_type,
                "target_id": target_id,
                "debit": debit,
                "credit": credit,
                "payee_id": payee_id,
                "description": description,
            }
        )
    st.button(
        "+ Add line",
        key=f"{prefix}_add_line",
        on_click=_add_line,
        args=(profile_key, mode, scope),
    )
    return rows


def _decimal_amount(value: object) -> Decimal:
    try:
        amount = Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")
    return amount.quantize(Decimal("0.01")) if amount.is_finite() else Decimal("0.00")


def journal_totals(rows: Sequence[Mapping[str, object]]) -> tuple[Decimal, Decimal]:
    """Return display totals without treating them as save validation."""
    debit = sum((_decimal_amount(row.get("debit")) for row in rows), Decimal("0.00"))
    credit = sum(
        (_decimal_amount(row.get("credit")) for row in rows), Decimal("0.00")
    )
    return debit, credit


def _render_totals(rows: Sequence[Mapping[str, object]]) -> None:
    debits, credits = journal_totals(rows)
    difference = debits - credits
    debit_column, credit_column, difference_column = st.columns(3)
    debit_column.metric("Total Debits", f"${debits:,.2f}")
    credit_column.metric("Total Credits", f"${credits:,.2f}")
    difference_column.metric("Difference", f"${difference:,.2f}")


def _normalized_postings(
    rows: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        return normalize_journal_postings(rows), None
    except JournalValidationError as error:
        return [], str(error)


def _draft_snapshot(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return {
        "lines": tuple(
            (
                str(row.get("target_type") or ""),
                str(row.get("target_id") or ""),
                str(_decimal_amount(row.get("debit"))),
                str(_decimal_amount(row.get("credit"))),
                str(row.get("payee_id") or ""),
                str(row.get("description") or ""),
            )
            for row in rows
        )
    }


def _guard_postings(postings: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Exclude draft line identities from duplicate-submission fingerprints."""
    return [
        {
            key: posting.get(key)
            for key in (
                "position",
                "target_type",
                "target_id",
                "side",
                "amount",
                "payee_id",
                "description",
            )
        }
        for posting in postings
    ]


def _reset_created_journal(
    context: TransactionsContext,
    generation_key: str,
) -> None:
    st.session_state[generation_key] = int(st.session_state.get(generation_key, 0)) + 1
    context.schedule_widget_reset("reset_add_transaction_form")


def render_new_journal_entry(
    context: TransactionsContext,
    *,
    shared_date: date,
    shared_description: str,
    accounts: Sequence[Mapping[str, object]],
    categories: Sequence[Mapping[str, object]],
    account_paths: Mapping[str, str],
    category_paths: Mapping[str, str],
    payees: Sequence[Mapping[str, object]],
) -> JournalCreationState:
    """Render the advanced create editor without persisting partial rows."""
    generation_key = _journal_key(context.profile_key, "create", "generation")
    generation = int(st.session_state.get(generation_key, 0))
    scope = str(generation)
    st.caption(
        "Record one balanced entry with two or more debit and credit postings. "
        "Journal entries do not support receipts, Tags, recurrence, or copying."
    )
    rows = _render_posting_lines(
        profile_key=context.profile_key,
        mode="create",
        scope=scope,
        postings=(),
        accounts=accounts,
        categories=categories,
        account_paths=account_paths,
        category_paths=category_paths,
        payees=payees,
    )
    _render_totals(rows)
    normalized, validation_error = _normalized_postings(rows)
    if validation_error:
        st.info(validation_error)
    save_error = st.empty()
    save_requested = st.button(
        "Save journal entry",
        type="primary",
        width="stretch",
        disabled=validation_error is not None,
        key=f"journal_create_save_{context.profile_key}_{generation}",
    )
    if save_requested:
        # Generate identities before the first attempt and retain them while
        # an uncertain or failed submission remains on this draft generation.
        entry_id_key = _journal_key(
            context.profile_key, "create", f"entry_id_{generation}"
        )
        entry_id = str(st.session_state.setdefault(entry_id_key, str(uuid4())))
        payload = {
            "txn_date": shared_date,
            "description": shared_description,
            "postings": _guard_postings(normalized),
        }
        context.confirmed_write(
            "create_journal_entry",
            payload,
            lambda: context.services.journals.create(
                entry_id=entry_id,
                txn_date=shared_date,
                description=shared_description,
                postings=normalized,
            ),
            "Journal entry saved.",
            on_success=lambda: _reset_created_journal(context, generation_key),
            report_error=save_error.error,
        )
    return JournalCreationState(_draft_snapshot(rows))


def _clear_edit_state_from(
    state: MutableMapping[str, object], profile_key: str, entry_id: str
) -> None:
    scope = entry_id
    prefix = _scope_prefix(profile_key, "edit", scope)
    line_ids_key = _journal_key(profile_key, "edit", f"line_ids_{scope}")
    for line_id in state.get(line_ids_key, ()):
        for field in (
            "target",
            "debit",
            "credit",
            "payee",
            "description",
            "remove",
        ):
            state.pop(_line_key(prefix, str(line_id), field), None)
    state.pop(line_ids_key, None)
    state.pop(_journal_key(profile_key, "edit", f"baseline_{entry_id}"), None)
    for suffix in ("date", "description", "confirm_delete"):
        state.pop(f"{prefix}_{suffix}", None)


def _clear_edit_state(profile_key: str, entry_id: str) -> None:
    _clear_edit_state_from(st.session_state, profile_key, entry_id)


def _journal_edit_baseline(
    state: MutableMapping[str, object],
    *,
    profile_key: str,
    configuration_revision: str,
    entry: Mapping[str, object],
) -> Mapping[str, object]:
    """Keep the first complete entry snapshot as the stale-write expectation."""
    entry_id = str(entry.get("id") or "")
    active_key = _journal_key(profile_key, "edit", "active_entry")
    previous_entry_id = str(state.get(active_key) or "")
    if previous_entry_id and previous_entry_id != entry_id:
        _clear_edit_state_from(state, profile_key, previous_entry_id)
    state[active_key] = entry_id

    baseline_key = _journal_key(profile_key, "edit", f"baseline_{entry_id}")
    stored = state.get(baseline_key)
    configuration_changed = isinstance(stored, Mapping) and str(
        stored.get("configuration_revision") or ""
    ) != str(configuration_revision)
    if not isinstance(stored, Mapping) or configuration_changed:
        if configuration_changed:
            _clear_edit_state_from(state, profile_key, entry_id)
        stored = {
            "configuration_revision": str(configuration_revision),
            "entry": deepcopy(dict(entry)),
        }
        state[baseline_key] = stored
    baseline = stored.get("entry")
    return baseline if isinstance(baseline, Mapping) else deepcopy(dict(entry))


def render_journal_entry_editor(
    context: TransactionsContext,
    *,
    entry: Mapping[str, object],
    accounts: Sequence[Mapping[str, object]],
    categories: Sequence[Mapping[str, object]],
    account_paths: Mapping[str, str],
    category_paths: Mapping[str, str],
    payees: Sequence[Mapping[str, object]],
) -> bool:
    """Render fixed-type edit and whole-entry deletion for one journal."""
    entry_id = str(entry.get("id") or "")
    baseline_entry = _journal_edit_baseline(
        st.session_state,
        profile_key=context.profile_key,
        configuration_revision=context.configuration_revision,
        entry=entry,
    )
    scope = entry_id
    prefix = _scope_prefix(context.profile_key, "edit", scope)
    with st.expander("Edit journal entry", expanded=True):
        st.caption(
            "This saved record remains a Multi-line Journal. Every save or "
            "deletion applies to the complete balanced entry."
        )
        transaction_date = st.date_input(
            "Date",
            value=date.fromisoformat(str(baseline_entry.get("txn_date"))),
            key=f"{prefix}_date",
        )
        description = st.text_input(
            "Description / memo",
            value=str(baseline_entry.get("description") or ""),
            key=f"{prefix}_description",
        )
        postings = baseline_entry.get("postings")
        rows = _render_posting_lines(
            profile_key=context.profile_key,
            mode="edit",
            scope=scope,
            postings=(postings if isinstance(postings, Sequence) else ()),
            accounts=accounts,
            categories=categories,
            account_paths=account_paths,
            category_paths=category_paths,
            payees=payees,
        )
        _render_totals(rows)
        normalized, validation_error = _normalized_postings(rows)
        if validation_error:
            st.info(validation_error)
        edit_error = st.empty()
        st.warning(
            "Deleting this journal entry permanently removes its parent and all "
            "posting lines and cannot be undone.",
            icon="⚠️",
        )
        confirm_delete = st.checkbox(
            "I understand this complete journal entry will be permanently deleted",
            key=f"{prefix}_confirm_delete",
        )
        save_column, delete_column = st.columns(2)
        save_requested = save_column.button(
            "Save changes",
            type="primary",
            width="stretch",
            disabled=validation_error is not None,
            key=f"{prefix}_save",
        )
        with delete_column:
            with st.container(key="destructive_journal_edit_delete"):
                delete_requested = st.button(
                    "Permanently delete",
                    icon=":material/delete_forever:",
                    width="stretch",
                    key=f"{prefix}_delete",
                )
        if save_requested:
            payload = {
                "id": entry_id,
                "txn_date": transaction_date,
                "description": description,
                "postings": _guard_postings(normalized),
            }
            context.confirmed_write(
                "edit_journal_entry",
                payload,
                lambda: context.services.journals.update(
                    entry_id,
                    expected=baseline_entry,
                    txn_date=transaction_date,
                    description=description,
                    postings=normalized,
                ),
                "Journal entry updated.",
                on_success=lambda: _clear_edit_state(context.profile_key, entry_id),
                report_error=edit_error.error,
            )
        if delete_requested:
            if not confirm_delete:
                edit_error.error(
                    "Confirm that you understand deletion is permanent."
                )
            else:
                context.confirmed_write(
                    "delete_journal_entry",
                    {"id": entry_id, "expected_entry": baseline_entry},
                    lambda: context.services.journals.delete(
                        entry_id,
                        expected=baseline_entry,
                    ),
                    "Journal entry deleted.",
                    on_success=lambda: _clear_edit_state(
                        context.profile_key, entry_id
                    ),
                    report_error=edit_error.error,
                )
    return False


__all__ = [
    "JournalCreationState",
    "journal_totals",
    "render_journal_entry_editor",
    "render_new_journal_entry",
]
