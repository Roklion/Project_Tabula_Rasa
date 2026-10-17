"""Container entry point: one worker, no header trust, access logs or migrations."""

import os

import uvicorn


def main():
    try:
        port = int(os.environ.get("PORT", "10000"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise SystemExit("Invalid HTTP port.") from None
    from tabula_rasa.telemetry import configure_console
    configure_console()
    uvicorn.run("tabula_rasa.http.app:create_app", factory=True, host="0.0.0.0", port=port,
                workers=1, proxy_headers=False, access_log=False)


if __name__ == "__main__":
    main()
