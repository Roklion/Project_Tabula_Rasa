# Transactions extraction and redesign audit

This audit separates the mechanical code movement, intentional presentation
changes, and review remediations delivered for issue #54. It supplements the
[Transactions surface inventory](TRANSACTIONS_SURFACE_INVENTORY.md) so later
changes can review behavior independently from package organization.

## Integrated issue #54 change set

Pull request #83 merged as `501946e`. Its source commits divide into the
following categories.

### Mechanical extraction

Commit `3405d73` moved the existing Transactions block out of
`tabula_rasa/app.py` and introduced the explicit `TransactionsContext` call
boundary. The mechanical portion consists of:

- moving transaction creation, ledger filtering, row selection, editing,
  deletion, and receipt management out of the application entrypoint;
- replacing direct use of application globals with context fields and
  callbacks for the selected profile, storage, Drive client, confirmed writes,
  error reporting, and widget resets;
- moving the receipt-indicator helper with the Transactions surface;
- retaining `tabula_rasa/app.py` as the tested Streamlit entrypoint and sole
  dispatcher; and
- preserving widget keys, form names, table-generation keys, action names,
  payloads, rerun points, stop behavior, and storage/Drive calls.

Commit `746144d` is also mechanical. It relocated the extracted package from
the initially proposed `tabula_rasa/pages/transactions` path to
`tabula_rasa/page_renderers/transactions`. Streamlit reserves the sibling
`pages` directory for legacy multipage discovery, so the corrected location
preserves the application's custom sidebar as the only navigation surface.

### Intentional redesign and visible-contract work

The presentation portion of `3405d73` is limited to the issue #54 hierarchy:

- the two established tabs gained explicit `Add transaction` and
  `View & edit ledger` section headings;
- each section gained concise guidance for its existing workflow;
- creation and editing retained their existing field order and
  type-dependent controls;
- the ledger retained all eleven columns, latest-date-first ordering,
  structured filters, and single-row editing; and
- the permanent-delete warning and receipt-reference-versus-Drive-file
  distinction remained explicit.

No receipt upload during creation, text search, bulk selection, or bulk
mutation was introduced. Those behaviors remain owned by issues #55-#57.

### Review remediations

- `e03ca30` made source and destination selector indexes tolerate a historical
  account row that is no longer available. This complements the tested
  inactive-current-account contract without making required transaction
  fields optional.
- `746144d` corrected the Streamlit-reserved package location described above.
- `0dc9e8f` skips JSON decoding for the exact initialized-empty receipt value
  `[]`; legacy empty strings still follow receipt-reference initialization.
- Suggestions to substitute today's date, `$0.01`, or empty required fields
  for malformed ledger data were rejected. Such defaults could hide
  corruption and overwrite a row with invented accounting values.

## Post-merge responsibility split

The follow-up branch makes the mechanical architecture independently visible
without changing presentation or domain behavior:

| Commit | Responsibility | Resulting module |
| --- | --- | --- |
| `a767982` | Shell dependency contract and creation form | `context.py`, `creation.py` |
| `2f6efd6` | Existing receipt links, unlinking, orphan linking, and upload | `receipts.py` |
| `78474c7` | Filters, ledger table, selection, edit, delete, and receipt delegation | `ledger.py` |

`renderer.py` is now page coordination only: it renders the header and tabs,
loads profile-scoped accounts and categories, derives hierarchy labels, and
dispatches the creation and ledger renderers. Dependencies remain one-way;
none of the extracted modules imports `tabula_rasa.app` or performs rendering,
storage reads, or Drive reads at import time.

## End-to-end AppTest evidence

All UI scenarios continue to launch `tabula_rasa/app.py`; no extracted module
is used as a substitute test entrypoint.

| Scenario | Transactions behavior exercised |
| --- | --- |
| `tests/_app_google_workflow_scenario.py` | Table-generation stability; failed-create state preservation; successful Expense, Income, and Transfer creation; account filters including both transfer sides; latest-date-first ledger order; editing while retaining the currently referenced inactive account; confirmed update; guarded permanent delete; navigation-away generation reset |
| `tests/_app_receipt_unlink_scenario.py` | Eleven-column ledger tail; receipt indicator; profile-scoped account filter; unlink request/cancel/confirm; failed and successful unlink handling; Drive-file preservation; linking an eligible unreferenced receipt |
| `tests/_app_csv_reporting_scenario.py` | Transaction data remains integrated with duplicate validation, CSV output, and report totals through the application shell |
| `tests/_app_hierarchy_workflow_scenario.py` | Transactions remain integrated with hierarchy changes and profile-isolated application state |

Validation recorded after each responsibility extraction:

- `ruff check .` passed.
- `python -m pytest` passed all 373 tests.
- `tests/test_app_google_workflow.py` passed all four subprocess-isolated
  application scenarios after each code-movement increment.

## Review boundary for future transaction work

Future reviews can treat changes to `renderer.py` or `context.py` as page-shell
contract changes, `creation.py` as create-workflow changes, `ledger.py` as
filter/selection/edit/delete changes, and `receipts.py` as post-creation Drive
and reference-management changes. Cross-module changes should explain why one
stable responsibility cannot contain the behavior.
