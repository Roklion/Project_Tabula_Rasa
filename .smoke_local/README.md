# Isolated Streamlit smoke fixture

This directory contains a reusable local browser-smoke fixture for issue #87
and later shell/layout checks. It runs the real application against a fake
workbook and a fake business profile, so it does not call Google Sheets or
Google Drive and does not use the repository's real local profile data.

From the repository root, start it with:

```powershell
$env:TABULA_LOCAL_PROFILE_ADMIN = '1'
.\.venv\Scripts\python.exe -m streamlit run .smoke_local\smoke_app.py `
  --server.address 127.0.0.1 --server.port 8501 --server.headless true
```

The fixture password is `test-password-123`. Use it only with this isolated
fixture. The application routes are available with the loopback-only profile
administrator enabled; the workbook is an empty `Test Ledger`.
