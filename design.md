# Project Tabula Rasa — Design system

## Purpose and authority

This document is the durable user-interface and interaction specification for
Project Tabula Rasa. It defines the product character, visual tokens, layout
rules, reusable component behavior, responsive and accessibility requirements,
Streamlit constraints, page contracts, and objective UI acceptance criteria.

It is intentionally text-first. Screenshots are optional implementation
evidence; they do not replace the written contract.

Two kinds of authority must remain distinct:

- **Current-state authority:** When the question is what the application
  actually does now, the implementation and maintained tests are evidence of
  current behavior.
- **Intended UI authority:** When the question is what UI or interaction is
  intended, the active task requirements and this document are the durable
  design contract.

When code, tests, documentation, and this design disagree, identify the
discrepancy and reconcile it intentionally. Do not silently redefine intended
design because code drifted, and do not change runtime behavior as part of a
documentation-only cleanup.

The current application is a private, Google Sheets-backed bookkeeping tool
for one person or a small group of businesses. The active ledger remains
Google Sheets-backed. Architecture, setup, usage, and recovery detail belongs
in [Architecture](docs/ARCHITECTURE.md), [Setup](docs/SETUP.md),
[Using Tabula Rasa](docs/USING_TABULA_RASA.md), and
[Backup and recovery](docs/BACKUP_RECOVERY.md); this file should specify UI
intent rather than duplicate those guides.

**Current behavior:** The Streamlit composition refuses a profile configured
for bookkeeping maintenance or PostgreSQL before initializing its Sheet.
Backend activation is an operator procedure documented in
[Bookkeeping acceptance and cutover](docs/BOOKKEEPING_CUTOVER.md); no backend
picker or commercial authorization flow is added to the Streamlit interface.

## Product character

The interface should feel professional, calm, precise, trustworthy,
financially literate, operational, efficient, and purpose-built. It should
not feel like a marketing site, consumer-banking promotion, cryptocurrency
dashboard, gamified budgeting product, generic admin template, or decorative
spreadsheet. It must remain comfortable during extended bookkeeping sessions.

## Design principles

### Information before decoration

Financial data, bookkeeping state, required actions, warnings, and recovery
information take priority over ornament.

### Dense but readable

Use space efficiently for tables, filters, forms, navigation, financial rows,
validation summaries, backups, and imports. Use larger spacing only between
major information groups.

### Tables are primary

Transactions, mileage, accounts, categories, reports, and profile summaries
are core work surfaces. Charts support interpretation and must not become
decoration.

### One dominant action per workflow

Each independent form, tab, expander, or workflow section normally has one
obvious primary action. A multipurpose page may still contain several
independent workflows and must not hide valid secondary actions.

### Semantic, non-exclusive color

Use color for state, direction, risk, completion, selection, and attention.
Use text, signs, icons, or explicit messages as well; color is never the only
state indicator. Blue is the default interaction color, not a financial-gain
indicator.

### No hover-only behavior

Important actions, values, warnings, and states must remain visible or
keyboard-accessible without hover.

### Native Streamlit first

Prefer native Streamlit controls. Use custom CSS, HTML, or components only
when the benefit is substantial and maintainable.

### Safe actions are explicit

Destructive or consequential actions must state what changes before execution.
This includes permanent deletion, receipt-reference removal, credential
rotation, Drive disconnection, storage-root changes, imports, and backup
creation or upload.

### Profile context is always visible

The selected business and workbook context remain discoverable. Every
profile-sensitive read, write, import, export, receipt action, backup, cache,
selection, and prepared snapshot is scoped to that business.

## Visual tokens

### Color

| Token | Value | Use |
| --- | --- | --- |
| canvas | #F5F4F0 | Warm application background |
| surface-primary | #FFFFFF | Tables, forms, cards, and dialogs |
| surface-secondary | #FAFAF8 | Secondary grouped controls |
| surface-hover | #F2F3F4 | Row and control hover |
| surface-selected | #EAF0FC | Selected rows and active navigation |
| text-primary | #202124 | Main text and financial values |
| text-secondary | #62666B | Supporting descriptions |
| text-muted | #85898E | Timestamps and tertiary metadata |
| border-default | #DDDED9 | Standard boundaries |
| border-subtle | #E9E9E5 | Table separators |
| border-strong | #B8BAB6 | Focused or emphasized boundaries |
| interactive-primary | #3267D6 | Primary actions, links, selection |
| interactive-hover | #2858BC | Primary hover |
| interactive-focus | #6B96ED | Focus rings |
| success | #287A4B on #EAF5EE | Confirmed completion and healthy state |
| error | #B33A3A on #FBECEC | Failed or invalid state |
| warning | #996600 on #FFF5D9 | Attention and incomplete state |
| neutral | #62666B on #F1F2F1 | Pending or disabled state |

Use green for confirmed success, balance, and favorable movement; red for
errors, adverse movement, invalid state, and destructive actions; amber for
duplicates, incomplete setup, out-of-balance state, and review conditions;
blue for links, navigation, selection, primary actions, and information; and
neutral gray for pending or inactive context. Do not make every save button
green or every ledger amount colored.

### Financial values

Direction must remain clear without color:

```text
+$1,250.00
−$420.00
$0.00
```

Use a plus sign when positive direction matters, a consistent minus sign,
tabular numerals, and consistent currency precision. Right-align comparable
amount and balance columns. Ordinary ledger amounts normally use neutral text
because their meaning depends on account context. A negative balance is not
automatically an error; normal liability and equity stored signs are not
errors.

### Typography

Use a system sans-serif stack:

```css
font-family:
  Inter,
  ui-sans-serif,
  -apple-system,
  BlinkMacSystemFont,
  "Segoe UI",
  sans-serif;
```

| Role | Size | Weight |
| --- | ---: | ---: |
| Application title | 24px | 600 |
| Page title | 22px | 600 |
| Section title | 16px | 600 |
| Card title | 14px | 600 |
| Body and controls | 14px | 400 |
| Table text | 13–14px | 400 |
| Secondary text | 12px | 400 |
| Major metric | 26–32px | 600 |

Use tabular numerals for financial figures where supported. UI writing is
direct, specific, concise, consistent, and action-oriented. Prefer Save
transaction over Submit and an explicit duplicate count over vague success.

### Spacing, geometry, and elevation

Use a 4px base grid with approved values 4, 8, 12, 16, 20, 24, 32, and 40px.
Use 36–44px table rows, compact filter controls, 12–16px metric-card
padding, and 16px primary surface padding. Keep related controls 8–12px
apart and major groups 24–32px apart.

Use moderate corner radii, thin borders, subtle dividers, and restrained
shadows only where hierarchy benefits. Do not use gradients, glassmorphism,
heavy cell borders, saturated alternating rows, or rounded cards for every
block.

## Charts and metric cards

Charts are quiet, readable, and subordinate to the values they explain. Use
lines for trends, bars for period comparisons, horizontal bars for category
ranking, and stacked bars only when composition matters. Avoid 3D charts,
rainbow palettes, and charts that repeat a visible metric without adding
meaning.

Every chart has a clear title, scope, units, readable axes, limited gridlines,
and visible values or a useful tooltip. A typical chart is 220–320px high and
must render safely for empty and single-point data. Use blue as the primary
series and related muted tones for neutral categories; semantic colors are for
semantic series, not decoration.

Metric groups use a short label, primary value, and optional comparison or
context. Support normal, positive, negative, warning, loading, and unavailable
states. Unavailable data is shown as an em dash rather than zero unless the
value is truly zero. Do not put every metric in a heavily bordered card.

## Application shell

The shell uses the Project Tabula Rasa identity in the page title, sign-in
surface, sidebar, and documentation. The authenticated sidebar is ordered:

1. Dashboard
2. Transactions
3. Assets
4. Mileage
5. Accounts
6. Categories
7. Reports
8. Data & backup
9. Account settings, only when local loopback administration is enabled
10. Log out in the utility area

The Business selector shows each business name and a muted caption immediately
below it with the selected immutable profile key (`Profile key: <key>`).

Below the workbook metadata and utility controls, the authenticated sidebar
also contains a compact, read-only **Google Maps API usage** expander after
authentication. Routes API and Places API (New) are visibly separate. Each
quota row is compact: `Endpoint: usage/limit (time period)`. Raw project and
user dimensions, utilization, and per-row timestamps are omitted. Google's
maximum-integer quota sentinel is shown as **Unlimited**. After a successful
Monitoring response with no data points, the matching usage is shown as zero;
the expander-level caption explains that each row shows Google's latest sampled
rate from the lookback and retains the sampling and real-time caveats. Until
configured, the expander reports its setup guidance.
Read failures identify Service Usage or Cloud Monitoring and provide a safe
HTTP-status-based remediation hint without displaying Google response bodies.
It warns that Monitoring may lag several minutes (including up to about 240
seconds after sampling), and is not a real-time remaining-request or
billing/spend meter.

Require application-password authentication before any ledger page or workbook
data is visible. Show the business selector when profiles exist and the
selected workbook title on ordinary pages. The current password grants access
to every configured profile; the shell must not imply per-profile user
authorization.

Account settings is visually separated from operational navigation and is
available only when the local administration flag and loopback binding pass.
It is a settings surface, not a user-identity or permission-management page.
The login surface uses the keyed native login_surface container so its readable
desktop width does not depend on an undocumented Streamlit test ID.

A compact global footer exposes **Terms of Use | Privacy Policy** on the login
surface and every authenticated page. Each link opens a static public legal
document without requiring the application password or loading profiles,
credentials, workbooks, OAuth state, or ledger data.

When the profile changes, keep the new business and workbook visible and clear
or rebuild page-local filters, selections, edit targets, widget generations,
and pending notices. Never initialize or access another profile's storage
under the new selection.

Use one configuration snapshot for ledger initialization and page settings;
apply configuration changes together on the next rerun. If the selected
profile cannot be resolved, stop before rendering a ledger page and show a
safe reload/settings error. Never substitute another profile's workbook or
expose a raw traceback for this configuration failure.

## Commercial shell

**Current behavior** for the #311/#312 opt-in named-user foundation:

- Pending identity displays a loading state before any private feature is
  mounted. Missing/expired/revoked identity offers Sign in through the hosted
  provider. Failed callbacks show a clean sign-in failure page without provider
  query values. Authenticated users without active business access see Workspace
  setup required, an owner-contact instruction and Sign out, not an empty ledger.
- Named sessions show the existing business shell with a labeled Sign out
  control. Session loss or authorization-storage outage unmounts private queries,
  drafts and receipt views; confirmed identity/scope/version changes remount the
  existing private boundary. Visible tabs recheck on focus/pageshow/visibility
  and every 60 seconds. Same-origin sign-out signals contain no private data;
  they invalidate pending initial session responses as well as loaded private UI.
- If selected business access is removed while another authorized business
  remains, session validation selects an available authorized business and the
  private boundary remounts. Workspace setup required appears only when no
  available business remains.
- Logout clears the local browser even when server revocation cannot be
  confirmed, and displays a safe failure instead of claiming durable success.
  Authorization failure screens retain Sign out without restoring private UI;
  a reload during storage outage can obtain logout-only CSRF through a same-origin
  read. Network failure remains visible and does not claim cookie clearing.
  Read-only and setup users can inspect identity and sign out without ledger
  write permission. [Named-user authentication](docs/NAMED_USER_AUTH.md) owns the
  operator settings, session policy and remaining release gates. Organization
  onboarding and commercial switching UI remain subsequent epic slices.

**Current behavior** for the #277/#278/#279/#280/#281/#282/#283/#286 technical-alpha application:

- The React shell uses the visual tokens, typography and approximately 760px
  stacking boundary above. Navigation covers Dashboard, Transactions, Assets,
  Mileage, Accounts, Categories & contacts, Reports, and Data & backup in the same order.
  A labeled Menu button exposes navigation on narrow screens.
- The server-resolved business name is always visible. The fixed synthetic
  context is identified as technical-alpha development. This shell does not
  expose internal profile keys, workbook metadata, Google credentials or local
  administration controls as commercial authorization.
- #279's hosted development/staging mode protects the shell, assets and API
  with an environment-specific browser HTTP Basic prompt over HTTPS. It retains
  one fixed synthetic business; the gate grants operator access, not commercial
  membership. Minimal health/version probes are public. Production rejects this
  synthetic mode; #222 owns real login and session behavior. Hosted setup and
  acceptance remain subject to the [operator checkpoint](docs/COMMERCIAL_DEPLOYMENT.md).
- Dashboard and Reports show service-calculated profit/loss, balance-sheet
  sections, current earnings, the accounting-equation check and clearly labeled
  all-date account balances. Their From/To inputs govern the period/as-of date.
  Accounts, Categories and Payees/Tags offer shared create fields and tables,
  plus protected edits/removals/merges. Accounts deactivate; categories retain
  guarded removal without an invented inactive flag. Parent names are visible.
- The server-configured local business selector requires an explicit keep or
  discard-and-switch choice, is disabled during mutations and remounts queries
  and drafts after a confirmed context change. Failed switches preserve the current
  scope, private cache and draft while showing a selection error. Independent clients select
  independently. Functional selection never proves membership authorization.
- Transactions offers separate guarded navigation to Add transaction and Add
  journal forms. Creation uses the protected editors' shared fields; journals use
  target/side/amount posting rows, stable line IDs, visible totals/difference and
  explicit add/remove controls. Creates retain identities/drafts on failure,
  never retry automatically and reset only after confirmed success.
- The combined ledger offers inclusive From/To, Type, Accounts (including labeled
  Income/Expense category targets), Tags, complete-entry sorting and text
  search, defaults to all dates/newest first and preserves journal grouping.
  Amounts, dates and receipt contents are outside text search. Journal posting
  rows show Debit/Credit with no independent mutation action. Derived transactions
  retain their source owner. Other scoped routes retain availability states;
  Mileage retains the #280 existing-record editor. No internal-edition workflow
  is removed or replaced.
- Shared loading, empty, validation, conflict, unexpected-error and success
  states use text plus semantic status/alert roles. Conflicts preserve drafts
  and offer an explicit review action. Forms retain loaded server metadata
  independently from editable values and request confirmation before dirty
  navigation or document unload.
- Protected mutations submit the baseline captured at load. Conflicts retain the
  draft and original token. Review latest record offers Keep draft or Discard
  draft and reload; only the latter replaces fields and metadata together.
  Fixed account types select their required classification; Other permits a classification choice. Payee/tag active-to-inactive saves require confirmation and preserve the original loaded baseline. Active accounts deactivate only through the confirmed Deactivate action; inactive accounts may reactivate through Active and Save changes. Parent choices contain compatible roots, and parents with children remain roots and retain their classification/kind until the children are moved. Transfer destinations exclude the selected source account; changing the source clears an identical destination. Changing transaction kind clears an incompatible category, and existing/new payee inputs are mutually exclusive. Bookkeeping selectors retain only each loaded field/posting's historical inactive references alongside active choices.
  Deletion/deactivation requires acknowledgement; merges retain target/source
  tokens. Merge source choices exclude the selected target, and changing the target clears it from selected sources. Successful saves advance the baseline from the confirmed response.
  No mutation retries automatically. Journal target selectors show Choose target
  for new postings and clear the selection when Account/Category changes.
- Context changes remount private queries and drafts; no prior business/session
  cache is reused. Forms stack; tables may scroll within their own region.
  Keyboard focus, labels and business scope remain reachable at 320 CSS pixels.
- #287 uses one native modal confirmation component for discard, navigation,
  business switching, record reload and destructive confirmations. The keep
  action receives initial focus, Tab/Shift+Tab wrap within the prompt, Escape
  keeps the draft, and dismissal restores the initiating control when it remains
  mounted. Pending operations cannot be dismissed or submitted again. A rejected
  destructive confirmation or failed reload closes so the shared error/review action is reachable.
  A successful route change closes mobile navigation and focuses main content;
  blocked navigation keeps its initiating link available. Declared top-level
  validation errors are associated with their labeled fields and generic messages.

**Current behavior — shared commercial visual foundation (#325):** The React
stylesheet owns the shared type roles and spacing grid above, with the approved
commercial palette below. Primary surfaces use 16px padding. Native single-line
controls have a 40px minimum on desktop with a fine pointer and 44px on touch or
narrow layouts;
multiple selects remain multiline listboxes (128px minimum), and textareas are
vertically resizable (112px minimum). Disabled controls retain legible neutral
text. Keyboard focus combines a contrasting primary outline with the focus halo.
Create forms share primary submit/secondary back actions and section headers;
confirmation dialogs share action tones, with permanent deletion explicitly red.
Accounts demonstrates the shared page header, primary Add link, neutral Edit
action and keyboard-scrollable table region. Long account/parent names wrap;
Edit's accessible name identifies the full account. Table body cells, including
row headers, use ordinary weight; column headings retain emphasis. Financial
values use tabular numerals, and Accounts aligns the opening-balance heading
with its values. Shared metrics use 28px values and ordinary labels. These are
foundations for later page slices, not completion of the full design epic.
The compact [requirement/implementation audit](docs/COMMERCIAL_UI_FOUNDATIONS.md)
records commercial/Streamlit conflicts, reuse owners, hooks and visual evidence.

**Current behavior — light Soft workspace (#331, owner-selected direction):**
The commercial app stays light even when the operating system prefers dark.
This explicitly replaces the earlier commercial neutral palette; the internal
Streamlit palette above retains its own owner.

| Commercial token | Value / treatment |
| --- | --- |
| Canvas | `#EEF2F7` |
| Primary / secondary surfaces | `#F8FAFD` / `#EAF0F8` |
| Native control fill | `#EDF2F9` |
| Hover / selected | `#E5EDF8` / `#E3ECFD` |
| Primary / secondary text | `#223149` / `#52627A` |
| Default / subtle / emphasized borders | `#CFDAE9` / `#DCE5F0` / `#7B8DA7` |
| Primary action / hover / focus halo | `#2E60CC` / `#2858BC` / `#6B96ED`; filled actions use white text |
| Neutral pending/disabled | `#52627A` on `#E8EDF4` |
| Controls / surfaces | 8px / 12px radii; surface shadow `0 4px 16px rgb(34 49 73 / 4%)` |

Forms and editor/filter surfaces stop growing at 960px; tables keep the available
page width and intentional local scrolling. Labels and primary record names/amounts
use weight 500, ordinary supporting table cells 400 and page headings 600.
Compact desktop fields retain readable padding;
touch targets, native multiline selectors and error/focus associations remain.
Tables share a rounded, subtly bordered region, a tinted header and restrained
row dividers/hover; financial columns stay right-aligned and tabular. Records use
primary-name and quieter supporting-detail hierarchy, compact text status/type
badges and lightweight inline row actions. At desktop widths of at least 1000px,
action columns stay visible while the financial columns scroll. Narrow layouts
retain local scrolling and 44px action targets. Writer detail links say Manage
for Assets, Recurring and Mixed-use; read-only detail links say View. The route,
loaded baseline, confirmations and available commands remain capability-owned.
The ledger displays transaction type and source as separate pills (for example,
Expense and Mixed-use), with the existing combined accessible row name. Mileage
keeps 16px between Download filtered mileage CSV and the log table. Semantic
success/error/warning colors and all bookkeeping/state owners remain unchanged.
The [integrated acceptance record](docs/COMMERCIAL_UI_ACCEPTANCE.md) tracks the
selected direction, exact-candidate evidence and separate manual/release gates.

**Current behavior — commercial core presentation (#326–#328, EPIC #323 / initiative #124):**
The shell marks the current main destination with weight and a leading rule as
well as color. Transactions remains the current main workflow for Journals,
Mixed-use expenses and Recurring expenses. Categories & contacts groups
Categories, Payees and Tags, including their create and merge routes. Moving
between those reference routes keeps Categories & contacts current in the main
menu. Each group has its own wrapping, labeled navigation list with a visible
current link. Mileage shares View mileage log / Add trip navigation;
Add trip remains capability-gated. These are real guarded route links, not ARIA
tabs. A cancelled dirty navigation retains the draft, menu and initiating focus;
a completed navigation closes the menu and focuses main content.

Page headers group related actions. Dashboard's primary View ledger and neutral
Set up accounts are styled links; Transactions uses primary Add transaction and
neutral Add journal. Journals, Payees/Tags, Mixed-use and Recurring lists reuse
the shared header with their existing capability-gated Add action. Informational
inline links retain their underlining.

Dashboard/Reports share labeled period controls and Clear dates, separated
Profit and loss / Balance sheet / all-date balances sections, responsive metric
groups, ordinary row weight and aligned numeric headings/cells. From/To are
inclusive; To is the balance-sheet as-of boundary. The all-date section is
explicitly independent of those controls. Decimal strings retain server signs
and precision. Negative net/current earnings retain a minus sign and use red;
missing values show an em dash/unavailable status, never an invented zero.
Empty statement groups and account balances explain their absence; loading and
failed reads do not fabricate summary values. The accounting-equation message
shows balanced, difference (including the reported value), or unavailable text.
No report, chart or client accounting calculation is added; the Streamlit page
contracts below do not expand the commercial summary endpoint's scope.

The combined ledger uses a labeled filter surface: From/To/Type, then Accounts
and Tags, search with conditional Clear search, complete-entry sort/order and
Clear filters. Desktop related controls align; narrow controls stack. Native
multiline listboxes have equal deliberate height, selection instructions and
full selected-label summaries (native option wrapping varies by browser).
Clear filters restores all dates/types/targets/tags, empty search and Date /
Descending ordering. The keyboard-focusable Ledger region contains horizontal
overflow; accounting columns and stable IDs remain available. Names, tags and
memos wrap; ordinary rows stay normal weight. Each journal has one parent/group
with subordinate Debit/Credit postings and no posting mutation actions.
Ordinary Edit/Receipts controls use short visible labels and complete record
labels for assistive technology; source-owned rows retain their owner links.
[UI foundations](docs/COMMERCIAL_UI_FOUNDATIONS.md) records the reuse map and
synthetic before/after evidence. #331 integrated acceptance, #222 identity/onboarding
and #288 hosted/device gates remain separate.

**Current behavior — commercial forms and secondary presentation (#329/#330):**
Create and protected-edit routes share labeled field groups, two related desktop
columns that stack at 760px, multiline memo/notes controls, decimal keyboard
hints and native listboxes with selection guidance and full selected labels.
Save is primary, Back and explicit commands are neutral, and permanent deletion
is red. Existing confirmation, dirty-navigation, historical inactive choices,
loaded baselines and explicit stale-conflict review retain their owners.
Journals group each stable posting's target, side/amount and optional details;
Add/Remove remain explicit, and debit/credit/difference feedback stays visible
without duplicating balancing or payload logic. Reference lists wrap long names
and retain stable per-record Edit actions; merge choices and confirmations keep
their original semantics.

Assets, Mixed-use and Recurring reuse these fields, detail groups, action and
table patterns. Source ownership, service-calculated allocation, posted-history
locks and future-only schedule edits are explained alongside the applicable
controls. Depreciation and occurrence history remain locally scrollable tables;
generation, posting and retirement retain explicit protected confirmations.
Mileage uses the same create/edit fields, a named scrollable log, wrapped text
and aligned distance columns; manual entry, round trips and scoped CSV remain.
Shared fields keep their labels and controls at the top of a grid row, so the
compact date filters do not stretch beside the multiline tags list. Reference
management pages show their title once; tables retain accessible names without
repeated visible section headings or captions.
Receipts group linked files, attachment and unreferenced recovery separately,
with full filenames, keyboard-accessible metadata, upload/link status and clear
unlink-retains-file guidance. Read-only users retain inspection/downloads;
unconfigured storage offers availability/reload without attachment controls.
Data & backup provides the three import workflows described below for authorized
users. Browser backup remains outside this slice; absent workflows are not shown
as disabled controls or promised as a release.
The integrated named-user signed-out, session-unavailable and setup-required
surfaces also share headers, surfaces and Sign in/Sign out actions, while their
identity, private-view unmount and receipt-abort behavior retains the #312 owner.
The [route inventory and evidence](docs/COMMERCIAL_UI_FOUNDATIONS.md#wave-2-forms-and-secondary-routes-329330)
records all current commercial routes and accepted exclusions. #314/#317 own
future identity/onboarding integration, #331 integrated visual acceptance and
#288 hosted/provider/device acceptance.

[Foundation conventions](docs/COMMERCIAL_FOUNDATION.md) owns technical contracts.
[Commercial concurrency](docs/COMMERCIAL_CONCURRENCY.md) owns the #280 contract.
**Current behavior** added by #283/#286: Mileage has a complete manual log,
inclusive date/any-tag filtering, scoped totals/CSV, one-way/round-trip creation
and fresh detail routes reusing the protected editor. Ordinary saved transactions
link to receipt management with portable metadata inspection, same-origin
downloads, multi-file attachment, upload/link progress and unresolved-file retry.
Confirmed uploads survive link failures. Retry and cancellation notices distinguish
confirmed uploads from unconfirmed selections and directs users to inspect
unreferenced receipts before selecting unconfirmed files again.
Confirmed unlink removes only the reference; unreferenced files can be relinked.
Read-only users can inspect/download;
unconfigured document storage shows availability text without upload controls.
Source-owned receipt workflows stay with their owners. Maps/routing remains with
#363. The existing QuickBooks mileage import is available in Data & backup under
#364. [Commercial mileage and receipts](docs/COMMERCIAL_MILEAGE_RECEIPTS.md)
owns this slice's transport, recovery and validation contract.
[Commercial core workflows](docs/COMMERCIAL_WORKFLOWS.md) owns #281/#282 scope.
#222 adds authenticated identity/membership context selection,
[Secondary workflows](docs/COMMERCIAL_SECONDARY_WORKFLOWS.md) delivers #284/#285.
[Browser quality](docs/COMMERCIAL_BROWSER_QUALITY.md)
documents #287's completed automated baseline. [Technical alpha](docs/TECHNICAL_ALPHA.md)
defines the release/routing matrix and outstanding hosted receipt configuration,
staging, rollback and manual-device gates; no internal workflow is retired.
The default hosted synthetic runtime can bind the existing receipt UI through
the explicit server-only [Drive file configuration](docs/ALPHA_DOCUMENT_STORAGE.md).
Absent configuration retains the availability screen; invalid supplied bindings
stop startup. No credential controls or Google authorization routes are added to
the commercial browser.
The Streamlit-specific shell requirements above continue to govern the internal
edition.

## Page headers, workflow groups, and messages

**Current behavior — existing workflow ports (#357/#358/#362/#364):** Data &
backup contains separate Tabula Rasa CSV, QuickBooks transaction and QuickBooks
mileage uploaders, scoped to the selected business. Uploaders require read, write
and import access (Owner, Admin or Accountant); Editor access alone is insufficient.
File preparation/preview is
read-only; explicit commands submit the selected source again for fresh validation.
Tabula Rasa CSV preserves its first-20-source-row presentation and Income/Expense
contract. QuickBooks transactions preserve CSV/General Ledger XLSX/ZIP conversion,
counts, row diagnostics, optional reference proposals and Transfer support.
QuickBooks mileage preserves Business/duplicate/Personal/Unreviewed diagnostics,
one-decimal distance and a confirmed import. Failed/uncertain commands retain the
file/draft and direct users to inspect the ledger/log before retrying. No automatic
retry or partial-batch success is shown. The shared page owns one dirty-navigation
guard across its three independent uploader states.

The commercial ledger offers explicit visible-entry selection with loaded stable
IDs/baselines, ordinary Copy transaction and confirmed Category/Payee/Tag changes
or eligible permanent deletion. Copy starts with a new identity, active Tags,
exactly one source memo suffix and no receipts or recurring ownership. Journal
selections and mixed-use/depreciation projections disable generic mutations;
selected CSV export remains #359. Filter/search/sort changes clear selection.
Bulk mutation validates the entire selection before an atomic PostgreSQL write;
untouched fields remain unchanged. Entering Bulk mode loads baselines and refreshes
the displayed ledger before enabling selection; a failed refresh prevents entry.
After a submitted failure, the preserved bulk draft remains visible with actions
disabled until the user leaves Bulk mode and loads a fresh selection.

Complete mixed-use sources offer independent Copy mixed-use expense with new
source/projection identities and no copied receipts/recurrence. An eligible ordinary
Expense offers Make recurring, loading a fresh baseline and the existing schedule
fields; confirmation creates a schedule around the existing initial Expense rather
than duplicating it. Prefilled copies require confirmed cancellation even without
edits. Confirmed copy/conversion completion closes that mutation surface.
[Commercial import, copy and bulk workflows](docs/COMMERCIAL_WORKFLOW_PORTS.md)
owns formats, failure behavior, transport, validation and #288/#303 boundaries.

**Current behavior — commercial secondary workflows (#284/#285):** Transactions
links to Mixed-use expenses and Recurring expenses. Mixed-use source creation,
editing and confirmed deletion preserve the stable source/projection pair; a
service-calculated Ledger result previews allocation. Incomplete relationships
remain inspection-only. Recurring lists show cadence, next/latest occurrence,
status, attention and ID; details show durable occurrence provenance. Ordinary
and mixed-use creation commit the schedule and initial occurrence together.
Protected Pause/Resume/End actions require confirmation; End retains history.
Generate due occurrences is an explicit confirmed command. Commercial page
loads never reconcile recurring schedules; the internal edition's on-load
behavior below remains specific to Streamlit.

Assets provides a register, create/detail/edit, retirement and guarded deletion.
Server-calculated quarterly schedules show override reasons, Posted/Pending and
ledger IDs. Protected override/removal and Post due depreciation require
confirmation. Terms/history locks and deletion availability come from the
service, including immutable posted provenance. Responsive tables scroll inside
labeled regions and forms retain the existing dirty-navigation/conflict contract.
Completed explicit commands require returning to the list for a fresh editor.
Detail visits wait for a fresh read before opening an editor; later background
read failures preserve its loaded draft and baseline. Read-only views expose
saved terms without mutation controls.
[Commercial secondary workflows](docs/COMMERCIAL_SECONDARY_WORKFLOWS.md) owns
scope, recovery and release boundaries.

Page headers state the page purpose and place its primary workflow actions
near the relevant content. Use tabs for current workflow divisions:

- Transactions: Add transaction and View & edit ledger
- Transactions: Payees & Tags management
- Mileage: Add trip and View & edit mileage log

Assets is a separate top-level master-record workflow. It is not a
Transactions tab and does not expose a mixed-use placeholder before that
workflow is implemented.

Use bordered containers or expanders for dense independent workflows such as
edit forms, imports, profile administration, and backup controls. Do not move
long previews or multi-part recovery workflows into cramped dialogs.

Messages identify what happened, whether data changed, and what to do next.
Use informational blue, warning amber, error red, and confirmed-success green
with meaningful text. Do not show a success message before the relevant
Google API or storage operation confirms the write. Ordinary errors must not
expose secrets, tokens, private keys, private ledger data, receipt contents,
or raw stack traces.

## Tables and generic filters

Tables use compact rows, clear headers, subtle separators, restrained hover,
clear selection, and sticky headers where feasible. Dates and descriptions are
left-aligned; amounts, balances, and counts are right-aligned. Preserve stable
record-ID mapping and keep a reliable explicit selector for edit workflows.
Do not hide important accounting fields solely to avoid narrow-screen
scrolling.

For a management table whose visible rows can be changed, select one row with
the table's native row-selection affordance, then use Edit, Rename, or Remove.
The selected row's stable record ID, never its displayed position, identifies
the mutation target. Clear or repair selection when the profile, visible rows,
or underlying records change. Avoid a second dropdown that only reselects an
already-visible target; related-value selectors such as merge targets and
sources may remain separate.

Generic filters use explicit labels, AND semantics, visible scope, and a
clear path back to the unfiltered state. Changing result scope clears
incompatible row selections. Exact control order and field meaning belong in
the relevant page contract below.

## Forms, buttons, and destructive actions

Use one column for sequential decisions and two columns only for clearly
related desktop fields. Keep labels visible, helper text concise, tab order
logical, and validation near the workflow. Stack related columns on narrow
screens.

Blue is the normal primary action. Neutral styling is for alternatives and
read-only checks. Red is for permanent deletion or an equally destructive
operation. Amber may call attention to a review or retry action. Disabled
actions remain legible and explain why they are unavailable.

Permanent deletion confirmations name the record, state that deletion is
permanent and cannot be undone, and require explicit acknowledgement. Receipt
reference removal must state that the ledger reference changes while the Drive
file remains.

## Receipts as a cross-cutting interaction

Receipts are managed within the selected saved transaction's workflow. When
Drive is unavailable, show a clear setup message and do not display
nonfunctional upload controls.

Supported files are PDF, PNG, JPG, JPEG, WEBP, and HEIC. Every selected file
is validated before upload; each is non-empty and no larger than 20 MB, and a
batch is no larger than 200 MB. Preserve a recognizable sanitized filename,
suffix conflicts numerically, and store stable identity, size, and SHA-256
metadata.

Show linked files with an open-in-Drive link, Remove receipt action, and the
consequence that only the ledger reference is removed. The unreferenced
workflow can link an eligible app-managed file without renaming it. Integrity
metadata warnings remain visible.

Receipt-on-create is an ordered workflow: validate fields and files, save the
transaction, upload files, and link each result independently. A confirmed
transaction is never reported as unsaved because receipt work failed. Partial
work keeps successful links, reports complete and unresolved counts, and
offers retry only for unresolved work. Each Drive upload uses a prepared
receipt ID and content hash: after an uncertain response, read Drive once by
that identity, then retry the upload once only when the file is clearly absent.
Sheets linking uses the shared bounded write policy: one fresh readback can
confirm an uncertain link, while an unconfirmed uploaded file remains available
through Unreferenced receipt. The editor retains multi-file upload, retry,
cancel recovery, unlink, and unreferenced-link behavior.

Add and Edit share receipt recovery keyed by profile and transaction ID. New
transactions receive their UUID before persistence, without a placeholder row.
Pending receipt state is scoped to the selected profile and exact workbook and
receipt folder. A configuration change clears that pending state instead of
reattaching it elsewhere; uploaded files remain recoverable in Drive.

The interface reports the concise outcome and next action; it does not expose
an internal pending/uploaded/linked/failed state machine as a separate product
surface.

## Imports as a cross-cutting interaction

The Data & backup page keeps Tabula Rasa CSV, QuickBooks transactions, and
QuickBooks mileage as separate uploaders. Parsing, preview, diagnostics,
duplicate detection, and proposed account/category creation are read-only.
Explicit import actions perform the confirmed batch write.

Preview states must clearly distinguish ready, duplicate, skipped, conversion,
validation, and storage failures. Imports use the selected profile and validate
references again before writing. No partial import is claimed after a failure.

### Import page contract

The Tabula Rasa CSV workflow requires Date, Type, Amount, Account, and
Category, accepts Payee, Description, and Reference, previews up to 20 rows,
and imports Income or Expense rows only. It does not import transfers.

QuickBooks transaction sources are Transaction Detail by Account CSV and
Self-Employed General ledger XLSX or its supported ZIP. Its preview retains
ready, duplicate, Income, Expense, Transfer, conversion-error, and
validation-error counts; duplicate and error row numbers; up to 50 source
rows; optional account/category auto-create proposals; and an explicit Import
validated rows action. Duplicates are skipped and valid rows are written in
one confirmed batch after references are checked again.

QuickBooks mileage retains ready, duplicate, Personal, Unreviewed, and
validation-error counts; row numbers and details; up to 50 source rows; and an
explicit Import validated mileage action. Only valid unique Business rows are
written. The three uploaders have separate staged state and never write during
preview.

## Responsive behavior

The application is desktop-first but remains usable at narrower widths. At
approximately 760px and below:

- multi-column forms stack;
- metric cards wrap;
- dashboard sections stack by priority;
- sidebar navigation may collapse;
- tables may scroll horizontally; and
- secondary actions may move below the primary action.

The priority order is page title and primary action, primary financial summary,
attention items, supporting metrics, main table or chart, and secondary
details. There must be no control overlap or unintended page-level horizontal
overflow. Intentional table scrolling is acceptable. Do not silently omit
important accounting columns.

## Accessibility

All pages require keyboard navigation, visible focus, explicit labels,
sufficient contrast, non-color state indicators, descriptive button text,
predictable control order, and accessible error messages. Do not remove focus
outlines without an equivalent replacement. Icons are never the only
representation of delete, edit, warning, success, financial direction,
active/inactive, or balanced/out-of-balance state. Avoid nonessential motion.

## Streamlit constraints

Prefer the following mappings:

| Need | Preferred control |
| --- | --- |
| Text | st.text_input or st.text_area |
| Amount, miles | st.number_input |
| Date | st.date_input |
| Single choice | st.selectbox |
| Account filter | st.multiselect |
| Transaction type | st.segmented_control |
| Boolean or acknowledgement | st.checkbox or st.toggle |
| Upload | st.file_uploader |
| Submission | st.form and st.form_submit_button |
| Read-only selectable table | st.dataframe with selection |
| Edit/Bulk mode | segmented control or toggle with explicit labels |
| Export | st.download_button |
| Status | st.success, st.warning, st.error, or st.info |
| Metric | st.metric |
| Chart | st.plotly_chart |

Avoid replacing native controls solely for styling. Large prepared exports
should not be regenerated on every rerun. Show their preparation timestamp,
change Prepare to Refresh when a set exists, and invalidate a set after a
confirmed workbook write.

## Page contracts

The page contracts below are the canonical location for exact control order,
fields, table schemas, and current UI acceptance criteria. Generic sections
above define reusable rules and do not repeat these details.

### Authentication and global shell

#### Required behavior

- Require application-password authentication before ledger access.
- Display the business selector when profiles exist.
- Display the selected workbook title on normal pages.
- Scope all operations to the selected profile.
- Preserve Log out on every normal page.
- Expose Account settings only under current local-administration safety
  conditions.
- Keep Terms of Use and Privacy Policy available before and after
  authentication without exposing application data.

#### Acceptance criteria

No ledger page is visible before authentication. The active business and
workbook are discoverable. Authenticated users are not told that the password
restricts them to one profile.

### Dashboard

#### Purpose and content

Show Total balance, Income this month, Expenses this month, Net this month,
recent activity, and account balances using the latest confirmed Sheets state.
Recent activity retains Date, Type, Payee, Category, Account, and Amount and
the current recent-activity limit. Account balances retain Account,
Classification, Type, and Balance. By default, account balances are grouped in
Asset, Liability, then Equity order and sorted by account name within each
classification.

#### Acceptance criteria

All four metrics and both tables remain present. Empty ledgers direct the user
to Transactions. Expense signs preserve current display semantics. Account
balances sit beside recent activity on wide screens and stack by priority on
narrow screens. At constrained desktop widths with the expanded sidebar, the
cards stack to preserve readable tables. On wide screens, both tables fit their
cards without requiring horizontal scrolling at the standard application
content width.

### Transactions

#### Purpose

Create income, expense, and transfer entries; optionally attach receipts;
filter, search, and review the ledger; edit or permanently delete saved
entries; perform approved bulk actions; and manage receipt references.

#### Phase A mixed-use storage contract

The storage/domain layer also defines a dedicated `MixedUseExpenses` source
collection for cost-based mixed-use expenses. A source is the authoritative
editable record and contains the normal Expense inputs, total expense,
business-use percentage, currency-rounded allocated amount, Allocation
Rationale, its stable source ID, and its stable linked transaction ID. The
linked row in `Transactions` remains an ordinary Expense projection containing
only the allocated business amount and generic `source_type`/`source_id`
provenance. Source-aware create, edit, and delete operations preserve this
relationship, use fresh reads, and confirm uncertain multi-record writes with
one readback and at most one retry when the pair is clearly unchanged;
they do not expose a mixed-use page or workflow in Phase A. Current-format
backups include the source collection and reject orphaned or inconsistent
relationships. Only the frozen format-13 archive is supported; earlier
formats are rejected before restore writes.

The Transactions page also provides a **Mixed-use expenses** tab. Its
profile-scoped source editor exposes normal Expense fields plus Total Expense,
Business Use %, and required Allocation Rationale. A live, side-effect-free
Ledger Result preview uses the canonical Decimal allocation calculation; Save
is the only persistence action and there is no Draft mode. Complete sources
can be edited or permanently deleted only from this tab, preserving stable IDs
and updating/removing the existing projection. A source without its linked
projection is inspection-only; Save and permanent deletion are unavailable
until the source and ledger relationship has been reviewed.

The linked projection remains visible in the ordinary ledger at the allocated
amount and is marked **Mixed-use**. It is read-only there; edit, delete, copy,
bulk mutation, and receipt actions are managed from the Mixed-use expenses tab.
Receipt operations use the same profile receipt folder and Drive recovery
workflow as ordinary transactions. The Mixed-use Expense Log also provides
**Copy mixed-use expense** for one selected complete source. Copy initiation
re-reads and validates the source/projection pair, then opens a distinct
new-source editor from an independent snapshot with pre-generated source and
projection IDs. The copy preserves the date, normal Expense fields, allocation
inputs, and active managed associations; its memo ends with exactly one
`Copy From <mixed-use source ID>` suffix. Allocation is normalized again when
the copy is saved. Copy mode has no receipt uploader or receipt references,
and Cancel creates nothing. The authoritative source and its projection are
never mutated; incomplete sources remain inspection-only and cannot be copied.

The Mixed-use expenses tab shows a single-row-selectable **Mixed-use Expense
Log** before its editor. The table's displayed row position is translated to
the selected source's stable ID; no displayed value is used as an edit or
delete key. The selected source ID and its table scope are profile-local and
include the visible source IDs and workbook data revision. A changed or
invalid scope clears the selection and edit baseline, and a new table
generation prevents an old table selection from being replayed. The tab opens
in clearly labeled **Add mixed-use expense** mode. Selecting a row changes to
**Edit mixed-use expense**; **Copy mixed-use expense** opens an independent
new-source editor; **Add new mixed-use expense** clears the selection and
returns to Add mode. If a source exists without its linked ledger
projection, it is shown for inspection only: Save and permanent deletion are
unavailable until the source and ledger relationship has been reviewed.
The log columns, in exact order, are Date, Payee, Account, Category, Total,
Business %, Allocated, Rationale, Description, and Receipt. Receipt shows the
paperclip indicator when one or more receipts are linked.

#### Add transaction contract

The Add transaction tab is a **New entry** surface with a top-level **Entry
Type** segmented selector: **Simple Transaction** (default) and **Multi-line
Journal**. Date and Description / memo are shared above the selected editor.
Creation uses ordinary keyed widgets so unsaved changes are available to the
mode-switch guard. Switching a meaningful draft requires **Discard and switch**
or **Keep editing**; shared Date and memo survive either choice. Receipt recovery
replaces the creation surface until resolved. Pending recurring saves also
prevent a mode switch. Saved records have a fixed editor type, with no conversion
selector.

The Simple Transaction editor preserves the existing fields:

1. Transaction type: Income, Expense, or Transfer
2. Shared Date above the editor
3. Category and Amount for Income or Expense
4. Amount for Transfer
5. Account: **To Account** for Income, **From Account** for Expense or
   Transfer
6. **To account** for Transfer
7. Payee / customer selector and Reference. The selector lists active managed
   Payees and accepts a new name typed and confirmed with Enter; typed existing
   names select the stored Payee case-insensitively. New values are stored in
   the managed Payees table before they are referenced by a transaction.
8. Tags (optional). The multi-select lists profile-local stored Tags, lets each
   selection be removed independently. Typing a new name and pressing Enter in
   the selector creates and selects the inline Tag. Only one new Tag name may
   be entered per record; typed existing names select the stored Tag
   case-insensitively.
9. Shared Description / memo above the editor
10. Receipt (optional)
11. Save transaction

Only active accounts are offered for new entries. Income and Expense require a
same-kind category; Transfer has no category and requires two different
active accounts. If no active account or matching category exists, show a
clear warning and do not present a misleading save path.

The receipt control accepts the supported multi-file batch. All transaction
and file validation completes before the Sheets write. On no-receipt save,
confirm the write and intentionally reset the form on the next rerun. On
receipt save, follow the ordered receipt sequence in the generic receipt
contract.

#### Multi-line Journal contract

The advanced editor starts with two blank posting rows. Each row contains a
managed **Account** selector, **Debit**, **Credit**, **Description**, and a managed
**Payee / customer** selector. The Account selector combines balance-sheet
accounts and Income/Expense categories with explicit labels; stable typed
references preserve the distinction. **+ Add line** appends a row, and **Remove**
removes a draft line while retaining at least two usable editor rows. The compact
row grid stacks on narrow screens. Line IDs remain stable when other rows change.

Every populated line requires a valid target and exactly one positive,
cent-normalized Debit or Credit. Completely blank rows are omitted; incomplete
populated rows block save. **Total Debits**, **Total Credits**, and **Difference**
remain visible. Save is disabled until at least two valid postings balance
exactly. The journal application service validates input, and its adapter repeats shared
domain validation against fresh references before saving the parent and all
postings in one native Sheets batch. A successful API response is authoritative; an uncertain
response receives one readback, then either confirmed success or inspection
guidance. Draft identities remain available for a retry.

Transaction and journal mutations use the selected profile's application services.
The single transaction editor supplies its visible record as the expected
snapshot; a changed record must be refreshed before editing or deleting.

Journal edit uses the full posting grid and a complete expected-entry snapshot;
stale edits cannot overwrite a changed entry. Permanent deletion requires the
normal acknowledgement and removes the parent and all postings together.
Journals have no receipt, Tag, recurrence, copy, or import workflow in this
release. Existing simple workflows retain those supported features.

#### Ledger controls and table

Controls appear in this exact order:

1. From
2. To
3. Type
4. Accounts
5. Tags
6. Search transactions
7. conditional Clear search
8. Edit/Bulk mode
9. Sort entries by and Entry order when the workbook contains journals

The table columns, in exact order, are Date, Type, Account, To account,
Category, Payee, Amount, Tags, Description, Receipt, Reference, and ID. To
account is blank for non-transfers, Category is blank for transfers, Tags is
blank when none are assigned, Receipt indicates one or more linked receipts,
and ID remains accessible for disambiguation. When journals are visible, Debit
and Credit columns follow Amount. Ordinary entries and journal parents leave
these columns blank. The Tags filter matches a record
when it contains any selected Tag.

The ledger defaults to latest-date-first and Edit mode. The table does not
begin with a visibly preselected row. When the edit section opens, its
selector targets the first visible transaction. A selected visible row or the
selector changes the edit target. If the current target is filtered out, it
moves to the first visible row or clears when none remain.

Search is a trimmed, case-insensitive substring match applied after the
structured filters. It searches Type, Account, To account, Category, Payee,
Tags, Description, Reference, and ID. It does not search dates, amounts, receipt
contents, receipt filenames, or hidden Drive metadata. Show result count,
conditional clear, and a distinct no-results state. Whitespace-only text is
equivalent to cleared search.

Filters and search persist across Add transaction / View & edit ledger and
across Edit/Bulk changes. Changing a filter or search clears bulk selection.
Changing mode also clears incompatible selection and recreates the dataframe,
so the native client-side sort resets to latest-date-first. The design does
not promise to preserve client-side sort across that recreation. Interactive
sorting may persist while the same widget remains mounted, including across
the two Transactions tabs. Navigation away and back resets the table
generation and latest-date-first ordering for a simple-only workbook. When a
workbook contains journals, app-level sort controls order complete logical
entries; column selection disables native dataframe sorting in Edit, Bulk, and
copy-locked views. Header clicks select a column and never split a journal group.

Each journal renders one parent summary (date, Journal indicator, stable ID,
memo, Multiple accounts / N postings, amount = total debits), immediately followed
by all posting rows. Children use a subordinate arrow, blank repeated parent
fields, target path, one Debit/Credit amount, payee, and description. Summary
amounts are not repeated on children. Filtering/searching any posting retains
the parent and every sibling. The Type filter includes Journal; Accounts also
offers labeled Income/Expense categories. Untagged journals do not match an active
Tag filter. Counts operate on logical entries, never display rows.

Selecting any journal row targets its parent editor. Multiple selected rows of
one journal count once. Filter, ordering, mode, profile, and data-revision changes
invalidate incompatible selection. No posting is independently editable or
permanently deletable. No pagination is currently used.

In Edit or Bulk mode, **Copy transaction** is enabled only when exactly one
visible transaction is selected. It opens the existing editor as a clearly
labeled new-transaction copy workflow. The copy preserves the source date,
active Tag associations, and other eligible fields, retains the user memo, and appends exactly one `Copy From
<source ID>` suffix, removing stale generated copy notes when recopying. It
starts with no receipt references. Save creates a new transaction; Cancel
discards the copy state without changing the source row.

#### Bulk behavior

Bulk mode is explicit and selects only visible rows. It shows the selection
count and only these actions:

- **Copy transaction:** available for exactly one selected row and opens the
  new-transaction copy editor.
- **Export selected:** downloads selected visible ledger columns without a
  workbook change.
- **Apply changes:** edits Category, Payee, and Tags through an explicit
  partial-change editor. Category is available only for a homogeneous Income
  or Expense selection and is restricted to categories of that kind. Payee
  uses existing profile-local Payee records, and Tags use complete-set
  replacement.
- **Permanently delete selected:** shows count and aggregate absolute amount,
  requires acknowledgement, removes selected ledger rows, and retains linked
  Drive files as unreferenced files.

When any selected logical record is a journal, **Export selected** includes its
complete parent/posting group. Copy, bulk changes, and bulk permanent deletion
are unavailable for that selection; an explanation directs the user to Edit for
whole-journal edit/delete. The app never silently mutates only the simple subset.

Bulk actions revalidate all selected stable IDs immediately before one batch
write and never silently partially apply. Transfers and mixed Income/Expense
selections cannot use Category changes. Category, Payee, and Tags controls show
their shared current value or **Mixed / Multiple values**. A field is included
in the mutation only after the user changes it or explicitly selects **Apply
<field> to all selected**; untouched fields remain unchanged. Tags use
complete-set replacement, so clearing all Tags requires that explicit action.
Bulk changes are not available for dates, amounts, descriptions, references,
accounts, transfer structure, or receipts.

Bulk edits and deletions use one Google Sheets
[spreadsheets.batchUpdate](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate)
request per mutation. The complete request is validated before application.
An uncertain response is followed by a fresh stable-ID read and classified;
the application never blindly retries an ambiguous mutation.

#### Edit, delete, and receipt acceptance

Preserve type-specific editing of source and destination accounts, category,
date, amount, payee, Tags, reference, and description. Tags use stable IDs;
individual associations can be added or removed without changing the others.
Transfer accounts remain
different, and inactive accounts already referenced by a selected historical
transaction remain available where currently supported. Single deletion has
the same permanent warning and acknowledgement strength as bulk deletion.

The page must retain linked receipt opening, reference removal without file
deletion, multi-file editor upload, unresolved retry, cancel recovery,
and unreferenced receipt linking.

In the edit form, the optional multi-file receipt picker appears immediately
before the Save changes controls. Saving the edit validates and processes any
selected receipts through the same ordered, retry-safe workflow; there is no
separate receipt upload button.

#### Acceptance criteria

Create, edit, single delete, search, bulk actions, table columns, and receipt
operations remain discoverable. Success occurs only after confirmation.
Receipt-on-create partial failure never duplicates or discards a confirmed
transaction. Bulk mode cannot operate on rows outside the current visible
scope. Tags remain independent of Categories and do not affect accounting.

#### Recurring expenses management

Transactions includes a fourth top-level tab named **Recurring expenses**,
before Payees & Tags. It lists each profile-local Expense schedule with its
cadence, next due date, latest current occurrence, status, attention state, and
stable schedule ID. Select one schedule row and choose **Edit** to open its
template editor; the same selection drives Pause, Resume, and End. The schedule
template is flat and validated: amount,
account, Expense category, optional Payee, Tags, description, and reference.
Receipt references are occurrence-specific and are never stored in a template.

Creating an ordinary or mixed-use recurring Expense writes the schedule and
initial occurrence as one logical operation. An existing ordinary or mixed-use
Expense that is not already linked to a schedule can also be made recurring
from its edit surface; the saved edit becomes the schedule's initial occurrence.
When first enabled in any of these creation forms, Repeat every defaults to
one month; a user's chosen cadence is preserved during correction or retry.
Reconciliation runs once per
profile/session, creates due occurrences from stable schedule/date identities,
and is safe to repeat after an uncertain response. A failed schedule is
marked for attention without preventing other schedules from reconciling.
An uncertain link created while converting an existing expense remains out of
reconciliation until its initial occurrence is confirmed; if no linked
occurrence is present after restart, the schedule reports attention so the
user can end it and retry the expense edit.
Generated mixed-use rows always use the source-authoritative source/projection
pair and mirror recurring provenance on both rows.

Pause stops generation without changing the template or existing occurrences;
Resume continues from the latest current linked scheduled date. End prevents
future generation permanently. Editing or deleting an occurrence never edits
or deletes its existing schedule. Schedule edits affect future generated occurrences;
existing occurrences remain ordinary editable/deletable records.

#### Payees & Tags management

Transactions includes a fifth top-level tab named **Payees & Tags**. It has
visually separate **Payees** and **Tags** subtabs and always identifies the
selected business profile. Each section lists all stored values, including
inactive values, and provides add, rename, merge, and remove workflows.
Select one Payee or Tag directly in its table before opening Rename or Remove;
both actions use that same selected stable ID. Merge keeps its separate target
and source controls.

Rename retains the stable ID and every existing reference. A merge requires an
explicit target, one or more explicit sources, and acknowledgement before one
confirmed, atomic workbook mutation. Payee merges update Transactions,
RecurringSchedules, Assets, JournalPostings, and the corresponding MixedUseExpenses
source/projection pair. Tag merges update Transactions, Mileage,
RecurringSchedules, Assets, and MixedUseExpenses, replace source IDs with the
target, and de-duplicate an association when both are present. Unrelated fields
and associations remain unchanged.

Removal is permanent and permitted only when a fresh reference check finds no
uses. A referenced Payee or Tag is not silently unassigned; the page reports
the reference count and directs the user to unassign it through the relevant
transaction, mileage, recurring, or asset editor, or to merge it. Confirmed writes
invalidate only the affected profile-local caches. Uncertain batch responses receive one fresh
readback; only a clearly unchanged operation may be retried once, while a
partial or unreadable state invalidates caches and gives inspection guidance.

### Mileage

#### Purpose and fields

Record and maintain dated business mileage. Add trip preserves Trip date,
Vehicle, Business miles, Starting location, Destination, Round trip, optional
Tags, Business purpose, Notes, and Save mileage trip. Related fields may share
desktop rows: Trip date/Vehicle, Business miles/Return business miles when
Round trip is selected, and Starting location/Destination. Tags appear
immediately below the mileage row.

The log presents From, To, and Tags filters, Trips and Business miles metrics,
filtered CSV download, and the complete table with ID, Date, Miles, From,
Destination, Business purpose, Vehicle, Tags, and Notes. The Tags filter
matches a trip when it contains any selected Tag. It provides single-row
selection and an Edit mileage trip section with all fields, save, and permanent
delete.

Mileage Tags use the same profile-local stored Tag list and type-and-Enter
creation behavior as Transactions. Zero, one, or multiple Tags are valid; each
is independently removable. Only one new Tag name may be entered per record,
and typed existing names select the stored Tag case-insensitively. Round-trip
creation applies the same selected Tags to both independent rows.

When app-wide Google Maps configuration is available, Starting location and
Destination use a narrowly scoped address-lookup component. The Google lookup
fields are optional; the editable recorded-text fields are always visible and
provide the direct manual-entry path. After two Google suggestions are selected, an
explicit Calculate mileage action requests the primary driving route and shows
the editable one-decimal Business miles field; for a round trip it also fills
the editable return-mileage field. The user reviews or edits those provisional
values before saving. The Calculate mileage action appears directly below the
address controls. Changing either endpoint clears the corresponding calculated
state. Until a ready route has been calculated, show a warning that the current
mileage cannot yet be compared with a route; this is advisory and does not block
manual mileage entry. Changing either endpoint clears the corresponding
calculated state, while changing only the Round trip option preserves existing
outbound mileage drafts. Enabling Round trip creates a new return-mileage draft
initialized from the current outbound mileage draft and warns until the return
route is calculated; disabling it removes only the return-mileage input and does
not warn or change outbound mileage. Calculation errors preserve manual entry.
When a Google selection is
used, its final display text pre-fills the editable location text to record;
later user edits remain respected, and the user reviews the text before saving.
The component's Google display text is not written to the ledger until the
user saves the trip.
When Google Maps is not configured, each lookup control is the single manual
recorded-text input; the page does not render a duplicate recorded-text field.
When either current endpoint was selected with Google autocomplete or the
current mileage suggestion was calculated by Google Routes, a Google Maps note
appears directly below the mileage and Tags controls. Stored rows do not claim Google
provenance after reload because that metadata is intentionally not persisted.

Round trip performs separate outbound and reversed return calculations and
shows independently editable mileage values. Saving creates the same two
independent records in one confirmed write, with the reversed return listed
before outbound for newly created pairs when the records share a timestamp.
Existing rows are not rewritten or migrated. Each row receives its own
confirmed mileage and a separate ID; there is no durable pairing. Recalculating
a saved row affects only that row. The filters, metrics, table, and CSV use the
same date scope. Without Maps configuration, the current manual workflow
remains available.

In the edit section, Calculate mileage appears immediately after the address
controls and before the editable trip-details row. Changing an edited address
shows a potential mileage mismatch warning even before recalculation; the user
can recalculate or review and edit the existing mileage manually before saving.
The Google lookup controls start empty for an existing row, while the recorded
text inputs are always visible and initialized from the saved ledger values.
The normal Add and Edit screens do not show a separate Enter address manually
button; a provider-failure recovery control may appear only when Google lookup
itself fails.

#### Acceptance criteria

Round-trip help remains visible. Create, edit, delete, filtering, totals, and
export remain available. Autocomplete remains keyboard and narrow-layout
usable, its prediction list remains legible in the active app theme, manual
entry is always available, and ordinary reruns do not trigger paid route
requests. Mileage remains separate from financial transactions.

### Assets

Assets is the profile-local fixed-asset register for individually tracked
business-use depreciable property. The page contains an Add asset expander, a
compact selectable asset register, an edit/retire/delete surface, and the
selected asset's manually triggered quarterly depreciation schedule. An asset
has a stable ID, required name and enumerated type, optional notes, acquisition
and depreciation-start dates, cost basis, salvage value, useful life in whole
quarters, straight-line method, optional managed Payee and Tags, optional
reference, and an optional acquisition-transaction audit link. The acquisition
link reuses any transaction receipt context; it never copies a Drive file, and
a missing linked transaction does not invalidate or remove the asset.

The fixed asset types are Computers & office equipment; Furniture, fixtures &
appliances; Photography, communication & video equipment; Machinery, equipment
& tools; Vehicles; Construction equipment; Farm equipment;
Residential rental property; Commercial real property; Land improvements;
Leasehold improvements; Software & other intangibles; and Other depreciable
property. Land itself is deliberately absent because it is not depreciable.
The type is classification metadata and does not choose a tax recovery period
or provide tax advice.

The quarterly straight-line source schedule uses `(cost basis - salvage value)
/ useful-life quarters`. The first occurrence is the configured depreciation
start date and each later occurrence is three calendar months later on the same
anchor day. A missing day uses that month's final day without changing the
anchor. There is no automatic partial-quarter proration. Currency calculations
use Decimal-safe cent rounding, and the final quarter absorbs the residual so
the completed schedule ends exactly at salvage value.

Only due or past schedule quarters can receive a durable amount override, and
every override requires a reason. An override fixes that quarter and all
earlier schedule results; the remaining depreciable basis is spread evenly
over later quarters with a final-cent true-up. Asset schedule terms are locked
while overrides exist, though descriptive metadata remains editable. Before posting, removing
all overrides restores editable schedule terms and the ordinary straight-line
calculation. After posting begins, overrides and schedule terms remain locked. Retirement stops occurrences after the retirement date without
calculating disposal proceeds, gain/loss, recapture, or a remaining-basis
write-off. Permanent deletion is allowed only before the asset has saved
depreciation history. Once an override exists, the durable history is retained
and the asset can be retired but not deleted. Posted depreciation carries
the same retention boundary. Retirement cannot precede any posted period.

**Current behavior — Simple Ledger depreciation posting.** Each asset may select
its Depreciation expense account (an Expense category in Simple Ledger) and an
Accumulated depreciation account (type Other, classification Asset). Both are
required before posting; the accumulated depreciation account must be active.
Account selectors remain available for Phase A assets with historical overrides
until the first posting. Posting accounts are locked after posting begins.

The selected asset has an explicit **Post due depreciation** button and a
**Post depreciation through** date, defaulting to today. Posting creates one
Expense row for each pending scheduled quarter on or before that date, including
zero-amount quarters when rounding or an override produces zero. The category
is the expense debit and the account is the accumulated depreciation credit.
P&L includes the expense, the balance sheet reduces asset value and current
earnings equally, and cash/bank balances do not change. This workflow is fully
available in Simple Ledger and has no dependency on #169 or a multi-line journal.
Calculating a schedule or rerunning the application never posts depreciation.

Each generated row stores `source_type=depreciation`, `source_id=<asset ID>`,
and an entry ID deterministically derived from the asset ID and quarter sequence.
This is the durable asset-period linkage; posting and provenance share one row.
The schedule displays Posted/Pending and the linked Ledger entry ID. Fully
depreciated status requires all schedule quarters to be posted, not merely due.
Posted rows cannot be independently edited, copied, deleted, made recurring, or
have receipts managed from the ordinary ledger; selection directs the user to
Assets. Existing acquisition-transaction receipt context remains unchanged.

The existing per-workbook application lock serializes concurrent sessions.
Uncertain writes use the existing bounded stable-ID readback/retry mechanism.
If a later quarter fails, confirmed earlier quarters remain posted; refreshing
and posting again skips them. Conflicting provenance stops posting with guidance
to inspect the source. Backup/restore validates the same source relationships.
No new worksheet or header is needed; the current workbook/backup format retains
the asset fields and transaction source metadata.

### Accounts

#### Purpose and table

Maintain balance-sheet accounts, classifications, opening balances, active
state, hierarchy, and calculated balances. The table retains Account, Layer,
Parent, Classification, Type, Active, Balance, and Transaction count.

The Accounts table and account selectors use the same stable order: Asset,
Liability, then Equity; within each classification, Layer 1 accounts are sorted
by name and each account's Layer 2 children follow their parent sorted by name.

Add and edit fields are Account name, Type (Bank, Cash, Credit card,
Short-term debt, Equity, or Other), balance-sheet Classification, Opening
balance, Parent account, and Active where applicable.

#### Rules

Layer 2 parents share the same classification. Fixed subtypes retain their
normal classification. A Layer 1 account with children cannot be moved under
another parent until its children are promoted or reparented. Parent rows
show rollup balance and count; child rows show direct values. Accounts are
deactivated rather than deleted so history remains valid.

#### Acceptance criteria

Stable IDs and transaction references survive rename, promotion, and
reparenting. Active/inactive state is text-backed. Liability and equity
opening-balance guidance remains visible. No Delete account action is added
without a storage-model change.

### Categories

Maintain Income and Expense categories and their two-layer hierarchy. The table
retains Category, Layer, Parent, Type, and Transaction count. Add/edit fields
are name, type, and optional parent.

A child uses a same-kind parent. A parent with children cannot itself be moved
under another parent until its children are handled. Rename, promotion, and
reparenting preserve the stable category ID. Permanent deletion requires no
transaction references and no child categories, a fresh check, and explicit
acknowledgement. Paths remain available in selectors and reports.

### Reports

#### Content and scopes

Use From and To for income-and-expense analytics and a separate As of date for
the balance sheet. Present, in order:

1. Report period controls;
2. Income, Expenses, and Net;
3. Monthly performance grouped bars;
4. Expenses by category horizontal ranking bars;
5. Category detail with Category, Layer, Parent, Direct activity, and Layer 1
   total;
6. Total assets, liabilities, and equity; and
7. Assets, Liabilities, and Equity tables, with Current earnings in Equity.

Current earnings are income minus expenses and are included in total equity.
Layer 1 totals and direct activity are explainable without double-counting.
Reports show text-backed balanced or out-of-balance status with the difference
for Assets = Liabilities + Equity. They communicate empty activity, empty
expense results, empty statement groups, and storage failures.

#### Acceptance criteria

Charts remain subordinate to reported values and resize within their columns.
No unsupported cash-flow, transaction-detail, or reconciliation report is
presented as current.

### Data & backup

#### Purpose and order

Provide cloud backup controls, recovery-configuration visibility, live exports,
and imports in this order:

1. Cloud backup
2. Recovery status
3. Exports
4. Imports

Cloud backup retains not-configured guidance, profile-scoped destination,
latest backup information, no-backup warning, Upload fresh backup now, and
Verify latest cloud backup. Verification is read-only and never implies
restore or live-workbook mutation.

Recovery status retains optional Synology guidance, invalid metadata warnings,
profile-root source, Receipts and Ledger Backups children, download-only
direction, destination-deletion protection, destination, schedule, retention,
and the explicit statement that the app does not configure or observe DSM.
An absent hosted/local record is reported as unavailable, not as healthy.

Exports retain one Prepare/Refresh workflow, preparation timestamp,
transactions CSV, mileage CSV, and a complete backup when receipt preparation
succeeds. Complete Sheets backups and recovery accept only the frozen
[format-13 source contract](docs/SHEETS_SOURCE_CONTRACT.md). Unsupported archives
fail before writes, preserving the file. CSV downloads remain available when
the complete backup fails.
Prepared data is scoped to profile, configuration revision, workbook identity,
and confirmed workbook data revision.

Imports retain the three distinct workflows and all previews, diagnostics,
duplicate summaries, and explicit actions in the import contract above.

#### Acceptance criteria

Cloud upload, cloud verification, CSV exports, complete backup, all three
imports, and recovery status remain available. No local Drive Desktop
dependency is implied for cloud-native backup.

### Account settings

#### Purpose and availability

Account settings is the local administration home for business profiles,
credentials, Drive storage, recovery metadata, and hosted Secrets handoff. It
requires loopback-only availability and application-password reauthentication.
It is unavailable for writable administration in hosted environments.

Organize the surface as Business profiles, Google setup, Recovery, and
Security & deployment information. The last section is informational except
for Generate hosted Secrets file, which creates a local handoff but cannot
write to or verify hosted Streamlit Secrets.

#### Business profiles

When no local profile exists, lead with profile creation and do not render
unrelated Drive or Synology controls. Preserve:

- profile summary with key, business, masked spreadsheet ID, local backup
  folder, Google connection/account, Synology state/path,
  and configuration source;
- business name and immutable safe profile key;
- optional local backup folder and Save profile for the initial setup record;
- profile-scoped Connect/reconnect Google;
- ledger spreadsheet selection through Google Picker, with OAuth open and
  Editor capability validation before saving its ID, rejecting a ledger
  already assigned to another local business profile;
- Validate ledger: initialize genuinely blank workbooks; populated legacy or
  incompatible workbooks are rejected without writes under the frozen
  [format-13 source contract](docs/SHEETS_SOURCE_CONTRACT.md); historical
  ledger/archive conversion is retired;
- edit of business name and local backup folder; and
- candidate workbook Picker authorization for recovery/migration that preserves
  the active ledger ID.

Sheets and Drive use the same human Google OAuth grant with `drive.file`.
There are no Sheets service-account upload, private-key, or rotation controls.

Failed validation leaves the prior profile intact. Never display private keys,
refresh tokens, private ledger data, or receipt contents. Readiness performs
fresh workbook and configured-destination checks without walking ordinary
Drive parent folders.

#### Google setup

Preserve profile-scoped Connect or reconnect, disconnect without deleting
Drive files or revoking the Google application grant, existing-root Picker selection or app-managed root creation,
Provision storage folders, and authorized-account/destination summaries.
Managed Receipts and Ledger Backups children are identified by stored IDs and
profile metadata rather than names alone.

#### Initial ledger provision

In Account settings > Google setup, a connected profile with no ledger can use
Create ledger spreadsheet instead of selecting an existing file. The app creates
`Business name Ledger` in that Google account's My Drive, saves its ID, and
initializes the existing required worksheets and default accounts/categories.
This does not require a separate Picker grant because the app creates the file.
The action is hidden once a ledger is configured and never replaces an existing
ledger. Drive receipt/backup folders are still configured in the same setup tab.

If creation or initialization is uncertain, no file is deleted or blindly
recreated. Inspect Drive and select the created file through Picker; if its ID
was saved, use Validate ledger to finish supported blank-workbook initialization.


#### Recovery

Preserve enable/disable, profile-root Cloud Sync summary, NAS destination,
schedule, retention, download-only direction, and destination-deletion
protection. Enabled records use layout profile-root automatically. Saving
these local metadata fields must not access Drive or verify DSM, and equivalent,
shared, or nested normalized NAS destinations are rejected.

Changing only local backup or Synology metadata does not change hosted Secrets.
Changing a Drive root while recovery is enabled is blocked until the recovery
record is disabled and saved.

#### Security and deployment

State that the application password grants access to every configured profile,
profile keys are configuration identifiers rather than users, local profile
storage is plaintext protected by the operating system, and hosted changes
require the documented export and replacement process. Generate hosted Secrets
reloads and validates profiles, uses an explicit allowlist, writes a new
ignored owner-only file without overwriting an existing one, and reports only
its path.

#### Acceptance criteria

All existing profile, credential, Drive, storage, recovery, readiness, and
hosted-export functions remain discoverable. The page does not imply
per-profile permissions, DSM monitoring, or in-app restore.

## Component contracts

### Date control

Use explicit labels such as From, To, Date, Trip date, or As of. Preserve the
scope. Reports As of is never combined with the income-and-expense range.

### Hierarchy selectors

Display full hierarchy paths where used, preserve stable IDs behind labels,
sort category options by parent and category name, restrict category options by kind,
and include inactive accounts only for
historical edit contexts where supported. Transfer destinations must differ
from the source.

### Currency input and output

Use two decimal places for currency, default new transaction amounts to 0.00,
require a positive amount before saving, right-align displayed values, and
preserve the existing opening-balance sign conventions.

### Selectable table

Map every displayed row to a stable ID, make selection clear, preserve an
explicit edit selector, and do not add multi-row selection outside the
approved Bulk transaction workflow.

### File upload

Show accepted types and preserve input after non-write validation errors where
possible. Distinguish parsing failure, validation failure, Drive upload
failure, and ledger-link failure. Never expose file contents or secrets in
diagnostics.

### Prepared exports

Avoid repeated large payload generation, show preparation time, use Refresh
when a set exists, and invalidate or separate the set after a confirmed
workbook write.

### Ledger search

Use the Search transactions label, the exact field scope above, structured
filter AND semantics, result count, clear action, no-results state, and the
same profile/table-generation reset behavior as the Transactions contract.

### Bulk action bar

Hide it without a selection, show count, expose only valid actions, keep
export secondary, and show category-change and deletion review summaries
before writing.

### Receipt-on-create

Treat save, upload, and link as ordered stages. Never report a confirmed
transaction as unsaved. On partial failure show its saved identity and retry
path. Do not reset the form until the selected workflow completes.

### Success notice

Use concise confirmed messages such as Transaction saved, Category updated for
12 transactions, Permanently deleted 3 transactions; linked Drive files were
retained, Imported 24 transactions, and Latest cloud backup downloaded and
verified. Do not show success before confirmation.

## Durable non-goals and prohibited patterns

The current design does not include reconciliation, Tag hierarchies,
Tag-based financial reports, receipt-content search, cash-flow reports, per-profile user authorization, or
bulk changes beyond export, compatible Category/Payee/Tags editing, and
permanent delete.
Do not add them as implied badges, controls, status fields, or backlog entries
in this design specification.

Do not introduce marketing hero sections, oversized headings, excessive
whitespace, gradients, glassmorphism, neon accents, decorative animation,
oversized pills, unexplained icon-only controls, colorful charts without
semantic purpose, hidden critical errors, generic confirmation language, or
irreversible actions without explicit confirmation.

When implementing a UI change, inspect the current page implementation and
the relevant canonical guide, preserve every current function, prefer native
Streamlit controls, and verify success and relevant failure paths at the
supported desktop and narrow viewports. This is an implementation discipline,
not a PR or agent-review procedure; repository review rules belong in
AGENTS.md and .gemini/styleguide.md.
