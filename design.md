# Project Tabula Rasa — Design System

## 1. Purpose

This document is the authoritative user-interface and interaction specification for Project Tabula Rasa.

It defines:

- Product character and design principles
- Visual tokens
- Layout and spacing
- Components and interaction patterns
- Dashboard and analytics hierarchy
- Financial data presentation
- Page-specific contracts
- Responsive behavior
- Accessibility requirements
- Streamlit implementation constraints
- Objective acceptance criteria
- Codex implementation and review procedures

This specification is intentionally **text-first**. Screenshots are not required for implementation or review. When visual references are consulted, they are research inputs only; the written rules in this document remain authoritative.

The current functional baseline was reconciled on 2026-08-06 against the application entry point, delegated profile-administration UI, and maintained guides for ordinary use, QuickBooks imports, business profiles, Google Drive, and backup/recovery.

---

## 2. Product Context and Current Functional Baseline

Project Tabula Rasa is a private, Google Sheets-backed bookkeeping and financial-operations application built in Python and deployed through Streamlit.

The primary users are the owner and, potentially, the owner's spouse. The repository, project, and application display label are Project Tabula Rasa. The application is not designed as a public consumer-finance product or a commercial multi-tenant accounting platform.

### 2.1 Current core use cases

The current application supports:

- Selecting among isolated business profiles
- Recording income, expense, and transfer transactions
- Reviewing, filtering, editing, and permanently deleting transactions
- Linking, uploading, opening, and unlinking transaction receipts through Google Drive
- Maintaining two-layer account and category hierarchies
- Recording, filtering, exporting, editing, and deleting business mileage
- Reviewing monthly income, expenses, net activity, category rollups, account balances, and a balance sheet
- Exporting transactions and mileage to CSV
- Creating and downloading a complete validated workbook backup
- Uploading and verifying Google Drive cloud backups
- Displaying the configured optional Synology recovery-copy expectations
- Importing Tabula Rasa transaction CSV files
- Previewing and importing supported QuickBooks transaction exports
- Previewing and importing supported QuickBooks mileage exports
- Adding and editing local business profiles
- Rotating Sheets service-account credentials
- Connecting each profile to a human-owned Google Drive and provisioning receipt and backup folders
- Recording per-profile Synology recovery metadata

### 2.2 Current and target navigation surface

The authenticated application currently exposes these operational pages, in this order:

1. Dashboard
2. Transactions
3. Mileage
4. Accounts
5. Categories
6. Reports
7. Data & backup
8. Account settings — only when the loopback-only local profile administrator is enabled

The approved target design preserves the seven operational pages and reframes the current `Business profiles` route as **Account settings**.

Target sidebar structure:

1. Dashboard
2. Transactions
3. Mileage
4. Accounts
5. Categories
6. Reports
7. Data & backup
8. Account settings — visually separated from operational navigation and available only under the current local-administration safety conditions
9. Log out

`Account settings` is the familiar settings destination for business-profile setup, Google Drive connection, storage destinations, credential rotation, and recovery configuration. It is not a per-user identity or permission-management page.

No reconciliation page is planned.

### 2.3 Functional preservation rule

The current codebase and maintained documentation define the minimum functional baseline.

A redesign must not remove, hide, merge away, or make materially harder to discover any current function unless the task explicitly authorizes that product change.

Visual restructuring is permitted only when all affected workflows remain available, including conditional and local-only workflows.

When this document conflicts with the current implementation or maintained product documentation, Codex must:

1. Preserve current functionality.
2. Identify the conflict.
3. Update this document or request an explicit product decision.
4. Never silently omit the existing function.

### 2.4 Non-UI operational baseline

A UI redesign must not disrupt or imply replacement of the current command-line and operational workflows, including:

- Local and Google Drive backup creation
- Weekly scheduled backup registration
- Backup validation
- Restore into a new blank workbook
- Receipt-file recovery and Drive-ID remapping from the independent recovery copy
- Historical backup-format conversion
- Google Sheets validation and reversible write testing
- Hosted Streamlit Secrets export
- Synology Cloud Sync and retention procedures performed outside the application

These workflows may remain outside the Streamlit interface. The design must not add misleading in-app Restore, NAS health, or scheduler controls unless the underlying capability is implemented in the same task.

### 2.5 Approved proposed behavior

This design approves the following additive features for implementation:

1. **Receipt upload during transaction creation**
   - The optional receipt is selected in the Add transaction form.
   - The transaction is validated and confirmed in Google Sheets before Drive upload begins.
   - The saved transaction, receipt upload, and reference-link result are presented as one user workflow.
   - Existing post-creation receipt management remains available.

2. **Transaction ledger search (current behavior)**
   - Search is additive to the existing date, type, and account filters.
   - Search is case-insensitive and covers the visible transaction text fields specified in Section 18.
   - Search does not replace existing filters.

3. **Explicit bulk-selection mode for the transaction ledger**
   - Default mode remains single-row selection for editing.
   - Bulk mode permits multi-row selection without weakening the existing edit workflow.
   - The initial approved bulk actions are: export selected rows, change category for a compatible selection, and permanently delete selected transactions.

4. **Account settings information architecture**
   - The current local-only Business profiles functionality is retained and presented as an Account settings page.
   - All current profile, Drive, credential, and Synology controls remain available.

These are target behaviors, not claims about the current implementation. Until code and tests implement a target behavior, the current workflow remains the functional baseline.

The following remain out of scope unless separately approved:

- Account reconciliation
- Transaction tags
- Bulk changes to dates, amounts, payees, references, descriptions, accounts, transfers, or receipts
- Receipt-content search
- Cash-flow or reconciliation reports
- Per-profile user authorization

---

## 3. Product Character

The interface should feel:

- Professional
- Calm
- Precise
- Trustworthy
- Financially literate
- Operational
- Efficient
- Purpose-built

The application should not feel like:

- A marketing website
- A consumer banking promotion
- A cryptocurrency dashboard
- A gamified budgeting application
- A generic admin template
- A spreadsheet with decorative styling added afterward
- A collection of unrelated cards
- A showcase for charts or animation

The application should be comfortable to use for extended bookkeeping sessions.

---

## 4. Design Foundations

### 4.1 Seline-derived analytics hierarchy

Use Seline-inspired principles for:

- Dashboard composition
- Analytical hierarchy
- Warm canvas surfaces
- White data panels
- Quiet charts
- Clear distinction between primary and supporting metrics
- Asymmetrical layouts that reflect information importance
- Restraint in color and decoration

Do not adopt a strict single-accent-color limitation. Project Tabula Rasa requires distinct semantic red, green, amber, blue, and neutral states.

### 4.2 Attio-derived component geometry

Use Attio-inspired principles for:

- Buttons
- Inputs
- Selectors
- Navigation
- Dialogs
- Filters
- Moderate corner radii
- Hairline borders
- Compact control spacing
- Clear focus and selection states

Do not adopt marketing-oriented section spacing or landing-page composition.

### 4.3 Tabula Rasa financial and operational semantics

Use a restrained semantic palette for:

- Positive and negative deltas
- Active and inactive records
- Balanced and out-of-balance statements
- Import readiness, duplicates, and errors
- Backup availability and verification
- Receipt availability and integrity
- Destructive actions
- Warnings
- Successful completion

Semantic color must reinforce meaning without dominating the interface.

---

## 5. Design Authority

When requirements or references conflict, apply the following order:

1. Current accounting and data-integrity behavior in the codebase
2. Current maintained product and operations documentation
3. Explicit requirements in the active task
4. Streamlit implementation constraints
5. Accessibility requirements
6. This design system
7. External design references
8. General visual judgment

The current functional baseline in Section 2 is mandatory.

External screenshots, galleries, or reference products are inspiration only.

Do not copy another product's:

- Brand colors
- Logos
- Typography
- Proprietary terminology
- Decorative styling
- Data visualizations without adaptation
- Interaction patterns that are impractical in Streamlit

Do not infer that a visually simplified page may omit operational controls, warnings, validation output, recovery information, or local-administration features.

---

## 6. Core Design Principles

### 6.1 Information before decoration

Financial data, bookkeeping state, and required actions take priority over visual ornament.

### 6.2 Dense but readable

The interface should use screen space efficiently without appearing crowded.

Use compact spacing for:

- Tables
- Filters
- Forms
- Navigation
- Repetitive financial rows
- Validation summaries
- Backup and import controls

Use larger spacing only between major information groups.

### 6.3 Tables are primary

Transaction, mileage, account, category, report, and profile tables are core application surfaces.

Charts are secondary and should support interpretation rather than act as decoration.

### 6.4 One dominant action per workflow section

A page may contain multiple independent workflows. Each workflow section, form, tab, or expander should normally have one obvious primary action.

Examples:

- Save transaction
- Save mileage trip
- Add account
- Add category
- Upload fresh backup now
- Import validated rows
- Validate and save

Do not suppress valid secondary workflows merely to force one action across an entire multi-purpose page.

### 6.5 Color is semantic

Use color to communicate:

- State
- Direction
- Risk
- Completion
- Selection
- Required attention

Do not use color merely to create visual variety.

### 6.6 No hover-only functionality

Important actions, values, warnings, and states must remain visible or accessible without hover.

### 6.7 Native Streamlit first

Prefer native Streamlit components wherever they can satisfy the requirement.

Use custom HTML, CSS, or custom Streamlit components only when the benefit is substantial and maintainable.

### 6.8 Text specifications are authoritative

Screenshots are not required.

For every page or component, implementation should be based on:

- Written purpose
- Current functional baseline
- Content hierarchy
- Layout contract
- Interaction rules
- Responsive behavior
- Acceptance criteria

### 6.9 Safe actions are explicit

Material actions must communicate their consequence before execution.

Examples:

- Permanently deleting a transaction
- Permanently deleting a mileage trip
- Permanently deleting an eligible category
- Removing a receipt reference while retaining the Drive file
- Rotating a service-account credential
- Disconnecting Google Drive
- Changing a profile's storage destination
- Committing imported rows
- Creating or uploading a recovery backup

### 6.10 Profile isolation is always visible

Every workbook read, write, import, export, receipt operation, backup, and cache is scoped to the selected business profile.

The active business and workbook context must remain discoverable. A redesign must not make cross-profile scope ambiguous.

### 6.11 Current shell identity and profile transitions

The current application display identity is **Project Tabula Rasa**. The sign-in
surface, sidebar title, Streamlit page title, and shell-level documentation use
that name. The operational route label **Account settings** is current after
the #62 information-architecture change.

When the selected business changes, the sidebar continues to show the selected
business and workbook context. Page selections, table widget keys, edit-row
selections, date filters, and pending write notices must not be reused across
profiles in a way that makes the active workbook ambiguous. A profile change
must not initialize or access another profile's storage.

The sign-in surface uses the keyed native container `login_surface` so its
responsive width rule targets the rendered login surface without depending on
an undocumented bordered-container test ID. The supported Streamlit DOM should
keep that keyed surface at a readable width on desktop layouts.

---

## 7. Color System

### 7.1 Neutral palette

| Token | Value | Usage |
|---|---|---|
| `canvas` | `#F5F4F0` | Main application background |
| `surface-primary` | `#FFFFFF` | Tables, forms, cards, dialogs |
| `surface-secondary` | `#FAFAF8` | Secondary panels and grouped controls |
| `surface-hover` | `#F2F3F4` | Row and control hover states |
| `surface-selected` | `#EAF0FC` | Selected rows and active navigation |
| `text-primary` | `#202124` | Main text and financial values |
| `text-secondary` | `#62666B` | Supporting text and descriptions |
| `text-muted` | `#85898E` | Timestamps and tertiary metadata |
| `border-default` | `#DDDED9` | Standard borders and dividers |
| `border-subtle` | `#E9E9E5` | Table row separators |
| `border-strong` | `#B8BAB6` | Focused or emphasized boundaries |

The canvas should be subtly warm. Primary data surfaces should remain white.

### 7.2 Interactive palette

| Token | Value | Usage |
|---|---|---|
| `interactive-primary` | `#3267D6` | Primary buttons, links, selected controls |
| `interactive-hover` | `#2858BC` | Primary hover state |
| `interactive-subtle` | `#EAF0FC` | Selected rows, active navigation backgrounds |
| `interactive-focus` | `#6B96ED` | Focus rings |

Blue is the default interaction color.

Blue must not communicate financial gain or positive performance.

### 7.3 Semantic palette

| Meaning | Text | Background | Border |
|---|---|---|---|
| Positive / Success | `#287A4B` | `#EAF5EE` | `#B7DCC5` |
| Negative / Error | `#B33A3A` | `#FBECEC` | `#E8BABA` |
| Warning / Attention | `#996600` | `#FFF5D9` | `#E7CE8C` |
| Informational | `#3267D6` | `#EAF0FC` | `#B8CAF1` |
| Neutral / Pending | `#62666B` | `#F1F2F1` | `#D5D7D4` |

### 7.4 Semantic color rules

Use green for:

- Positive financial movement when positive is favorable in context
- Successful saves, imports, uploads, and verification
- Balanced balance-sheet state
- Confirmed completion
- Healthy validation state

Use red for:

- Negative financial movement when negative is adverse in context
- Errors
- Failed imports or backup operations
- Invalid workbook, profile, or accounting state
- Destructive actions

Use amber for:

- Duplicate or skipped import rows
- Missing or unavailable configuration
- Out-of-balance statements
- Receipt or recovery conditions requiring attention
- Incomplete setup
- Conditions that require review but are not data-loss errors

Use blue for:

- Selection
- Navigation
- Links
- Primary actions
- Informational status

Use neutral gray for:

- Pending states that do not yet require attention
- Disabled states
- Inactive account metadata
- Read-only context

Do not use green as the default Save button color.

Do not use red for ordinary navigation or cancellation.

Do not rely on color alone. Pair semantic color with text, an icon, a sign, or an explicit message.

---

## 8. Positive and Negative Values

Financial direction must remain understandable without color.

### 8.1 Amount formatting

Examples:

```text
+$1,250.00
−$420.00
$0.00
```

Use:

- A plus sign for positive deltas when direction matters
- A consistent minus sign for negative values
- Tabular numerals
- Consistent currency precision
- Parentheses only when a report convention explicitly requires them

### 8.2 Color treatment

Use semantic green or red for:

- Period-over-period deltas
- Gains and losses
- Variances
- Cash-flow changes
- Performance comparisons

Do not color every transaction amount.

Ordinary ledger entries should normally use neutral text because positive and negative accounting meaning depends on account context.

### 8.3 Supporting indicators

Use one of the following with a colored delta:

- Up or down arrow
- Plus or minus sign
- Increase or Decrease label
- Previous-period comparison
- Explicit status label

Example:

```text
Net income
$12,480
↑ 8.4% from last month
```

### 8.4 Negative balance handling

A negative balance is not automatically an error.

Use red only when the negative value is adverse in context, such as a negative asset balance or a reported imbalance requiring investigation.

Do not color normal liability or equity ledger balances red merely because their stored signs are negative. Reports present liabilities and equity using conventional positive statement values.

---

## 9. Typography

### 9.1 Font family

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

Do not require a custom web font for correct rendering.

### 9.2 Type scale

| Role | Size | Weight |
|---|---:|---:|
| Application title | 24px | 600 |
| Page title | 22px | 600 |
| Section title | 16px | 600 |
| Card title | 14px | 600 |
| Body text | 14px | 400 |
| Form control text | 14px | 400 |
| Table text | 13–14px | 400 |
| Secondary text | 12px | 400 |
| Label text | 12px | 500 |
| Major metric | 26–32px | 600 |
| Supporting metric | 18–22px | 600 |

Avoid oversized 40–60px dashboard numbers unless a page has one genuinely dominant value.

### 9.3 Financial numerals

Use tabular numerals where supported:

```css
font-variant-numeric: tabular-nums;
```

Right-align comparable numeric table columns.

### 9.4 Writing style

UI text should be:

- Direct
- Specific
- Concise
- Consistent
- Action-oriented

Prefer:

- `Save Transaction`
- `3 duplicate rows will be skipped`

Avoid:

- `Submit`
- `Proceed`
- `Something went wrong`
- Excessively casual language

---

## 10. Spacing System

Use a 4px base spacing grid.

Approved spacing values:

```text
4px
8px
12px
16px
20px
24px
32px
40px
```

### 10.1 Default spacing

| Context | Spacing |
|---|---:|
| Icon to label | 6–8px |
| Form label to control | 4–6px |
| Controls in the same group | 8–12px |
| Table toolbar controls | 8px |
| Card internal padding | 16px |
| Dense metric-card padding | 12–16px |
| Between related cards | 12–16px |
| Between dashboard sections | 24px |
| Between major page sections | 24–32px |
| Page top and side padding | 24–32px |

### 10.2 Prohibited marketing spacing

Do not use:

- 64px gaps between ordinary application sections
- 80–120px marketing-page section spacing
- Excessive whitespace around headings
- Large empty areas inserted only for visual effect

At 1440 × 1000, the user should normally see the page title, primary action, primary financial summary, and at least one supporting section without scrolling.

---

## 11. Geometry and Elevation

### 11.1 Corner radius

| Component | Radius |
|---|---:|
| Buttons | 6–8px |
| Inputs | 6–8px |
| Selectors | 6–8px |
| Cards | 8px |
| Dialogs | 10–12px |
| Status badges | Pill |
| Filter chips | Pill |
| Tables | 0–8px depending on container |

Avoid using 16–32px radii throughout the application.

### 11.2 Borders

Use thin borders as the primary method of separating surfaces.

Default:

```text
1px solid border-default
```

Use hairline row separators in tables.

### 11.3 Shadows

Shadows are not used by default.

Permitted uses:

- Dialogs
- Popovers
- Floating menus
- Temporary overlays
- One major elevated panel when necessary

Do not apply shadows to every card.

---

## 12. Application Shell

### 12.1 Desktop layout

The desktop application uses:

- Persistent left navigation
- Main content area
- Optional page-level controls
- No oversized global header

Recommended dimensions:

| Element | Size |
|---|---:|
| Sidebar width | 220–248px |
| Main content padding | 24–32px |
| Maximum readable content width | 1440px |
| Standard page width | Fluid |
| Dense report width | Full available width when needed |

The application should use available desktop width rather than forcing all content into a narrow centered column.

### 12.2 Sidebar

The sidebar must preserve:

1. Product name
2. Business selector when profiles exist
3. Selected business caption
4. Operational navigation in the current order
5. A visually separated utility area
6. Account settings when local administration is enabled
7. Log out action
8. Selected workbook title for normal application pages

Operational destinations appear beneath a `Workspace` section label. The label
uses smaller semibold muted text, slight letter spacing, and a distinct gap
before the destinations so it reads as a group heading rather than a page.

Target operational navigation:

1. Dashboard
2. Transactions
3. Mileage
4. Accounts
5. Categories
6. Reports
7. Data & backup

Target utility navigation:

- Account settings — the displayed route label for local profile administration
- Log out

When no profiles exist and local administration is available, Account settings is the only available page.

Active navigation should use:

- Subtle accent background or indicator
- Stronger text
- Compact rows
- No oversized button treatment

Account settings should be visually separated from bookkeeping work, typically near the bottom of the sidebar. A gear icon may supplement the text label but must not replace it.

### 12.3 Business context selector

The current business selector scopes all workbook operations, receipts, imports, exports, backups, duplicate-submission checks, and caches.

The selected business must remain visible.

Changing business must:

- Update page scope clearly
- Never imply data from profiles are combined
- Preserve safe rerun behavior
- Not silently submit partially completed forms

### 12.4 Workbook, settings, and deployment context

The selected workbook title should remain visible in the sidebar on ordinary pages.

The current `Business profiles` functionality becomes the target **Account settings** page. Its configuration controls remain local-administration functions and must not be presented as writable in hosted or non-loopback environments when the current safety checks disable them.

Account settings must make the boundary explicit:

- Business profiles configure separate ledger workbooks and credentials.
- Google Drive settings configure profile-scoped receipt and backup storage.
- Synology settings record expected external recovery-copy configuration.
- Current authentication is application-wide and does not provide per-profile user permissions.

The page must not imply that the app can edit hosted Streamlit Secrets directly, inspect DSM status, or manage user identities unless those capabilities are implemented.

### 12.5 Authentication and logout

The application password gate and log out control are part of the required shell.

Current authentication grants access to every configured profile. The interface must not imply profile-level user authorization that does not exist.

---

## 13. Page Headers and Workflow Actions

Each page should have a compact header containing:

- Page title
- Optional one-line description
- Relevant scope information when needed

The page header should not resemble a marketing hero section.

Recommended spacing:

```text
Page title to description: 4–6px
Header to first workflow section: 16–24px
```

### 13.1 Action placement

Place an action in the page header only when it applies clearly to the whole page.

Many current pages contain independent tabs or sections. Their primary actions should remain inside the relevant workflow:

- Save transaction inside Add transaction
- Save mileage trip inside Add trip
- Add account inside Add account
- Import validated rows inside its import section
- Upload fresh backup now inside Google Drive backup

Do not move all page actions into a crowded global toolbar merely for visual uniformity.

### 13.2 Breadcrumbs

Breadcrumbs are optional.

Use them only if a redesign introduces a true nested route hierarchy. The current pages are top-level and do not require breadcrumbs.

---

## 14. Dashboard Hierarchy

The dashboard should use Seline-inspired analytical hierarchy while preserving its current information set.

### 14.1 Current dashboard purpose

The current dashboard answers:

- What is the total current account balance?
- What are income, expenses, and net activity for the current month?
- What transactions happened most recently?
- What are the current account balances?

### 14.2 Required current content

The redesign must preserve:

1. Total balance
2. Income this month
3. Expenses this month
4. Net this month
5. Recent activity table
6. Account balances table

The current recent-activity table displays:

- Date
- Type
- Payee
- Category
- Account
- Amount

The current account-balance table displays:

- Account
- Classification
- Type
- Balance

### 14.3 Recommended hierarchy

Use this hierarchy:

1. Current-month financial summary
2. Recent activity
3. Account balances

The four current metrics may be visually grouped so that Net this month or Total balance is more prominent, but none may be omitted.

Future analytics—such as period selectors, attention panels, or trend charts—must be additive and may not replace the current metrics or tables without an explicit product change.

### 14.4 Dashboard wireframe

```text
┌──────────────────────────────────────────────────────────────────┐
│ Your books at a glance                                           │
│ A current view of cash, income, and spending.                    │
├────────────────┬────────────────┬────────────────┬───────────────┤
│ Total balance  │ Income month   │ Expenses month │ Net month     │
├──────────────────────────────────────┬───────────────────────────┤
│ Recent activity                      │ Account balances          │
│ Date | Type | Payee | Category | ... │ Account | Class | Type... │
└──────────────────────────────────────┴───────────────────────────┘
```

### 14.5 Dashboard design rules

- Do not add marketing-style introductory spacing.
- Keep all four metrics visible near the top.
- Use neutral transaction amounts except where a directional comparison is explicitly added.
- Preserve the empty-state path to Transactions when no records exist.
- Preserve conventional currency formatting.
- Keep recent activity wider than account balances at desktop widths.

### 14.6 Dashboard acceptance criteria

- All four current metrics remain present.
- Recent activity and account balances remain present.
- Current-month scope is explicit.
- No large decorative chart displaces core data.
- The two lower sections stack in a logical order on narrow screens.
- Empty data does not cause errors or misleading unavailable values.

---

## 15. Charts and Analytics

Charts should be quiet, readable, and subordinate to the underlying values.

### 15.1 Preferred chart types

Use:

- Line charts for trends
- Bars for period comparisons
- Horizontal bars for category ranking
- Stacked bars when composition matters
- Small sparklines for compact trends

Avoid:

- 3D charts
- Donut charts with many categories
- Decorative area charts without clear values
- Multiple saturated colors
- Charts that repeat information already visible in a metric

### 15.2 Chart color rules

Use blue as the primary series.

Use semantic green and red only when the series itself represents positive and negative meaning.

For multiple neutral categories:

- Use related muted tones
- Direct-label important series
- Avoid rainbow palettes

### 15.3 Chart structure

Charts should include:

- Clear title
- Time period or scope
- Units
- Readable axes
- Limited gridlines
- Tooltip or visible values
- Empty-state behavior

### 15.4 Chart sizing

Default dashboard chart height:

```text
220–320px
```

Do not use full-page charts unless the page is specifically an analytical report.

### 15.5 Chart acceptance criteria

- Chart meaning is understandable from title, axes, and labels
- Color is not the only means of differentiating critical data
- Values use consistent currency or percentage formatting
- Empty and single-point datasets render safely
- Chart does not cause horizontal page overflow

---

## 16. Metric Cards

Metric cards should contain:

- Short label
- Primary value
- Optional delta
- Optional period comparison
- Optional one-line context

Recommended structure:

```text
Net cash flow
$8,420
↑ 12.4% from July
```

Rules:

- Keep labels concise
- Use tabular numerals
- Avoid icons unless they communicate meaning
- Avoid decorative illustrations
- Avoid large empty padding
- Do not place every metric inside a heavily bordered card

Metric cards may appear as flat grouped items within a larger analytical surface.

### 16.1 Metric card states

Support:

- Normal
- Positive change
- Negative change
- Warning
- Loading
- Unavailable

Unavailable data should display `—`, not `$0.00`, unless the value is truly zero.

---

## 17. Tables and Ledgers

Tables are core application components.

### 17.1 Density

Default table row height:

```text
36–44px
```

### 17.2 Alignment

- Dates: left-aligned
- Text descriptions: left-aligned
- Boolean or short state fields: left or center
- Amounts and balances: right-aligned
- Counts: right-aligned

### 17.3 Table hierarchy

Use:

- Subtle header background or strong divider
- Medium-weight column labels
- Hairline row separators
- Restrained hover state
- Clear selected-row state
- Sticky headers where feasible

Avoid:

- Heavy borders around every cell
- Alternating saturated row colors
- Large buttons inside every row
- Icon-only actions without labels or help

### 17.4 Current transaction table headers

The View & edit ledger table currently displays these columns in this exact order:

1. Date
2. Type
3. Account
4. To account
5. Category
6. Payee
7. Description
8. Amount
9. Receipt
10. Reference
11. ID

The redesign may adjust responsive presentation and column widths, but must not silently omit any current field.

`To account` remains blank for non-transfer transactions.

`Category` remains blank for transfers.

`Receipt` uses a paperclip indicator when one or more receipts are linked.

`ID` is an operational identifier used for selection and disambiguation. It may be visually de-emphasized, but must remain accessible in the ledger or edit selector.

### 17.5 Transaction selection modes and edit behavior

The ledger has two explicit modes.

Bulk mode implements the following behavior: it is entered explicitly, selects
only visible rows, and exposes only the approved actions below.

#### Edit mode — default

- Uses single-row selection.
- Selecting or double-clicking a row sets the transaction used by the Edit transaction expander.
- A separate transaction selector remains available inside that expander.
- The user can choose any transaction in the current filtered and searched result set.

#### Bulk mode — current

- Uses multi-row selection.
- The edit expander is disabled or visually de-emphasized while bulk mode is active.
- A bulk-action bar appears only after one or more rows are selected.
- The selection count is always visible.
- Switching between Edit and Bulk modes clears incompatible row selections but preserves filters, search, and interactive sort.

Both modes must preserve:

- A clear selected-row state
- Latest-date-first default ordering
- User-applied interactive table sorting while remaining on Transactions
- Reset to latest-date-first after navigating away and back

Changing any filter or search scope clears bulk selection before another bulk action can run.

### 17.6 Other required table schemas

Mileage table:

1. ID
2. Date
3. Miles
4. From
5. Destination
6. Business purpose
7. Vehicle
8. Notes

Accounts table:

1. Account
2. Layer
3. Parent
4. Classification
5. Type
6. Active
7. Balance
8. Transaction count

Categories table:

1. Category
2. Layer
3. Parent
4. Type
5. Transaction count

Report and profile tables must preserve the fields specified in their page contracts.

### 17.7 Current bulk ledger actions

Bulk actions are available only in explicit Bulk mode.

Initial approved actions:

1. **Export selected**
   - Downloads the selected ledger rows as CSV.
   - Uses the same user-facing columns and current profile scope.
   - Does not modify ledger data.

2. **Change category**
   - Available only when every selected row is Income or every selected row is Expense.
   - Transfers are not eligible.
   - Mixed Income and Expense selections are not eligible.
   - The category selector shows only categories matching the common transaction type.
   - The complete selection is revalidated immediately before one batch write.

3. **Permanently delete selected**
   - Shows the number of transactions and aggregate absolute amount before confirmation.
   - Requires an explicit acknowledgement that deletion is permanent.
   - Clearly states that linked receipt files remain in Google Drive and become unreferenced rather than being deleted.
   - Revalidates the selected IDs before one batch delete.

Bulk actions must not partially apply silently. The implementation must validate the entire selection before writing and report the exact outcome.

Not approved as initial bulk actions:

- Change date or amount
- Change payee, reference, or description
- Change source or destination account
- Convert transaction type
- Add, remove, or relink receipts
- Edit transfers
- Add tags

Do not add reconciliation, import-source, or unsupported status columns.

Bulk category changes and deletions use one Google Sheets
[`spreadsheets.batchUpdate`](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate)
request per mutation. Google validates every request before applying the batch
and guarantees that the requests are applied atomically; a collaborator may
still change the final sheet while the operation is in flight. An uncertain
response is followed by a fresh ID-based read and is classified as fully
applied, not applied and safely retryable, or mixed/ambiguous. The application
never retries an ambiguous mutation automatically.

### 17.8 Table empty states

Tables should distinguish among:

- No records exist
- No records exist in the selected date range
- No records match the active filters
- Data failed to load

Each state should preserve the relevant current next action.

---

## 18. Filters and Table Scope

### 18.1 Transaction-ledger filters and search

The transaction ledger preserves these current filters:

1. From date
2. To date
3. Type: All, Income, Expense, or Transfer
4. Accounts multiselect

The account filter includes a transfer when a selected account appears on either side of that transfer.

Add a compact search field labeled `Search transactions` above the ledger.

Search behavior:

- Applies after the current date, type, and account filters.
- Uses trimmed, case-insensitive substring matching.
- Searches: Type, Account, To account, Category, Payee, Description, Reference, and ID.
- Supports a full or partial transaction ID.
- Does not search receipt file contents, receipt filenames, amounts, or hidden Google Drive metadata.
- Displays the resulting row count.
- Provides a clear control when text is present.
- Shows an explicit no-results state without clearing the other filters.
- Empty or whitespace-only search text is treated as no search and restores the structured-filter result set.
- A completely empty ledger has a distinct empty state from a ledger with no rows matching the active filters or search.

The date, type, account, and search controls must remain visible above the ledger. Search must not replace the structured filters.

### 18.2 Current mileage filters

The mileage log currently provides:

1. From date
2. To date

The resulting scope controls the table, trip count, business-mile total, and filtered mileage CSV download.

### 18.3 Current report controls

Reports currently provide:

- From date
- To date
- A separate As of date for the balance sheet

The P&L metrics, monthly performance, expense-category analytics, and category detail use the From and To range.

The balance sheet uses the As of date.

### 18.4 Filter and search behavior

- Filter labels must remain explicit.
- Changing a filter or search value must rerun the relevant scoped read safely.
- Current selected business scope always takes precedence.
- Transaction account paths should remain hierarchical.
- Search and filters combine using AND semantics.
- Changing the result scope clears bulk selection.
- Clearing search restores the structured-filter result set and preserves date, type, account, and sort choices.
- Single-row edit selection is repaired to a visible row when a search changes the result set, and cleared when no rows remain.
- Search text may persist while switching between Add transaction and View & edit ledger, but should reset after leaving Transactions if that matches the existing table-generation reset behavior.

### 18.5 Future filters

Category filtering, amount ranges, receipt-presence filtering, and saved filter presets may be added later.

They are additive features and must not replace the current date, type, account, or approved search controls.

---

## 19. Forms

Forms should prioritize efficient and accurate data entry.

### 19.1 Form layout

Use:

- One column for sequential decisions
- Two columns for clearly related desktop fields
- Logical top-to-bottom tab order
- Visible labels
- Concise helper text
- Validation near the relevant workflow

Stack fields vertically on narrow screens.

### 19.2 Add-transaction entry structure — current behavior

The Add transaction tab uses this structure:

1. Transaction type segmented control: Income, Expense, Transfer
2. Date
3. For Income or Expense: Category and Amount on one row
4. For Transfer: Amount
5. From Account
6. For Transfer only: To account
7. Payee / customer and Reference (optional) on one row
8. Description / memo
9. Receipt (optional)
10. Save transaction

Conditional rules:

- Income and Expense require a category of the same type.
- Transfer has no category.
- Transfer requires two different active accounts.
- Only active accounts are offered for new transactions.
- The form is unavailable with a clear warning when no active account exists.
- Income or Expense entry is unavailable with a clear warning when no matching category exists.
- Receipt accepts zero, one, or multiple files using the same file types as the
  post-creation receipt uploader: PDF, PNG, JPG, JPEG, WEBP, or HEIC.
- Each selected file must be non-empty and no larger than 20 MB. Filenames are
  sanitized and duplicate names receive numeric suffixes without overwriting.
- Receipt selection is optional and does not change accounting validation.

Tags and advanced accounting fields are not implemented.

### 19.3 Add-transaction submission and receipt sequence — current behavior

The primary action remains:

```text
Save transaction
```

When no receipt is selected:

1. Validate the form.
2. Save the transaction.
3. Show confirmed success.
4. Reset the form intentionally on the next rerun.

When one or more receipts are selected:

1. Validate all transaction fields and every selected file before any write.
2. Create the transaction in Google Sheets.
3. After Sheets confirms creation and returns the transaction ID, upload each
   receipt to the selected profile's receipt folder.
4. Persist each receipt reference on the saved transaction independently.
5. Show one concise saved-transaction notice with the number of complete and
   unresolved receipts, any available unresolved errors, and one retry action.
6. Reset the form only after every selected receipt is linked.

Failure behavior:

- If transaction validation fails, do not upload the receipt.
- If the transaction save fails, do not upload the receipt.
- If the transaction saves but one or more receipt uploads fail, retain the
  transaction and every receipt already linked. Show a warning with a direct
  retry path for only the unresolved receipts.
- If a file uploads but linking fails, retain its exact Drive-file reference and
  retry linking that file or use the Unreferenced receipt workflow. Do not upload
  the same local file again as the primary recovery action.
- Preserve form and file state after a non-write validation error where Streamlit permits.
- Duplicate completed submissions must not create duplicate transactions or duplicate receipt files.

There is no required Cancel or Save and Add Another action.

### 19.4 Current edit-transaction form

The edit form preserves the transaction type and supports editing:

- Source account
- Destination account for transfers
- Category for income or expense
- Date
- Amount
- Payee / customer
- Reference
- Description

The edit form also provides:

- Save changes
- A permanent-deletion warning
- An explicit acknowledgement checkbox
- Permanently delete

Transfer source and destination accounts must remain different.

Inactive accounts already referenced by the selected transaction remain available for editing that historical record.

### 19.5 Validation and write safety

Validation must identify:

- The specific problem
- The action required to correct it
- Whether any write occurred

Failed saves preserve entered values where Streamlit permits.

A success message appears only after the Google Sheets operation is confirmed.

### 19.6 Add-transaction target wireframe

```text
┌──────────────────────────────────────────────────────────────┐
│ Add transaction                                              │
│ [Income] [Expense] [Transfer]                                │
├──────────────────────────────────────────────────────────────┤
│ Date                                                         │
├──────────────────────────────┬───────────────────────────────┤
│ Category*                    │ Amount                        │
├──────────────────────────────┴───────────────────────────────┤
│ From Account                                                 │
├──────────────────────────────────────────────────────────────┤
│ To account*                                                  │
├──────────────────────────────┬───────────────────────────────┤
│ Payee / customer             │ Reference (optional)          │
├──────────────────────────────┴───────────────────────────────┤
│ Description / memo                                           │
├──────────────────────────────────────────────────────────────┤
│ Receipt (optional)                                           │
│ [Choose file]                                                │
│ PDF, PNG, JPG, JPEG, WEBP, or HEIC                          │
├──────────────────────────────────────────────────────────────┤
│ [Save transaction]                                           │
└──────────────────────────────────────────────────────────────┘

* Category appears for Income and Expense.
* To account appears for Transfer.
```

The receipt control follows the descriptive fields so it does not interrupt the core accounting sequence.

### 19.7 Mileage-entry form

The Add trip tab must preserve:

1. Trip date
2. Vehicle (optional)
3. Business miles
4. Starting location
5. Destination
6. Round trip checkbox with explanatory help
7. Business purpose
8. Notes (optional)
9. Save mileage trip

Round trip creates two entries in one confirmed write. Each entry uses the entered one-way mileage, and the return entry reverses the locations.

---

## 20. Buttons

### 20.1 Primary button

Use blue for the default primary action.

Current examples:

- Save transaction
- Save changes
- Save mileage trip
- Add account
- Add category
- Upload fresh backup now
- Import validated rows
- Import validated mileage
- Validate and save

### 20.2 Secondary button

Use neutral styling for ordinary alternative actions, including:

- Verify latest cloud backup
- Prepare or refresh downloadable exports
- Cancel a receipt-reference removal
- Link selected receipt

### 20.3 Success or completion action

Green may be used only when the action itself represents a semantically successful completion rather than an ordinary save.

Most current completion is communicated through success messages after confirmation. Do not recolor every save or import button green.

### 20.4 Destructive button

Use red for current destructive actions:

- Permanently delete transaction
- Permanently delete mileage trip
- Permanently delete eligible category
- Disconnect or revoke when consequence is clear

Removing a receipt reference is destructive to the association but does not delete the Drive file; its copy must state that distinction.

### 20.5 Warning action

Amber may be used sparingly for a retry or review action when the operation is not destructive.

### 20.6 Disabled buttons

Disabled buttons must remain legible and should communicate why the action is unavailable through nearby helper text when the reason is not obvious.

Examples include import actions disabled by validation errors or cloud verification disabled when no backup exists.

---

## 21. Status and State Labels

Compact status labels may be used when they represent a real current state.

Current examples include:

| State | Treatment |
|---|---|
| Active account | Neutral or positive text plus explicit `Active` value |
| Inactive account | Neutral muted treatment plus explicit `Inactive` value |
| Balance sheet balanced | Green success notice with text |
| Balance sheet out of balance | Amber warning with difference amount |
| Import ready | Neutral or blue metric label |
| Duplicate import row | Amber warning and row numbers |
| Import error | Red error message |
| Backup verified | Green success message |
| Backup unavailable or not configured | Informational or amber message |
| Receipt linked | Paperclip in ledger and explicit receipt link in editor |
| Synology recovery enabled | Explicit configuration summary, not a presumed health indicator |

Do not add reconciliation, review, imported/manual, or attachment-missing badges to transaction rows unless those states are implemented and stored.

### 21.1 State-text rules

- Use the exact operational meaning.
- Do not imply a backup is healthy merely because a destination is configured.
- Do not imply Synology synchronization succeeded; the app does not inspect DSM.
- Do not imply a receipt file is deleted when only its transaction reference is removed.
- Do not use color without text.

---

## 22. Alerts, Notices, and Inline Messages

### 22.1 Informational notice

Use blue for non-urgent explanatory information.

### 22.2 Warning notice

Use amber when the user can continue but should review a condition.

### 22.3 Error notice

Use red when an action failed or data may be invalid.

### 22.4 Success notice

Use green after successful completion.

Success notices should be concise and should not remain permanently when the user has already moved on.

### 22.5 Message structure

A good message contains:

- What happened
- Whether data changed
- What the user should do next

Example:

```text
Import failed. No transactions were added. Correct the date column and try again.
```

---

## 23. Expanders, Containers, Tabs, and Optional Overlays

### 23.1 Current tabs

Tabs currently organize:

- Transactions: Add transaction; View & edit ledger
- Mileage: Add trip; View & edit mileage log

These workflow divisions must remain clear even if the visual implementation changes.

### 23.2 Current expanders and bordered containers

Current uses include:

- Edit transaction
- Edit mileage trip
- Add account
- Add category
- Edit account
- Edit category
- Import Tabula Rasa CSV
- Profile-specific administration sections

Expanders may preserve dense pages without hiding required next steps.

### 23.3 Dialogs and popovers

Dialogs and popovers are not required by the current implementation.

They may be introduced only when they preserve all fields, warnings, and actions of the current workflow. Do not move long import previews, recovery summaries, or multi-part profile administration into cramped overlays.

### 23.4 Destructive confirmation

Current destructive workflows use explicit warnings and acknowledgement checkboxes or confirm/cancel controls.

A visual redesign may use a dialog only if it preserves the same consequence text and confirmation strength.

---

## 24. Empty, Loading, and Error States

### 24.1 Empty states

Empty states should explain:

- What is missing
- Why the page or scope is empty
- What action the user can take

Current examples include:

- No transactions yet; add the first one from Transactions.
- No mileage trips in this period.
- No activity in this report period.
- No cloud backup has been uploaded for this profile.
- No unreferenced receipts are available in Google Drive.
- No accounts in one balance-sheet classification.

Avoid decorative illustrations unless subtle and useful.

### 24.2 First-use states

When no profiles exist and local administration is available:

1. Open Account settings.
2. Re-enter the application password.
3. Add and validate the first business profile.
4. Allow workbook initialization and default account/category seeding.
5. Select the profile and begin normal bookkeeping.

Within a valid blank profile:

1. Review or add accounts and categories.
2. Add transactions or mileage.
3. Review Dashboard and Reports.
4. Configure Google Drive only when receipts or cloud backups are needed.

### 24.3 Loading states

Use:

- Progress indicators
- Clear processing text
- Disabled duplicate actions when appropriate

Avoid content jumping where practical.

Long backup, Drive, import, or validation actions should make it clear that work is in progress and should not encourage repeated submission.

### 24.4 Error states

Errors should state:

- What failed
- Whether data changed
- What the user should do next
- Whether retrying is safe

Do not expose raw stack traces, secrets, private keys, tokens, receipt contents, or private ledger data in the ordinary interface.

---

## 25. Receipts and Google Drive Files

Receipt management is part of the selected saved transaction's edit workflow.

### 25.1 Availability

When the selected profile does not have a configured Google Drive receipt folder:

- Show a clear informational message.
- Preserve the current manual filename guidance using the transaction ID.
- Do not display nonfunctional upload controls.

### 25.2 Linked receipt display

For each linked receipt, preserve:

- Recognizable stored filename
- Open-in-Google-Drive link
- Remove receipt action
- Explicit consequence text

Removing a receipt removes only the transaction's ledger reference. The file remains in Google Drive.

### 25.3 Remove-reference confirmation

The current flow requires:

1. Remove receipt request
2. Warning that the file remains in Google Drive
3. Cancel or Remove reference
4. Confirmed success notice

Do not describe this as deleting the receipt file.

### 25.4 Unreferenced receipt linking

When app-managed receipt files exist in the profile's receipt folder without a transaction reference, preserve:

- Unreferenced receipt selector
- Filename-based option labels
- Link selected receipt action
- Clear success or error result
- Warning when files require integrity metadata before linking

### 25.5 Post-creation receipt upload

The existing transaction editor remains the full receipt-management surface.

It must preserve:

- Supported file types: PDF, PNG, JPG, JPEG, WEBP, and HEIC
- Original filename preservation with safe sanitization
- Numeric suffixing for filename conflicts
- SHA-256 and integrity metadata behavior
- Upload and link confirmation
- Retry-safe handling of uncertain Drive responses
- Existing linked-receipt display and removal
- Linking of eligible unreferenced receipts

### 25.6 Receipt during transaction creation — current behavior

The Add transaction form includes an optional multi-file receipt uploader.

The user experiences one submission workflow, while the system performs ordered operations:

1. Validate the transaction and every selected file.
2. Save the transaction and obtain its stable ID.
3. Upload each receipt using that transaction ID.
4. Link each resulting receipt reference independently.

The notice should identify the saved transaction, the complete and unresolved
receipt counts, and the retry action without exposing internal secrets or Drive
metadata. Do not expose a pending/uploaded/linked/failed state machine or add
background progress stages.

The success notice is `Transaction saved and N receipt(s) linked.` when every
selected receipt is complete. A partial result keeps the transaction saved and
offers `Retry unresolved receipts`.

Partial failure rules follow Section 19.3. A receipt failure never converts a confirmed transaction save into a reported total failure.

The session retains only the saved transaction ID plus the minimum per-receipt
recovery pointers needed to retry. Successful links are never retried solely
because another selected receipt failed; an uploaded-but-unlinked file is
retried by reference rather than re-uploaded.

The post-creation editor remains available for later upload, retry, linking, opening, and unlinking.

### 25.7 Receipt integrity and backup interaction

The design must not weaken:

- Stable receipt identity
- Checksum metadata
- Legacy-reference initialization
- Intentionally empty reference handling
- Backup-time receipt preparation
- Unreferenced receipt inventory
- Independent receipt-byte recovery requirements

Receipt files are not embedded in each ledger backup ZIP.

A styling change must not imply that unlinking or deleting a transaction deletes the Drive file unless a separate feature explicitly implements and confirms that behavior.

---

## 26. Import Workflows

The Data & backup page contains three distinct import workflows. They must remain distinguishable.

### 26.1 Import Tabula Rasa CSV

Supported current behavior:

- CSV upload
- Required columns: Date, Type, Amount, Account, Category
- Optional displayed fields include Payee, Description, and Reference
- Type must be Income or Expense
- Preview of the first 20 rows
- Import rows action
- Storage-level validation and confirmed batch write

This workflow does not import transfers.

### 26.2 Import QuickBooks transactions

Supported sources:

- QuickBooks Online Transaction Detail by Account CSV
- QuickBooks Self-Employed General ledger XLSX
- ZIP containing exactly one supported XLSX workbook

The preview must preserve:

- Ready count
- Duplicate count
- Income count
- Expense count
- Transfer count
- Conversion errors
- Validation errors
- Duplicate row numbers
- Preview of up to 50 source rows
- Optional Automatically create missing accounts and categories control
- Explicit proposed account and category additions
- Import validated rows action disabled when blocking errors exist or no rows are ready

Duplicates are skipped. Valid rows are written in one batch after references are validated again.

### 26.3 Import QuickBooks mileage

The preview must preserve:

- Mileage ready count
- Mileage duplicate count
- Personal skipped count
- Unreviewed skipped count
- Validation errors
- Duplicate row numbers
- Personal row numbers
- Unreviewed row numbers
- Preview of up to 50 source rows
- Import validated mileage action disabled when blocking errors exist or no rows are ready

Only valid unique Business rows are written.

### 26.4 Shared import rules

- Previewing does not write ledger rows.
- Imports are scoped to the selected business profile.
- Validation output must be readable and actionable.
- A reported success means the batch write was confirmed.
- File parsing failures must not produce partial imports.
- Existing duplicate-detection behavior must remain intact.
- Import controls must not be collapsed into one ambiguous generic uploader.

### 26.5 Completion behavior

After a successful import, show the confirmed number of imported transactions or mileage trips.

A redesign may add navigation to the relevant ledger, but that is additive and must not replace the current success result.

---

## 27. Responsive Behavior

The application is desktop-first but must remain usable in narrower browser windows.

### 27.1 Breakpoint behavior

At approximately 760px or below:

- Multi-column forms stack vertically
- Metric cards wrap into one or two columns
- Dashboard sections stack by priority
- Sidebar navigation may collapse
- Tables may use horizontal scrolling
- Secondary actions may move below the primary action

### 27.2 Priority order on narrow screens

Preserve this order:

1. Page title and primary action
2. Primary financial summary
3. Attention-required items
4. Supporting metrics
5. Main table or chart
6. Secondary details

### 27.3 Tables

Do not hide important accounting columns solely to avoid horizontal scrolling.

Prefer:

- Horizontal table scrolling
- Shorter column labels
- Optional low-priority columns
- Row-detail view

### 27.4 Responsive acceptance criteria

- No controls overlap
- No page-level horizontal overflow except intentional table scrolling
- Primary actions remain visible
- Forms preserve logical order
- Semantic status remains readable
- Charts resize without clipped labels

---

## 28. Accessibility

All pages must support:

- Keyboard navigation
- Visible focus indicators
- Clear labels
- Sufficient contrast
- Non-color status indicators
- Descriptive button text
- Predictable control order
- Accessible error messaging

### 28.1 Contrast

Do not use muted gray for essential data.

### 28.2 Focus

Interactive elements must have a visible focus state using the focus token.

Do not remove browser focus outlines without an equivalent replacement.

### 28.3 Icons

Icons must not be the sole representation of:

- Delete
- Edit
- Warning
- Success
- Active/inactive or balanced/out-of-balance state
- Financial direction

### 28.4 Motion

Avoid non-essential animation.

Any necessary animation should be brief and must not be required to understand state.

---

## 29. Streamlit Component Mapping

Prefer these mappings:

| Design pattern | Current or preferred Streamlit implementation |
|---|---|
| Primary action | `st.button` or `st.form_submit_button` |
| Text field | `st.text_input` |
| Multi-line notes | `st.text_area` |
| Amount or mileage field | `st.number_input` |
| Date selector | `st.date_input` |
| Single selector | `st.selectbox` |
| Multiple account selector | `st.multiselect` |
| Transaction type choice | `st.segmented_control` |
| Boolean/confirmation | `st.checkbox` or `st.toggle` when semantically appropriate |
| File upload | `st.file_uploader` |
| Grouped submission | `st.form` |
| Read-only selectable table | `st.dataframe` with `on_select` |
| Ledger search | `st.text_input` with case-insensitive filtering |
| Edit/Bulk mode | `st.segmented_control` or `st.toggle` with explicit labels |
| Bulk row selection | `st.dataframe` with `selection_mode="multi-row"` in Bulk mode |
| Bulk action bar | `st.container(border=True)` shown only with a non-empty selection |
| Optional editable grid | `st.data_editor` only when a new editable-grid requirement exists |
| Tabs | `st.tabs` |
| Dense optional workflow | `st.expander` |
| Bordered workflow group | `st.container(border=True)` |
| Status feedback | `st.success`, `st.warning`, `st.error`, `st.info` |
| Metric | `st.metric` or approved custom presentation |
| Sidebar navigation | `st.radio` inside `st.sidebar` or an explicitly approved equivalent |
| Account settings sections | `st.tabs`, compact section navigation, or clearly separated expanders |
| Receipt link | `st.link_button` |
| CSV/ZIP export | `st.download_button` |
| Chart | `st.plotly_chart` or another approved native chart integration |
| Temporary progress | `st.progress`, `st.status`, or visible processing text |

Do not replace native controls with a custom component solely for styling.

---

## 30. Streamlit Implementation Constraints

### 30.1 Preferred implementation order

1. Native Streamlit layout
2. Streamlit theme configuration
3. Reusable Python UI helpers
4. Limited stable CSS
5. Streamlit Custom Component only when justified

### 30.2 CSS rules

CSS may be used for:

- Typography
- Spacing
- Surface colors
- Borders
- Radius
- Limited layout refinement
- Stable component-level styling

Avoid CSS that targets:

- Generated class names
- Unstable internal widget structure
- Positional selectors dependent on page order
- Deeply nested Streamlit DOM structure

The current shared shell implementation keeps these rules in
`tabula_rasa/presentation.py`. It uses the documented theme options in
`.streamlit/config.toml` plus stable `data-testid` hooks for the sidebar,
metrics, tables, alerts, widget labels, and focus treatment. The existing
widget-label and tooltip layout is part of the current behavior and must be
preserved when those hooks change in a future Streamlit release. The
`test_global_styles_use_stable_shell_hooks_and_accessible_states` regression
test is the compatibility guard for this CSS boundary.

The current visual-polish pass also gives the shell, Dashboard, Reports, and
Data & backup sections stable keyed-container hooks. These hooks provide
compact spacing, bounded working surfaces, and narrow-viewport stacking while
leaving native forms, expanders, tables, and tabs responsible for their own
interaction. Dashboard activity and balance tables flatten their inner table
borders inside one surrounding working surface; account and category
expanders likewise use one workflow border rather than nested cards. The
working area uses the stable `stMainBlockContainer` test ID for its responsive
padding; generated Streamlit class names and broad DOM selectors remain out
of scope.

### 30.3 Custom components

A custom component requires explicit justification.

Appropriate examples:

- Advanced transaction grid
- Specialized receipt or import review interface
- Specialized financial visualization
- Complex keyboard-oriented entry control

Do not create a custom component solely to change minor styling.

### 30.4 State management

UI state should be predictable.

- Filters should persist during ordinary navigation where practical
- Successful saves should clear or reset forms intentionally
- Failed saves should preserve entered data
- Dialog state should not reopen unexpectedly
- Page reruns must not silently change user selections
- Changing ledger filters or search must clear bulk selection before an action can run
- Switching between Edit and Bulk modes must clear incompatible table selection
- A partial receipt-on-create failure must retain the confirmed transaction ID and expose a retry path

---

## 31. Page Contracts

Each page contract defines the current required function and any approved target behavior, together with hierarchy, states, and acceptance criteria.

### 31.1 Authentication and global shell

#### Required behavior

- Require application-password authentication before ledger access.
- Display the business selector when profiles exist.
- Scope every operation to the selected profile.
- Display the workbook title on ordinary pages.
- Preserve the Log out action.
- Do not imply profile-level authorization; authenticated users can currently select every configured profile.

#### Acceptance criteria

- No ledger page is visible before authentication.
- Selected business and workbook context is discoverable.
- Logout remains available from every normal page.
- Account settings appears only under current local-administration safety conditions.

### 31.2 Dashboard

#### Purpose

Provide a current overview of balances and current-month activity.

#### Required content

- Total balance
- Income this month
- Expenses this month
- Net this month
- Recent activity table
- Account balances table

#### Behavior

- Use the latest confirmed Google Sheets state.
- Show up to the current recent-activity limit without changing data semantics.
- Display an explicit empty state directing the user to Transactions when no transactions exist.

#### Acceptance criteria

- All four metrics and both tables remain present.
- Expense signs in recent activity retain current display behavior.
- Account balance columns remain Account, Classification, Type, Balance.

### 31.3 Transactions

#### Purpose

Create income, expense, and transfer entries; optionally attach a receipt during creation; search, filter, and review the ledger; edit or delete saved entries; perform approved bulk actions; and manage receipts.

#### Required layout

```text
┌──────────────────────────────────────────────────────────────────┐
│ Transactions                                                     │
│ [Add transaction] [View & edit ledger]                           │
├──────────────────────────────────────────────────────────────────┤
│ Add tab: conditional transaction form + optional receipt          │
├──────────────────────────────────────────────────────────────────┤
│ Ledger tab: [From] [To] [Type]                                   │
│             [Accounts multiselect] [Search transactions]          │
│             [Edit mode | Bulk mode]                              │
│             [Bulk action bar when rows selected]                 │
│ Date | Type | Account | To account | Category | Payee | ...      │
│ Edit transaction expander                                        │
│ Receipt management                                                │
└──────────────────────────────────────────────────────────────────┘
```

#### Create behavior

Follow Sections 19.2, 19.3, and 25.6.

#### Ledger behavior

- Preserve From, To, Type, and Accounts filters.
- Provide the current Search transactions control according to Section 18.1.
- Preserve the exact current headers in Section 17.4.
- Default to latest dates first.
- Preserve interactive sorting across the two Transactions tabs.
- Reset to latest-date-first after navigating away and returning.
- Default to Edit mode with one selected row targeting the edit workflow.
- Provide an explicit Bulk mode with multi-row selection.

#### Bulk behavior

- Follow Section 17.7.
- Show selection count and only valid actions.
- Clear selection when filters, search, or mode changes.
- Revalidate the complete selection immediately before a write.
- Do not silently partially apply a bulk mutation.

#### Edit/delete behavior

- Preserve the current type-specific account/category fields.
- Preserve date, amount, payee, reference, and description editing.
- Preserve explicit permanent-deletion warning and acknowledgement.
- Preserve separate Save changes and Permanently delete actions.

#### Receipt behavior

Follow Section 25. Existing post-creation receipt management remains the recovery and maintenance surface even after receipt-on-create is implemented.

#### Acceptance criteria

- No current ledger column is omitted.
- Create, edit, single delete, search, bulk actions, and receipt operations are available.
- Receipt-on-create partial failures do not duplicate or silently discard records or files.
- Transfer constraints remain enforced.
- Historical inactive referenced accounts remain editable where currently supported.
- Search combines with structured filters and has a clear no-results state.
- Bulk mode cannot accidentally edit one row or operate on rows no longer in scope.
- Reconciliation and tags are not implied.

### 31.4 Mileage

#### Purpose

Record and maintain a dated business-mileage log.

#### Required layout and behavior

- Tabs: Add trip; View & edit mileage log
- Add fields specified in Section 19.7
- Round trip creates two reversed-location entries in one confirmed write
- Log filters: From and To
- Metrics: Trips and Business miles
- Download filtered mileage CSV
- Table headers specified in Section 17.6
- Single-row selection
- Edit mileage trip expander
- Edit all stored mileage fields
- Explicit permanent-delete warning and acknowledgement

The current presentation uses compact two-column groupings for related Add trip
inputs (Trip date/Vehicle, Business miles/Round trip, and Starting
location/Destination). The log keeps From and To above the Trips and Business
miles metrics, then the secondary filtered CSV action, the complete eight-column
table, and the Edit mileage trip section. The table may scroll horizontally on
narrow viewports; no mileage field or schema column is omitted.

#### Acceptance criteria

- Round-trip explanatory help remains available.
- The entered mileage is treated as one-direction mileage for each created row.
- Filtered metrics, table, and CSV use the same date scope.
- Create, edit, delete, and export remain available.

### 31.5 Accounts

#### Purpose

Maintain balance-sheet accounts, hierarchy, opening balances, active state, and calculated balances.

#### Required table

- Account
- Layer
- Parent
- Classification
- Type
- Active
- Balance
- Transaction count

#### Add account fields

- Account name
- Type: Bank, Cash, Credit card, Short-term debt, Equity, Other
- Balance-sheet classification
- Opening balance
- Parent account (optional)

#### Hierarchy rules

- Layer 2 parent must share the same classification.
- Fixed account types retain their normal classification.
- A Layer 1 account with children cannot be moved under another parent until children are promoted or reparented.
- Parent rows display rolled-up balance and transaction count.
- Child rows display direct values.

#### Edit behavior

Preserve editing of:

- Name
- Type
- Classification
- Opening balance
- Active state
- Parent account

Accounts are deactivated rather than deleted so historical transaction references remain valid.

#### Acceptance criteria

- No Delete account action is introduced without a storage-model change.
- Active and inactive states remain explicit.
- Liability and equity opening-balance guidance remains visible.
- Stable IDs and transaction references survive rename, promotion, and reparenting.

### 31.6 Categories

#### Purpose

Maintain Income and Expense categories and their two-layer hierarchy.

#### Required table

- Category
- Layer
- Parent
- Type
- Transaction count

#### Add/edit fields

- Category name
- Type: Expense or Income
- Parent category (optional)

#### Rules

- A child must use a parent of the same type.
- A parent with children cannot itself be moved under another parent until its children are promoted or reparented.
- Renaming, promotion, or reparenting preserves the stable category ID.
- A category may be permanently deleted only when it has no transactions and no child categories.

#### Acceptance criteria

- Add, edit, and eligible permanent delete remain available.
- Deletion consequence acknowledgement remains explicit.
- Category paths remain available in transaction selectors and reports.

### 31.7 Reports

#### Purpose

Provide current income-and-expense analytics and a balance sheet.

#### Current period controls

- From
- To
- Balance-sheet As of date

#### Current income-and-expense content

- Income metric
- Expenses metric
- Net metric
- Monthly performance grouped bar chart
- Expenses by category horizontal bar chart
- Category detail table with Category, Layer, Parent, Direct activity, and Layer 1 total

#### Current balance-sheet content

- Total assets
- Total liabilities
- Total equity
- Assets table
- Liabilities table
- Equity table including Current earnings
- Balanced success or out-of-balance warning with the difference
- Guidance that liabilities and equity are presented conventionally positive while opening ledger balances are entered negative

#### Current presentation hierarchy

Reports present the period controls first, followed by the income-and-expense
summary, its supporting charts, the category detail table, and then the separate
balance sheet. The balance-sheet **As of** date remains independent from the
income-and-expense **From**/**To** range.

Metrics use compact grouped columns. Charts remain subordinate to the values:
monthly performance uses grouped bars with currency axes, while expenses by
category uses a horizontal ranking bar with Layer 1 rollup totals. The palette
uses the shared blue interaction color and a related muted blue series; color is
not the sole indicator of financial or balance-sheet state.

The page explicitly communicates empty activity, empty expense results, empty
statement groups, storage errors, and balanced or out-of-balance status. The
status text remains meaningful without relying on success or warning color.

#### Acceptance criteria

- All current metrics, charts, detail tables, and balance-sheet sections remain present.
- Layer 1 totals and Direct activity remain explainable without double counting.
- No unsupported cash-flow, transaction-detail, or reconciliation report is presented as current.
- Empty periods and empty statement groups render safely.

### 31.8 Data & backup

#### Purpose

Provide cloud backup controls, recovery-configuration visibility, live exports, and imports.

#### Current page order and action hierarchy

The current page groups its workflows in this order:

1. **Cloud backup** — Google Drive destination status, upload, and read-only verification.
2. **Recovery status** — local Synology metadata and its saved operational expectations.
3. **Exports** — one explicit prepare/refresh action followed by the available downloads.
4. **Imports** — three separate uploaders and previews, each with its own explicit write action.

Each workflow keeps one dominant action visible while retaining its warnings,
diagnostics, and secondary controls. The page-generated transaction, mileage,
manual complete-backup downloads, and cloud-managed backups all use the
canonical `tabula-rasa` filename prefix.

#### Google Drive backup section

Preserve:

- Not-configured guidance
- Configured destination name
- Latest app-managed backup name and creation time when available
- No-backup warning
- Upload fresh backup now
- Verify latest cloud backup
- Explanation that verification does not restore or modify the live workbook
- Validated backup creation and hash verification behavior

#### Synology recovery-copy section

Preserve:

- Optional/not-enabled guidance
- Configuration validation errors
- Warnings when Drive backup or receipt folders are missing
- Ledger backup source
- Receipt source
- Required sync direction
- Destination-deletion rule
- NAS destination
- Schedule
- Retention policy
- Explicit statement that Tabula Rasa does not connect to DSM or prove sync success

Synology/NAS values are local operational metadata. When the selected runtime
does not contain a local record, including the hosted projection, show that the
settings are intentionally unavailable and direct the administrator to the
loopback-only profile page and DSM. Do not infer or report NAS status from an
absent hosted field.

#### Live workbook exports

Preserve the Prepare or Refresh downloadable exports workflow.

After preparation, provide:

- Transactions CSV
- Mileage CSV
- Complete workbook backup ZIP when receipt preparation succeeds
- Preparation timestamp
- Warning explaining why the complete backup is unavailable when CSV exports remain available

#### Imports

Preserve all three import workflows in Section 26.

#### Acceptance criteria

- Cloud upload, cloud verification, exports, complete backup, plain CSV import, QuickBooks transaction import, and QuickBooks mileage import remain available.
- Backup verification never implies restoration.
- CSV exports remain available without Drive connection.
- Complete current-format backup remains dependent on a valid receipt-folder inventory.
- No local Google Drive Desktop dependency is implied for cloud-native backup mode.

### 31.9 Account settings

#### Purpose

Present the current local Business profiles administration as a familiar **Account settings** destination while preserving all profile, credential, Drive, storage, and recovery functions.

The page is an application-settings surface, not a bookkeeping workspace and not a per-user identity-management page.

#### Navigation and availability

- Display `Account settings` in the sidebar utility area, visually separated from operational pages.
- The current route label is `Account settings`.
- The page remains available only when the local-administration environment flag and loopback binding permit it.
- Require re-entry of the application password before configuration changes.
- Do not expose writable profile configuration in hosted environments where the current safety checks disable it.

#### Recommended information architecture

Use compact settings navigation or tabs:

1. **Business profiles**
2. **Google Drive storage**
3. **Recovery**
4. **Security & deployment information**

The last section is informational unless an implementation task adds supported controls.

#### Business profiles section

**Current guided behavior:** When no local profile exists, Account settings
leads with profile creation and does not render unrelated Drive or Synology
configuration. The administrator reviews an editable safe key derived from the
business name before the first save. After saving, one selected profile drives
the Sheets, local-backup, Drive, Synology, and readiness sections in dependency
order. Readiness reports incomplete, ready-local, or ready-hosted status and
uses fresh workbook and configured Drive destination reads without displaying
credential, token, ledger, or receipt contents.

Preserve the summary table fields:

- Profile key
- Business
- Masked spreadsheet identifier
- Local backup folder
- Service account email
- Drive OAuth state/account
- Synology recovery state/destination
- Configuration source

Preserve Add local profile:

- Business name
- Immutable safe profile key
- Google Sheets URL or spreadsheet ID
- Optional local backup folder path
- Google service-account JSON upload
- Validate and save
- Workbook validation, required-sheet initialization, and default seeding before save

Preserve Edit local profile:

- Business name
- Spreadsheet setting
- Optional local backup folder
- Validate and save settings
- Separate replacement credential upload
- Separate Validate and rotate credential action
- Failure behavior that leaves the prior profile intact

#### Google Drive storage section

Preserve profile-scoped controls for:

- Connect or reconnect Google Drive
- Disconnect the grant without deleting Drive files
- Select an existing storage root or create an app-managed root
- Provision or reuse Receipts and Ledger Backups child folders
- Display the authorized account and configured destinations

**Current behavior:** Profile readiness revalidates the selected root and its
managed children without opening ordinary Drive parent folders. It still
compares returned direct-parent IDs with known profile roots. Full cross-profile
root ancestry remains a dedicated Drive root-selection, creation, and
reconnection guard for recursive recovery safety.

#### Recovery section

Preserve Synology configuration:

- Enable/disable choice
- Canonical profile-root Cloud Sync task summary
- NAS destination path
- Cloud Sync schedule
- Retention policy
- Required download-only and destination-deletions-disabled guidance

**Current behavior:** New opt-ins default to one recursive Cloud Sync task whose
remote source is the selected profile storage root. Its NAS destination is
derived from the local app-wide NAS base path plus the immutable profile key, so a
global default never sends two profiles to the same destination. App-wide
schedule and retention defaults prefill the form and remain editable before
save. A saved per-profile value is the operational record; the app does not
configure or observe DSM.

Saving Synology destination, schedule, or retention metadata is a local-only
operation. The canonical layout field is stored automatically. Saving must not
access Google Drive or revalidate Drive ancestry; Drive root and managed-child
validation remains in the dedicated Google Drive settings workflow.

Enabled records always use `layout = "profile-root"`. The administrator has no
layout selector. The Data & backup summary shows the profile storage root as the
remote source and `Receipts` and `Ledger Backups` as the expected child folders.
Equivalent, shared, or nested normalized DSM destinations across profiles are
rejected.

All app-wide and per-profile Synology fields remain outside the hosted profile
projection. Changing only these fields must not change generated hosted Secrets
or require hosted redeployment.

Also preserve clear links or references to the maintained backup, restore, and receipt-recovery documentation without implying that Account settings performs restore or DSM monitoring.

#### Security & deployment information

Explain clearly:

- The application password currently grants access to every configured business profile.
- Profile keys are configuration identifiers, not user accounts.
- Local profile configuration is stored in the ignored plaintext profile file and depends on operating-system protections.
- Hosted-runtime configuration changes require the documented Streamlit Secrets export and replacement process.
- Local backup paths and Synology operational settings do not require a hosted export.
- Private keys are never displayed after upload.

The hosted exporter uses an explicit profile allowlist: display name,
spreadsheet ID, Sheets service-account credential, and validated Google Drive
authorization with its storage root and receipt/backup children. It excludes
local backup paths, Synology metadata, and unknown future local-operation
fields. Existing hosted documents with older extra fields remain readable, but
new exports omit them.

#### Acceptance criteria

- Every current Business profiles function remains available under Account settings.
- The page visually reads as settings rather than an operational ledger page.
- Private keys are never displayed after upload.
- Hosted/Secrets-sourced profiles remain visibly read-only in local administration where applicable.
- Profile keys remain immutable.
- Drive and Synology settings are preserved unless their dedicated controls change them.
- Successful changes to hosted-runtime fields remain followed by the documented hosted-Secrets export step outside this UI.
- Local-only backup and Synology changes leave the hosted projection unchanged.
- The page does not imply per-profile user permissions, DSM monitoring, or in-app restore.

## 32. Component Contracts

### 32.1 Date control

- Use an explicit label such as From, To, Date, Trip date, or As of.
- Preserve the scope associated with the control.
- Do not combine the Reports As of date with the P&L period range.

### 32.2 Hierarchical account selector

- Display the full hierarchy path where current code does so.
- Preserve stable ID values behind labels.
- Include inactive accounts only in historical edit contexts where currently supported.
- Transfer destination must exclude or reject the selected source account.

### 32.3 Hierarchical category selector

- Display the full hierarchy path.
- Restrict options to the selected transaction or category type.
- Preserve stable IDs behind labels.

### 32.4 Currency input and output

- Use two decimal places.
- Use a minimum of 0.01 for current transaction entry.
- Right-align comparable displayed values.
- Preserve current negative-sign semantics for stored liability/equity opening balances.

### 32.5 Selectable data table

- Use a clear selected-row state.
- Preserve the mapping from displayed row to stable record ID.
- Keep the explicit selectbox inside edit expanders as a reliable alternative.
- Do not introduce multi-row selection without a corresponding product feature.

### 32.6 Permanent-delete confirmation

The confirmation must state:

- The exact record type
- That deletion is permanent
- That the action cannot be undone

Require the current acknowledgement control before enabling or processing the destructive action.

### 32.7 Receipt reference removal

State that the transaction reference is removed and the Google Drive file remains.

Provide explicit Cancel and Remove reference actions after the initial request.

### 32.8 File upload

- Show accepted file types.
- Preserve input after non-write validation errors where practical.
- Distinguish parsing failure, validation failure, Drive upload failure, and ledger-link failure.
- Never expose file contents or secrets in diagnostics.

### 32.9 Prepared export state

- Do not generate large export payloads repeatedly on every rerun.
- Display the preparation timestamp.
- Change Prepare downloadable exports to Refresh downloadable exports when a prepared set exists.
- Invalidate or separate prepared exports after confirmed workbook writes.

### 32.10 Ledger search (current behavior)

- Label: `Search transactions`.
- Use case-insensitive substring matching over the fields defined in Section 18.1.
- Show result count and a clear action.
- Search combines with structured filters.
- Search must have a distinct no-results state.
- Search changes clear bulk selection.
- Empty or whitespace-only search is a no-op.
- Search state persists between the two Transactions tabs and resets when the Transactions table-generation boundary is recreated after leaving the page.

### 32.11 Bulk action bar

- Hidden when Bulk mode has no selection.
- Shows selected-row count.
- Shows only actions valid for the complete selection.
- Uses one visually dominant action only when a mutation is being confirmed.
- Export remains visually secondary because it is non-destructive.
- Category change and delete must show a review summary before write.

### 32.12 Receipt-on-create progress

- Treat transaction save, receipt upload, and receipt linking as ordered stages.
- Never report the transaction as unsaved after Sheets confirms it.
- On partial failure, show the saved transaction identifier and a retry path.
- Do not reset the form until the full selected workflow completes.

### 32.13 Success notice

Use short confirmed messages such as:

- Transaction saved.
- Transaction saved and receipt linked.
- Category updated for 12 transactions.
- Exported 8 selected transactions.
- Permanently deleted 3 transactions; linked Drive files were retained.
- Mileage trip updated.
- Category deleted.
- Imported 24 transactions.
- Latest cloud backup downloaded and verified.

Do not show success before the relevant Google API or storage operation confirms completion.

## 33. Text-Only Design Review Method

Screenshots are not required as inputs.

For each page, Codex should review the implementation against:

1. Purpose
2. Content hierarchy
3. ASCII wireframe
4. Component contracts
5. Responsive rules
6. Acceptance criteria

### 33.1 Written review questions

- Is the most important information visually dominant?
- Is each workflow section's primary action obvious?
- Is any component over-spaced?
- Are semantic colors used consistently?
- Are tables compact and aligned?
- Are all important states, warnings, and actions visible without hover?
- Is the page understandable without decorative graphics?
- Does the narrow layout preserve the intended priority order?

### 33.2 Optional generated screenshots

Codex may capture screenshots of the running application for self-review, but no external reference screenshot is required.

The captured image is evidence of the implementation, not the design specification.

---

## 34. Visual and Functional Verification

Every material UI change must be visually and functionally verified.

### 34.1 Required viewport checks

Test at approximately:

```text
1440 × 1000
1200 × 900
900 × 900
390 × 844
```

The mobile-width check is for narrow-browser resilience, not a mobile-first redesign.

### 34.2 Visual verification checklist

Confirm:

- Page hierarchy is clear
- No marketing-style spacing was introduced
- Tables remain readable
- Amount and balance columns align correctly
- Semantic colors are consistent
- Color is not the sole state indicator
- Forms preserve logical tab order
- Narrow layouts stack correctly
- No unintended full-page horizontal overflow exists
- Charts remain readable
- Empty and error states are present
- The active business and workbook remain discoverable

### 34.3 Required functional regression matrix

Authentication and shell:

- Sign in
- Select business
- Navigate all current pages
- Log out
- Confirm conditional Account settings availability and utility-area placement

Transactions:

- Create Income without a receipt
- Create Expense with a receipt
- Create Transfer with and without a receipt
- Confirm invalid transaction data prevents receipt upload
- Confirm transaction-save failure prevents receipt upload
- Confirm receipt-upload failure retains the saved transaction and exposes retry
- Confirm upload/link failure leaves the file recoverable without duplicate upload
- Filter by dates, type, and accounts
- Search each supported text field and transaction ID
- Clear search and verify structured filters remain
- Verify explicit no-results state
- Use Edit mode to select and edit one row
- Switch to Bulk mode and select multiple rows
- Export selected rows
- Change category for a valid homogeneous selection
- Confirm invalid mixed or transfer selection disables category change
- Permanently delete selected rows with confirmation and receipt-file warning
- Confirm filter/search/mode changes clear bulk selection
- Edit each transaction type
- Permanently delete one transaction with confirmation
- Open linked receipt
- Remove receipt reference
- Link unreferenced receipt
- Upload and link receipt from the editor

Mileage:

- Create one-way trip
- Create round trip as two entries
- Filter by dates
- Verify metrics
- Download filtered CSV
- Edit trip
- Permanently delete trip

Accounts:

- Add each relevant account type
- Add Layer 2 account
- Edit account fields
- Activate/deactivate
- Promote or reparent where valid
- Verify rollup balances and counts

Categories:

- Add Income and Expense category
- Add Layer 2 category
- Edit, promote, or reparent
- Delete eligible category
- Confirm blocked deletion for referenced or parent categories

Reports:

- Change From and To dates
- Verify metrics and charts
- Verify category rollups
- Change balance-sheet As of date
- Verify balanced and out-of-balance states

Data & backup:

- View configured and unconfigured Drive states
- Upload fresh cloud backup
- Verify latest cloud backup
- View Synology configuration and warnings
- Prepare/refresh exports
- Download transactions CSV
- Download mileage CSV
- Download complete backup when available
- Verify complete-backup failure leaves CSV exports available
- Import Tabula Rasa CSV
- Preview/import QuickBooks transactions
- Exercise optional auto-create
- Preview/import QuickBooks mileage

Account settings when locally enabled:

- Re-authenticate administration
- Add and validate profile
- Edit profile settings
- Rotate credential
- Connect/reconnect/disconnect Drive
- Select/create storage root and provision child folders
- Enable/disable and edit Synology metadata

### 34.4 Data-integrity checks

- No visual change alters Google Sheets schema or record IDs unintentionally.
- No current field is omitted from create, edit, export, import, or table display.
- No action reports success before confirmation.
- Profile scope remains isolated.
- Duplicate-submission protection remains active.
- Backup and receipt integrity behavior remains intact.
- Receipt-on-create failures never duplicate or silently delete a confirmed transaction or Drive file.
- Bulk mutations revalidate the complete visible selection and do not silently partially apply.
- Search and bulk selection remain scoped to the active business and current structured filters.

---

## 35. Codex Instructions

Before implementing a user-interface change, Codex must:

1. Read this document in full.
2. Inspect the current implementation in `tabula_rasa/app.py` and any delegated UI module.
3. Read the maintained guide relevant to the page being changed.
4. Identify every current control, field, table column, state, warning, and action in scope.
5. Produce a preservation checklist before restructuring the page.
6. Preserve business logic, storage behavior, record IDs, and profile scoping.
7. Prefer native Streamlit components.
8. Avoid introducing new design tokens without approval.
9. Implement one coherent visual change at a time.
10. Run the application.
11. Inspect the affected page at the required viewports.
12. Execute the relevant functional regression checks in Section 34.
13. Document any intentional product-level deviation.

### 35.1 No-function-loss rule

Codex must not remove or make inaccessible an existing function merely because it is absent from a visual reference, seems advanced, or complicates the layout.

This includes:

- Conditional controls
- Local-only administration
- Validation and error output
- Help text that explains financial or recovery semantics
- Receipt integrity behavior
- Backup verification
- Import diagnostics
- Hierarchy constraints
- Destructive confirmations
- Exports

When a cleaner design requires moving a function, Codex must identify its new location and verify discoverability.

### 35.2 Current-versus-target feature rule

This document contains both current baseline requirements and approved target behavior.

Codex must not present a target behavior as completed until its code, storage operation, error handling, and tests are implemented together.

Approved target behavior includes:

- Receipt upload during transaction creation
- Explicit bulk ledger mode and the approved bulk actions
- Account settings information architecture and route label

Transaction search is now current behavior: its implementation, state boundary,
selection repair, failure/empty states, tests, and user documentation are part of
the functional baseline.

Until each target is fully implemented, preserve the current workflow and identify the feature as incomplete rather than removing the current path.

Still unsupported and prohibited unless separately approved:

- Reconciliation workflows or status
- Transaction tags
- Bulk edits beyond the actions in Section 17.7
- Receipt-content search
- Cash-flow or reconciliation reports
- Per-profile user authorization

A partial implementation must not leave dead controls, fictional success states, or a design path that excludes the current function.

### 35.3 Required implementation summary

For material UI changes, Codex should report:

- Pages changed
- Current functions inventoried
- Components moved or restyled
- Design rules applied
- Functional regression checks completed
- Any remaining limitations or intentional deviations

---

## 36. Prohibited Patterns

Do not introduce:

- Marketing hero sections
- Extremely large headings
- Excessive whitespace
- Glassmorphism
- Gradient backgrounds
- Neon accents
- Decorative animations
- Oversized pill buttons
- Rounded cards for every content block
- Shadows on every surface
- Hover-only actions
- Equal-card dashboard grids by default
- Unexplained icon-only controls
- Colorful charts without semantic purpose
- Custom frontend components where native Streamlit is sufficient
- Hidden critical errors
- Generic confirmation language
- Irreversible actions without explicit confirmation

---

## 37. Initial Design Direction Summary

Project Tabula Rasa uses:

- A warm off-white application canvas
- White analytical and data surfaces
- Compact operational spacing
- Attio-inspired controls and navigation
- Seline-inspired dashboard composition
- Blue as the default interaction color
- Green for positive and completed states
- Red for negative, failed, and destructive states
- Amber for warnings and unresolved items
- Thin borders instead of frequent shadows
- Asymmetrical dashboard layouts
- Tables as primary work surfaces
- Charts as restrained analytical support
- Native Streamlit components wherever practical
- Optional receipt upload as part of transaction creation, with ordered partial-failure handling
- Additive transaction search over existing structured filters
- Explicit Edit and Bulk ledger modes
- Conservative bulk actions: export selected, compatible category change, and confirmed permanent deletion
- Account settings as the familiar home for business-profile, Google Drive, credential, and recovery configuration
- No reconciliation workflow

The intended result is a bookkeeping application that feels composed, credible, efficient, and purpose-built for financial work without sacrificing any current operational or recovery capability.
