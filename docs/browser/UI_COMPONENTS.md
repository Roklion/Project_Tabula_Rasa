# Browser UI components

[design.md](../../design.md) is the authoritative interface specification.
This guide maps its current browser implementation to shared component owners.
[Bookkeeping](BOOKKEEPING.md) and [concurrency](CONCURRENCY.md) define behavioral
contracts; [visual review](VISUAL_REVIEW.md) defines capture and manual review.
Historical design audits and implementation waves are retained in
[the foundation discussion](https://github.com/Roklion/Project_Tabula_Rasa/issues/325#issuecomment-6304015838).

## Shared ownership and consumer contract

`tokens.css` is the sole shared stylesheet/token owner. Existing short aliases
(`--surface`, `--secondary`, `--border`, `--hover`, `--selected`, `--primary`,
`--focus`) remain available. Use descriptive tokens for new code; avoid copying
palette/type/spacing values into page styles. `--text-muted` is palette metadata,
not an instruction to use low-contrast text for essential descriptions.

`ActionButton` forwards native button attributes/events, defaults to
`type="button"`, and permits an explicit submit type. `pending` disables the
button and marks it busy without changing its accessible name. It does not own
confirmation, retry, mutation or draft state. Navigation stays a real link;
`.button` is the existing primary-link hook, with `.action-secondary` available
for a secondary styled link. Do not use `aria-disabled` alone to prevent navigation.

`PageHeader`, `SectionHeader` and `TableRegion` only own semantic markup and
layout. Field labeling/error association stays with `States.Field`, shared
`Fields.tsx` adapters and `fieldErrors.ts`. Form validation, loaded metadata,
baseline capture, context/cache isolation and successful reset remain with
`CreateEditor`, `ProtectedEditor`, `useLoadedForm` and `ScopeBoundary`.
`ConfirmationDialog` keeps its focus, Escape and pending-operation behavior;
callers select a destructive tone only for an actually destructive operation.

Table consumers keep their native table/caption/header semantics and stable IDs.
Use `.tableText` for deliberate wrapping, `.amount`/`.numeric` for comparable
columns and `aria-selected` only when a workflow implements selection. The 40px
row size is a minimum; wrapping and accessible action targets may increase it.
Metrics use `.metrics`, optional `.metric-context` and `.metric-positive`,
`.metric-negative`, `.metric-warning`, `.metric-loading`, `.metric-unavailable`.
Always explain state in text; unavailable is an em dash, never invented zero.


## Shell, navigation and layout

`Shell`, `EntitySelection` and `navigation.ts` own context presentation and route
links. Retain semantic navigation, selected-route feedback, menu focus behavior
and dirty-navigation guards. Long business labels must fit the sidebar; display
the full selection in wrapping text while native selectors retain keyboard behavior.
Independent sections use shared spacing tokens, including Dashboard actions and
report controls. Meaningful route titles replace generic placeholders.

Use the current Soft workspace palette and geometry from `tokens.css` and
`design.md`: pale tinted surfaces, soft corners, 40px fine-pointer desktop
controls, 44px touch/narrow controls and a 960px form/editor width limit.
Do not copy historical audit values into new pages.

## Reports, ledger and filters

`ReportsPage` owns report presentation; `DateRangeFields` shares native date
adapters with the ledger. Preserve exact decimal strings and explain unavailable,
zero, negative and equation-difference states in text. Ordinary table rows remain
normal weight, comparable amounts align right and wide tables scroll locally.
`LedgerTable` retains complete journal grouping, subordinate postings, stable
logical entry IDs and links to source owners.

Transactions and Mileage use `FilterPanel` for above-table filter presentation.
Its accessible toggle exposes expanded state and a scope summary. Collapsing
retains mounted inputs, selected filters, results and export scope; it changes no
query value. Presentation preference remains scoped to page, business and user.
Report periods and workflow forms retain their own layout and stay expanded.

## Forms, confirmation and feedback

`FormSection` groups related fields with at most two desktop columns and stacks
at narrow widths. Shared field adapters retain labels, hint/error associations,
native multiple selection and inactive-reference choices. Journals preserve
posting IDs, draft totals and validation. Date fields stay compact alongside
taller tag lists. Reference lists have one visible page title and named tables.

`ConfirmationDialog` provides focus management, Escape behavior and live pending
feedback. Mutation owners guard duplicate submission and distinguish confirmed
success, safe rejection, reauthentication and uncertain outcomes. Preserve drafts
on failure and do not automatically retry a potentially completed write.
Grouping or styling an action does not transfer its authorization or mutation owner.

## Secondary records and receipts

Assets, recurring and mixed-use records retain their service-owned source,
projection and immutable-history boundaries. Mileage remains a separate manual
log with its own totals and CSV. Receipts retain source ownership, abort guards,
partial-result guidance, explicit unlink semantics and retained-file recovery.
Shared drop zones style the native chooser without replacing upload/import owners.

## Verification

`foundations.spec.ts`, `core-surfaces.spec.ts`, `forms-secondary.spec.ts` and
`ui-followup.spec.ts` cover shared controls, route families, protected forms,
long labels, pending/error/success feedback, keyboard navigation and local
overflow at desktop and narrow widths. Native HTTP/PostgreSQL journeys retain
success/failure and isolation ownership. Use [visual review](VISUAL_REVIEW.md)
to capture the untouched baseline and candidate separately, inspect their PNGs,
and record real device/browser/zoom observations. Automated axe and viewport
checks alone do not supply manual accessibility or release acceptance.
