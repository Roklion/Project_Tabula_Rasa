"""Real browser -> gated API -> persistent synthetic PostgreSQL smoke; no writes."""


def smoke(origin, username, password, release):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            anonymous = browser.new_context(base_url=origin)
            for path in ("/accounts", "/api/v1/session", "/api/openapi.json"):
                response = anonymous.request.get(path, headers={"Accept": "text/html"})
                if response.status != 401:
                    raise ValueError("Alpha access restriction failed.")
            if anonymous.request.get("/health/ready").status != 200:
                raise ValueError("Readiness failed.")
            if anonymous.request.get("/version").json() != {"release": release}:
                raise ValueError("Release identity mismatch.")
            anonymous.close()
            context = browser.new_context(base_url=origin, http_credentials={"username": username, "password": password})
            session = context.request.get("/api/v1/session").json()
            if session.get("entity", {}).get("id") != "alpha-synthetic" or not session.get("trusted_development"):
                raise ValueError("Synthetic deployment context mismatch.")
            if context.request.get("/api/v1/entities/another/accounts").status != 403:
                raise ValueError("Fixed entity isolation failed.")
            for path in ("/api/v1/unknown", "/assets/missing.js"):
                if context.request.get(path, headers={"Accept": "text/html"}).status != 404:
                    raise ValueError("Routing failure.")
            page = context.new_page()
            page.goto("/accounts")
            expect(page.get_by_role("heading", name="Accounts", exact=True)).to_be_visible()
            expect(page.get_by_role("rowheader", name="Deployment connectivity", exact=True)).to_be_visible()
            context.close()
        finally:
            browser.close()


if __name__ == "__main__":
    import argparse
    import os
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True)
    args = parser.parse_args()
    try:
        if os.environ.get("TABULA_RASA_ENVIRONMENT") not in {"development", "staging"}:
            raise ValueError
        origin = os.environ["TABULA_RASA_PUBLIC_ORIGIN"]
        if not origin.startswith("https://"):
            raise ValueError
        smoke(origin, os.environ["TABULA_RASA_ALPHA_USERNAME"], os.environ["TABULA_RASA_ALPHA_PASSWORD"], args.release)
    except Exception:
        raise SystemExit("Deployment browser smoke failed; inspect routing, access, release and synthetic fixture.") from None
    print("Deployment browser smoke passed.")
