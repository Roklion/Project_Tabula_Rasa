# Isolated Streamlit smoke fixture

This directory contains a reusable local browser-smoke fixture for shell and
layout checks. It runs the real application against a fake
workbook and a fake business profile, so it does not call Google Sheets or
Google Drive and does not use the repository's real local profile data.

The credential-shaped values in `.streamlit/secrets.toml` and
`.streamlit/business_profiles.json` are an explicit test-only fixture
exception. They are synthetic values with no access to any Google project,
Drive account, ledger, or deployment; the documented fixture password is also
intentionally public. No real credentials may be copied into `.smoke_local`.
Never replace these values with real credentials or reuse them outside this
isolated fixture.

From the repository root, run the explicitly invoked viewport smoke check with:

```powershell
python scripts\smoke_transactions.py
```

The runner starts the real Streamlit entrypoint in this directory, opens the
Transactions route after authentication, and uses
Playwright-managed Chromium at 1440x1000, 1200x900, 900x900, and 390x844, and
checks the Transactions workflows for key controls and page-level horizontal
overflow. It exits non-zero with the viewport and failed
condition when a check fails. The requested loopback port must be unused, and
the runner verifies that this fixture's checked-in Streamlit theme still
matches the production `.streamlit/config.toml` before launch. Optional
diagnostic screenshots can be retained with:

```powershell
python scripts\smoke_transactions.py --screenshots-dir .smoke_local\artifacts
```

The Assets page has a separate check using the same four viewports and fixture:

```powershell
python scripts\smoke_assets.py
```

Install the development dependencies and the local Chromium browser once per
environment:

```powershell
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

The fixture password is `test-password-123`. Use it only with this isolated
fixture. The application routes are available with the loopback-only profile
administrator enabled; the workbook is an empty `Test Ledger`. The smoke check
does not create transactions or exercise receipt upload/recovery behavior; the
existing AppTest coverage remains the behavioral contract for that workflow.
