# Isolated Streamlit smoke fixture

This directory contains a reusable local browser-smoke fixture for issue #87
and later shell/layout checks. It runs the real application against a fake
workbook and a fake business profile, so it does not call Google Sheets or
Google Drive and does not use the repository's real local profile data.

From the repository root, run the explicitly invoked viewport smoke check with:

```powershell
python scripts\smoke_transactions.py
```

The runner starts the real Streamlit entrypoint in this directory, opens the
Transactions route after authentication, and uses
Playwright-managed Chromium at 1440x1000, 1200x900, 900x900, and 390x844, and
checks the Transactions > Add transaction renderer for its key controls and
page-level horizontal overflow. It exits non-zero with the viewport and failed
condition when a check fails. Optional diagnostic screenshots can be retained
with:

```powershell
python scripts\smoke_transactions.py --screenshots-dir .smoke_local\artifacts
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
