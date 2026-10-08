from typing import Annotated

from pydantic import StringConstraints

from .common import DTO
from .mutations import ProtectedMutation

DecimalString = Annotated[str, StringConstraints(pattern=r"^-?\d+(\.\d+)?$", max_length=100)]


class AccountCreate(DTO):
    name: str
    type: str
    opening_balance: DecimalString = "0.00"
    classification: str | None = None
    parent_id: str | None = None


class Account(DTO):
    id: str
    name: str
    type: str
    classification: str
    opening_balance: DecimalString
    active: bool
    created_at: str
    parent_id: str | None
    baseline: str


class AccountList(DTO):
    items: list[Account]


class AccountChanges(DTO):
    name: str
    type: str
    classification: str
    opening_balance: DecimalString
    active: bool
    parent_id: str | None = None


class AccountUpdate(ProtectedMutation):
    changes: AccountChanges


def account_response(record) -> Account:
    # Explicit allowlist; do not expose infrastructure/provider fields.
    return Account(
        id=record["id"], name=record["name"], type=record["type"],
        classification=record["classification"],
        opening_balance=record["opening_balance"], active=record["active"],
        created_at=record["created_at"], parent_id=record["parent_id"] or None,
        baseline=record["baseline"],
    )
