# Transactions surface inventory

This inventory records the Transactions behavior preserved by issue #54 at
merge commit `501946e`. It is a review aid for later transaction work; it does
not authorize the proposed receipt-on-create, search, or bulk workflows owned
by issues #55-#57.

## Page coordination and data boundaries

- The application shell supplies a profile key, profile secrets,
  configuration revision, profile-scoped Google Sheets storage, a
  profile-scoped Google Drive client factory, confirmed-write handling,
  storage-error reporting, and widget-reset callbacks through
  `TransactionsContext`.
- Page entry prefetches `Accounts`, `Categories`, and `Transactions`, loads all
  accounts plus categories, and stops after reporting a storage failure.
- Creation choices include active accounts only. Editing includes active
  accounts plus the inactive source or destination currently referenced by
  the selected transaction.
- Google Sheets remains the transaction source of truth. Receipt files remain
  in the selected profile's configured Google Drive receipt folder.
- The page has two tabs in this order: `Add transaction`, then
  `View & edit ledger`.

## Add transaction

The section heading is `Add transaction` with guidance that the form records
income, expenses, or transfers in the active account set.

| Order | Control or field | Visible contract | State key or action |
| --- | --- | --- | --- |
| 1 | Transaction type | Segmented `Income`, `Expense`, `Transfer`; defaults to `Expense` | Type-specific controls and account/category keys |
| 2 | Date | Defaults to today | `add_transaction_date` |
| 3a | Category | Income/expense only; limited to categories of the selected type | `add_transaction_category_income` or `add_transaction_category_expense` |
| 3b | Amount | Positive amount, two-decimal display; beside Category for income/expense | `add_transaction_amount` |
| 4 | From Account | Active accounts only | `add_transaction_account_<type>` |
| 5 | To account | Transfer only; excludes the selected source account | `add_transaction_to_account` |
| 6a | Payee / customer | Optional text | `add_transaction_payee` |
| 6b | Reference (optional) | Optional text beside Payee / customer | `add_transaction_reference` |
| 7 | Description / memo | Optional text | `add_transaction_description` |
| 8 | Save transaction | Primary, full-width form submit | Confirmed `create_transaction` write |

Creation states and feedback:

- With no active account, the form is replaced by `Create an active account
  before recording transactions.`
- Income or Expense with no matching category shows `Create a <type> category
  first.`
- A transfer with no second active account shows `Create a second active
  account before recording a transfer.`
- Successful confirmed storage writes show `Transaction saved.`, schedule
  `reset_add_transaction_form`, and reset every listed creation widget on the
  following rerun.
- Validation or storage failures are handled by the shared confirmed-write
  path: entered values remain available, an error is shown, and no success or
  reset is reported.
- Duplicate submission protection uses the unchanged `create_transaction`
  action name and complete transaction payload.

## Ledger and structured filters

The section heading is `View & edit ledger` with guidance to filter the
ledger, select one row, and manage details or receipts.

| Order | Control | Visible contract | State key |
| --- | --- | --- | --- |
| 1 | From | Defaults to January 1 of the current year | `ledger_start` |
| 2 | To | Defaults to today | `ledger_end` |
| 3 | Type | `All`, `Income`, `Expense`, `Transfer` | `ledger_filter_type_<profile>` |
| 4 | Accounts | Multi-select; a transfer matches when either side is selected | `ledger_filter_accounts_<profile>` |
| 5 | Ledger table | Latest date first, stable ordering, single-row selection | `transaction_ledger_<profile>_<generation>` |

The ledger preserves all eleven columns in this order: `Date`, `Type`,
`Account`, `To account`, `Category`, `Payee`, `Description`, `Amount`,
`Receipt`, `Reference`, and `ID`. Amount uses `$%.2f`; Receipt shows a paperclip
when decoded receipt references are non-empty. Malformed receipt metadata does
not mark the row as having a receipt.

Selecting a table row sets `edit_transaction_id`. If the current edit target
is outside the filtered result, the latest visible transaction becomes the
target. The table-generation key prevents stale table selection from crossing
the application shell's intentional Transactions-page reset boundary.

Ledger read failures use the shared storage-error report and stop the page.
An empty ledger renders the empty table and does not render the edit expander
or receipt controls.

## Edit and permanent delete

The page instructs the user to select or double-click one row. The `Edit
transaction` expander opens automatically after table selection and otherwise
retains the single current target.

| Order | Control or field | Visible contract | State key or action |
| --- | --- | --- | --- |
| 1 | Transaction to edit | Label includes date, type, formatted amount, and short ID | `edit_transaction_id` |
| 2 | Edit account / Edit from account | Active accounts plus the transaction's current source account | `edit_transaction_account_<profile>_<id>` |
| 3a | Edit to account | Transfer only; active accounts plus current source/destination | `edit_transaction_to_account_<profile>_<id>` |
| 3b | Edit category | Non-transfer only; categories matching the immutable transaction type | `edit_transaction_category_<profile>_<id>` |
| 4a | Edit date | Current transaction date | `edit_transaction_date_<profile>_<id>` |
| 4b | Edit amount | Positive value, two-decimal display | `edit_transaction_amount_<profile>_<id>` |
| 5 | Edit payee / customer | Existing value or blank | `edit_transaction_payee_<profile>_<id>` |
| 6 | Edit reference | Existing value or blank | `edit_transaction_reference_<profile>_<id>` |
| 7 | Edit description | Existing value or blank | `edit_transaction_description_<profile>_<id>` |
| 8 | Permanent-delete acknowledgement | Explicit warning plus required checkbox | `edit_transaction_confirm_delete_<profile>_<id>` |
| 9a | Save changes | Primary form submit | Confirmed `edit_transaction` write |
| 9b | Permanently delete | Destructive form submit with delete icon/help | Confirmed `delete_transaction` write |

Edit and deletion feedback:

- A transfer whose source and destination match shows `Transfer accounts must
  be different.` and does not write.
- A delete request without the acknowledgement shows `Confirm that you
  understand deletion is permanent.` and does not write.
- Confirmed success messages are `Transaction updated.` and `Transaction
  deleted.`
- Shared confirmed-write handling preserves form state on failed writes and
  prevents duplicate edit/delete submissions.
- Deleting a transaction deletes its ledger row and receipt references. It
  does not delete any linked Google Drive file.
- Required transaction fields remain strict storage data. The editor does not
  invent dates, amounts, types, or account IDs for malformed ledger rows.

## Existing receipt management

Receipt management appears only below the selected existing transaction. It
is intentionally absent from transaction creation.

When no receipt folder is configured, the page explains how to connect Google
Drive through local Business profiles and gives the manual
`<transaction-id>-original-file-name` naming convention. Drive-client failures
show the returned safe Google Drive error.

### Reference initialization and existing links

- Receipt references are decoded from the selected transaction. Invalid data
  shows the storage error and disables reference-dependent actions.
- A legacy empty reference field triggers a one-time profile/folder-scoped
  Drive lookup for the selected transaction, conversion to manifest
  references, and a Sheets update. Failure shows `Existing receipt references
  could not be initialized.` plus the safe error.
- Each reference renders a Google Drive link and `Remove receipt` request.
- Removal uses a profile-and-transaction-scoped candidate key, asks `Remove
  <name> from this transaction? The file will remain in Google Drive.`, and
  offers `Cancel` and `Remove reference`.
- Unlink failure shows `Receipt reference was not removed.` plus the storage
  error. Success reruns and shows `Receipt removed: <name>. The file remains in
  Google Drive.`

### Linking an unreferenced Drive receipt

- The page gathers receipt IDs referenced by every transaction. Legacy-empty
  or malformed rows are excluded from orphan decisions so their files cannot
  be incorrectly offered for relinking.
- Profile receipt-list failure shows `Unreferenced Google Drive receipts could
  not be listed.` plus the safe Drive error.
- Files missing valid integrity metadata are omitted and reported as
  `<count> receipt(s) need integrity metadata before they can be linked.`
- Eligible files appear in `Unreferenced receipt`, keyed by
  `receipt-existing-select-<profile>-<transaction>`, with an explanation that
  they are app-managed files in this profile's receipt folder and are not
  linked elsewhere.
- `Link selected receipt` uses the corresponding scoped action key. Failure
  shows `The receipt could not be linked.` plus the storage error. Success
  reruns and shows `Receipt linked: <name>`.
- When none are eligible, the page shows `No unreferenced receipts are
  available in Google Drive.`

### Upload and link

- `Upload receipt` accepts one PDF, PNG, JPG/JPEG, WebP, or HEIC file and uses
  `receipt-upload-<transaction-id>`.
- After selection, guidance explains that the original filename is retained
  and a numeric suffix resolves collisions.
- `Upload receipt to Google Drive` is primary and uses
  `receipt-upload-button-<transaction-id>`.
- Upload is scoped to the selected profile, transaction, and configured receipt
  folder. Drive upload failures show the returned safe error.
- If upload succeeds but manifest conversion or Sheets linking fails, the page
  states that the file was uploaded but not linked and instructs the user to
  retry. It does not claim full success.
- Confirmed upload-and-link success shows `Receipt uploaded and linked:
  <name>` and reruns.

## Explicit non-goals at this baseline

- No receipt upload during transaction creation.
- No ledger text search.
- No bulk selection or bulk mutation.
- No Drive-file deletion from transaction or receipt-reference deletion.
- No local transaction store or alternate ledger source of truth.
