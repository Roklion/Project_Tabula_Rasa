from pydantic import Field

from .accounts import DecimalString
from .common import DTO
from .mutations import ProtectedMutation


class TransactionChanges(DTO):
    txn_date: str
    kind: str
    amount: DecimalString
    account_id: str
    to_account_id: str = ''
    category_id: str = ''
    payee_id: str = ''
    tag_ids: list[str] = Field(default_factory=list)
    description: str = ''
    reference: str = ''
    new_payee_name: str = ''
    new_tag_name: str = ''


class TransactionCreate(TransactionChanges):
    transaction_id: str


class Transaction(DTO):
    id: str
    txn_date: str
    kind: str
    amount: DecimalString
    account_id: str
    to_account_id: str
    category_id: str
    payee_id: str
    tag_ids: list[str]
    description: str
    reference: str
    created_at: str
    source_type: str
    baseline: str


class TransactionList(DTO):
    items: list[Transaction]


class TransactionUpdate(ProtectedMutation):
    changes: TransactionChanges


class Posting(DTO):
    id: str
    target_type: str
    target_id: str
    side: str
    amount: DecimalString
    payee_id: str = ''
    description: str = ''


class JournalChanges(DTO):
    txn_date: str
    description: str
    postings: list[Posting]


class JournalCreate(JournalChanges):
    entry_id: str


class Journal(JournalChanges):
    id: str
    created_at: str
    updated_at: str
    baseline: str


class JournalList(DTO):
    items: list[Journal]


class JournalUpdate(ProtectedMutation):
    changes: JournalChanges


def transaction_response(row):
    values = {name: row[name] for name in Transaction.model_fields if name != 'source_type'}
    return Transaction(**values, source_type=row.get('source_type', ''))


def journal_response(row):
    values = {name: row[name] for name in Journal.model_fields if name != 'postings'}
    return Journal(**values, postings=[Posting(**{name: line[name] for name in Posting.model_fields}) for line in row['postings']])
