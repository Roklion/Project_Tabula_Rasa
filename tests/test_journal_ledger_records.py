from tabula_rasa.ledger_records import (
    combine_ledger_entries, filter_ledger_entries, flatten_ledger_entries,
    ledger_summary_frame, search_ledger_entries, selected_parent_ids, sort_ledger_entries,
)


ACCOUNTS = [{"id": "cash", "name": "Cash"}]
CATEGORIES = [{"id": "office", "name": "Office", "kind": "Expense"}, {"id": "meals", "name": "Meals", "kind": "Expense"}]
JOURNAL = {"id": "j1", "txn_date": "2026-09-20", "description": "Split purchase", "postings": [
    {"id": "l1", "target_type": "category", "target_id": "office", "side": "Debit", "amount": "100", "payee": "Stationer", "description": "Pens"},
    {"id": "l2", "target_type": "category", "target_id": "meals", "side": "Debit", "amount": "50", "payee": "Cafe", "description": "Lunch"},
    {"id": "l3", "target_type": "account", "target_id": "cash", "side": "Credit", "amount": "150", "payee": "", "description": ""},
]}
SIMPLE = {"id": "t1", "txn_date": "2026-09-19", "kind": "Expense", "account_id": "cash", "category_id": "office", "amount": "9", "payee": "Software"}


def test_flatten_keeps_ordinary_row_and_complete_journal_with_parent_map():
    entries = combine_ledger_entries([SIMPLE], [JOURNAL])
    summaries = ledger_summary_frame(entries, ACCOUNTS, CATEGORIES).to_dict("records")
    frame, parents = flatten_ledger_entries(entries, summaries, ACCOUNTS, CATEGORIES)
    assert parents == ["journal:j1"] * 4 + ["t1"]
    assert frame["Type"].tolist() == ["Journal", "↳ Posting", "↳ Posting", "↳ Posting", "Expense"]
    assert frame.iloc[0]["Amount"] == 150
    assert frame.iloc[1]["Debit"] == 100
    assert frame.iloc[3]["Credit"] == 150
    assert frame.iloc[4]["Amount"] == 9
    assert selected_parent_ids(parents, [0, 1, 3, 4, -1, 10]) == ("journal:j1", "t1")


def test_filter_and_search_matching_one_posting_retains_every_sibling():
    entries = combine_ledger_entries([SIMPLE], [JOURNAL])
    filtered = filter_ledger_entries(entries, targets=[("category", "meals")])
    assert len(filtered) == 1
    summaries = ledger_summary_frame(entries, ACCOUNTS, CATEGORIES).to_dict("records")
    for term in ("Cafe", "LUNCH", "Meals", "split purchase", "journal:j1"):
        matched = search_ledger_entries(entries, summaries, ACCOUNTS, CATEGORIES, term)
        frame, parents = flatten_ledger_entries(matched, summaries, ACCOUNTS, CATEGORIES)
        assert len(frame) == 4
        assert parents == ["journal:j1"] * 4
    assert not search_ledger_entries(entries, summaries, ACCOUNTS, CATEGORIES, "150")


def test_sort_parents_first_then_flatten_and_keep_journal_together():
    entries = combine_ledger_entries([SIMPLE], [JOURNAL])
    summaries = ledger_summary_frame(entries, ACCOUNTS, CATEGORIES).to_dict("records")
    ordered = sort_ledger_entries(entries, summaries, field="Amount", descending=False)
    _, parents = flatten_ledger_entries(ordered, summaries, ACCOUNTS, CATEGORIES)
    assert parents == ["t1"] + ["journal:j1"] * 4
    assert filter_ledger_entries(entries, kind="Expense") == [SIMPLE]
    assert not filter_ledger_entries(entries, tag_ids=["tag"])
    assert not filter_ledger_entries(entries, start="2026-10-01", end="2026-01-01")


def test_simple_only_has_no_debit_credit_columns():
    entries = combine_ledger_entries([SIMPLE], [])
    summaries = ledger_summary_frame(entries, ACCOUNTS, CATEGORIES).to_dict("records")
    frame, parents = flatten_ledger_entries(entries, summaries, ACCOUNTS, CATEGORIES)
    assert "Debit" not in frame and "Credit" not in frame
    assert parents == ["t1"]
