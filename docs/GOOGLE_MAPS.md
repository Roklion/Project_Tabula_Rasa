# Google Maps mileage setup

Google address suggestions and route mileage are optional, app-wide features.
They are deliberately separate from each business profile's Sheets service
account and human Drive OAuth grant. When Maps is not configured or Google is
unavailable, Mileage continues to accept manual addresses and miles.

This setup creates paid Google Maps Platform access. Complete the quota and
budget steps before a live request. Pricing and product limits change; confirm
the current values in Google Cloud rather than relying on a price copied into
this repository.

## Operator checklist

1. Create or select a Google Cloud project dedicated to this deployment's Maps
   usage. A dedicated project makes its keys, quota, and billing easier to
   isolate from Sheets and Drive.
2. Link the project to the intended Cloud Billing account.
3. Enable **Maps JavaScript API**, **Places API (New)**, and **Routes API**.
   Do not enable legacy Directions or Distance Matrix APIs for this feature.
4. Create a browser API key for address autocomplete:
   - Application restriction: **Websites**.
   - Hosted referrer: the exact deployed origin, for example
     `https://tabula-rasa.streamlit.app/*`.
   - Local referrers, on a separate development key where practical:
     `http://localhost:8501/*` and `http://127.0.0.1:8501/*`. Add another exact
     port only when local Streamlit uses it.
   - API restrictions: **Maps JavaScript API** and **Places API (New)** only.
5. Create a different server API key for route calculation:
   - API restriction: **Routes API** only.
   - Add an IP-address application restriction when the deployment has a
     documented stable outbound IP.
   - Streamlit Community Cloud does not document a stable application egress
     address. If the actual host cannot guarantee one, use the Routes-only API
     restriction, a dedicated key/project, conservative quotas, and monitoring.
     A deployment policy that requires an IP-restricted server key needs a host
     or proxy with stable egress before rollout.
   - Never put this server key in browser component data or source control.
6. In **Google Maps Platform > Quotas**, lower the available quotas before live
   testing. A conservative single-operator starting point is 10 Compute Routes
   requests per minute and 100 per day when a daily control is available. Start
   browser/Places request quotas at 60 per minute, then raise them only from
   observed legitimate use. A one-way calculation consumes one Routes request;
   a round trip consumes two because each direction is calculated separately.
7. In **Billing > Budgets & alerts**, create a project-scoped monthly budget.
   For a controlled single-user rollout, `$10 USD` with actual-spend alerts at
   50%, 90%, and 100%, plus a 100% forecast alert, is a reasonable starting
   point; replace it with the maximum amount the operator is actually willing
   to spend. Include an actively monitored email notification channel.
8. Remember that ordinary budget alerts do not stop usage and cost reporting
   can be delayed. The lowered API quotas are the operational guardrail. If the
   billing console offers an enforceable spend-cap budget for this project,
   review its current supported-services behavior before relying on it.
9. Add the two deployment-specific keys to ignored Streamlit Secrets, restart
   local Streamlit, and separately update the hosted Secrets store.
10. Before public deployment, review the checked-in [Terms of Use](TERMS_OF_USE.md)
    and [Privacy Policy](PRIVACY_POLICY.md). The application footer exposes both
    documents without requiring the application password. Confirm they still
    satisfy the current Routes API policy and reference Google's terms and
    privacy policy as required. Keep the visible Google Maps attribution beside
    Google-derived suggestions and route mileage.
11. Perform one controlled live validation, then inspect key usage, API metrics,
    quota consumption, and billing. Rotate or disable any unused test key.

## Streamlit Secrets

Add this application-wide table to ignored `.streamlit/secrets.toml`:

```toml
[google_maps]
browser_api_key = "RESTRICTED_BROWSER_KEY"
routes_api_key = "RESTRICTED_SERVER_KEY"
routes_timeout_seconds = 15
# Optional two-letter region restriction, for example "us".
autocomplete_region_code = "us"
```

Omit `autocomplete_region_code` when the deployment has no clear country rule.
Do not copy Maps keys into a `business_profiles` entry. The local hosted-Secrets
export preserves the app-wide `google_maps` table; regenerate the complete
export with:

```powershell
python scripts\export_streamlit_secrets.py
```

Paste the generated document into Streamlit App settings > Secrets, save it,
delete the generated file, and validate the deployed app. Local Secrets do not
automatically update the hosted store.

## Controlled validation

1. Open Mileage > Add trip and confirm manual address/mileage entry still works.
2. Select two Google suggestions and choose **Calculate mileage**. Confirm the
   business-miles field is populated, remains editable, and shows one decimal
   place; for a round trip, confirm the return-mileage field behaves the same.
3. Change an endpoint and confirm the previous suggestion becomes stale and is
   not silently reused.
4. Select **Round trip**, calculate, and confirm two route requests are recorded
   and outbound/return miles can differ before one save.
5. Temporarily use an invalid test key or an exhausted test quota and confirm the
   app gives a safe error while manual entry remains available. Restore the
   valid restricted key immediately afterward.
6. Inspect Google Maps Platform metrics and Billing reports after reporting has
   caught up. Confirm only the expected APIs and keys appear.

Automated tests always mock Google and must never use either live key.

## Policy and operations notes

- The application requests only the primary driving route's distance in meters,
  converts using `meters / 1609.344`, and rounds the editable suggestion to one
  decimal place.
- Calculate/Recalculate is explicit. Ordinary Streamlit reruns do not make a
  route request.
- The autocomplete widget manages its own prediction session. The application
  does not create a second session-token system.
- The ledger stores the existing user-authored or user-confirmed location and
  mileage fields. It does not store autocomplete display content, complete
  Places or Routes responses, route polylines, or a durable round-trip link.
- Browser keys are visible to browsers by design and therefore depend on
  website plus API restrictions. Server keys remain in Streamlit Secrets and
  are never sent to the browser.
- Monitor usage after deployment. Unexpected API/key traffic is a credential
  incident: restrict or disable the affected key, investigate, then rotate it
  carefully.

## Google Maps data-retention decision

**Decision date:** September 1, 2026

The Application uses Google-derived API content transiently to assist the user.
Durable bookkeeping values are treated as application/user-entered or
user-confirmed ledger data only when the user supplies or confirms them. Simply
pressing Save does not convert otherwise restricted Google Maps Content into
unrestricted customer-owned data.

| Data | Required treatment |
| --- | --- |
| Autocomplete predictions | Session/transient only |
| Google Places formatted address / display name | Do not persist as Google-derived content |
| Google Place ID | May be retained if a future implementation genuinely needs it and current Google terms permit it; the current Application does not need or persist it |
| Raw Places response | Never persist |
| Raw Routes response | Never persist |
| Route polyline | Do not request or persist |
| Routes `distanceMeters` | Transient only |
| Google-calculated mileage suggestion | Transient only |
| User-confirmed business mileage recorded in the ledger | Persist as application/user business-record data |
| User-authored location text stored in the ledger | Persist as application/user business-record data |

This table is the canonical implementation policy for issue #135. Selecting a
Google suggestion provides transient routing input only. The Mileage workflow
shows the selected text for lookup and uses the transient route result to fill
editable, unsaved mileage fields; it does not write a durable mileage value
until the user reviews and saves the trip. The selected display text pre-fills
an editable location field but is not written to a durable ledger field until
the user saves the trip.

No Google response cache should be introduced, and no route polyline should be
stored. No Google provenance fields should be added to the Mileage worksheet
unless a future product requirement justifies them and the applicable policy is
reviewed again. The current Mileage and backup schemas therefore do not require
a migration for issue #135.

## Billing jurisdiction

- **Billing-account country:** United States
- **Applicable jurisdiction classification:** non-EEA
- **Review date:** September 1, 2026

This deployment is documented as governed by the applicable non-EEA Google Maps
Platform terms. If the billing-account country changes, especially to an EEA
country, the applicable Google Maps Platform terms and this retention decision
must be reviewed again before relying on them.

## Current authoritative references

- [Google Maps Platform Terms of Service](https://cloud.google.com/maps-platform/terms)
- [Maps Service Specific Terms](https://cloud.google.com/maps-platform/terms/maps-service-terms/)
- [Google Maps Platform API security](https://developers.google.com/maps/api-security-best-practices)
- [Place Autocomplete Widget](https://developers.google.com/maps/documentation/javascript/place-autocomplete-new)
- [Maps JavaScript API policies and attribution](https://developers.google.com/maps/documentation/javascript/policies)
- [Routes API usage, billing, and quotas](https://developers.google.com/maps/documentation/routes/usage-and-billing)
- [Routes API policies and attribution](https://developers.google.com/maps/documentation/routes/policies)
- [Google Maps Platform EEA Terms of Service](https://cloud.google.com/terms/maps-platform/eea)
- [EEA customer FAQ](https://developers.google.com/maps/comms/eea/faq)
- [Cloud Billing budgets and alerts](https://cloud.google.com/billing/docs/how-to/budgets)
- [Streamlit Community Cloud Secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)
