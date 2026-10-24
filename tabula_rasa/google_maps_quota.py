"""Streamlit adapter and compatibility facade for shared Maps quota monitoring."""

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

import streamlit as st
from google.oauth2.service_account import Credentials as Credentials

from .google_maps_quota_core import (
    SERVICE_USAGE_ENDPOINT as SERVICE_USAGE_ENDPOINT,
    MONITORING_ENDPOINT as MONITORING_ENDPOINT,
    MONITORING_METRIC_TYPE as MONITORING_METRIC_TYPE,
    MONITORING_RESOURCE_TYPE as MONITORING_RESOURCE_TYPE,
    MONITORED_SERVICES as MONITORED_SERVICES,
    MONITORING_LOOKBACK_MINUTES as MONITORING_LOOKBACK_MINUTES,
    SERVICE_USAGE_PAGE_SIZE as SERVICE_USAGE_PAGE_SIZE,
    GOOGLE_UNLIMITED_QUOTA_THRESHOLD as GOOGLE_UNLIMITED_QUOTA_THRESHOLD,
    SERVICE_USAGE_READ_SCOPE as SERVICE_USAGE_READ_SCOPE,
    MONITORING_READ_SCOPE as MONITORING_READ_SCOPE,
    READ_ONLY_SCOPES as READ_ONLY_SCOPES,
    DEFAULT_TIMEOUT_SECONDS as DEFAULT_TIMEOUT_SECONDS,
    QUOTA_CACHE_TTL_SECONDS as QUOTA_CACHE_TTL_SECONDS,
    GoogleMapsQuotaError as GoogleMapsQuotaError,
    GoogleMapsQuotaConfigurationError as GoogleMapsQuotaConfigurationError,
    GoogleMapsQuotaRequestError as GoogleMapsQuotaRequestError,
    GoogleMapsQuotaMonitoringConfig as GoogleMapsQuotaMonitoringConfig,
    GoogleMapsQuotaBucket as GoogleMapsQuotaBucket,
    GoogleMapsQuotaLimit as GoogleMapsQuotaLimit,
    GoogleMapsQuotaMetric as GoogleMapsQuotaMetric,
    GoogleMapsQuotaUsage as GoogleMapsQuotaUsage,
    GoogleMapsServiceReport as GoogleMapsServiceReport,
    GoogleMapsQuotaReport as GoogleMapsQuotaReport,
    _clean_text as _clean_text,
    _number as _number,
    _dimensions as _dimensions,
    parse_quota_metrics as parse_quota_metrics,
    _timestamp as _timestamp,
    parse_usage_time_series as parse_usage_time_series,
    GoogleMapsQuotaClient as GoogleMapsQuotaClient,
    _format_number as _format_number,
    _format_quota_period as _format_quota_period,
    _format_quota_endpoint as _format_quota_endpoint,
    _rate_in_minutes as _rate_in_minutes,
    _rate_period_seconds as _rate_period_seconds,
    _usage_in_limit_unit as _usage_in_limit_unit,
    quota_display as quota_display,
)

QUOTA_VIEW_REQUESTED_KEY = "google_maps_quota_view_requested"
QUOTA_REPORT_SESSION_KEY = "google_maps_quota_report"
QUOTA_REPORT_FETCHED_AT_KEY = "google_maps_quota_report_fetched_at"
QUOTA_REPORT_CONFIG_KEY = "google_maps_quota_report_config"
QUOTA_FETCH_ATTEMPTED_KEY = "google_maps_quota_fetch_attempted"
QUOTA_CONFIG_ERROR_KEY = "google_maps_quota_config_error"
QUOTA_CONFIG_ERROR_CONFIG_KEY = "google_maps_quota_config_error_config"
QUOTA_REQUEST_ERROR_KEY = "google_maps_quota_request_error"
QUOTA_REQUEST_ERROR_CONFIG_KEY = "google_maps_quota_request_error_config"


@st.cache_data(ttl=QUOTA_CACHE_TTL_SECONDS, show_spinner=False)
def _cached_quota_report(
    project_number: str, service_account_json: str, timeout: float
) -> GoogleMapsQuotaReport:
    """Cache only the sanitized report; timestamps remain Google timestamps."""
    try:
        credential = json.loads(service_account_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise GoogleMapsQuotaConfigurationError(
            "Google Maps quota monitoring credentials are invalid."
        ) from exc
    config = GoogleMapsQuotaMonitoringConfig(project_number, credential, timeout)
    return GoogleMapsQuotaClient(config).fetch_report()


def load_google_maps_quota_report(
    secrets_mapping: Mapping[str, Any],
) -> GoogleMapsQuotaReport:
    config = GoogleMapsQuotaMonitoringConfig.from_secrets(secrets_mapping)
    try:
        encoded = json.dumps(dict(config.service_account_info), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise GoogleMapsQuotaConfigurationError(
            "Google Maps quota monitoring credentials are invalid."
        ) from exc
    return _cached_quota_report(
        config.project_number, encoded, config.timeout_seconds
    )


def _quota_config_identity(config: GoogleMapsQuotaMonitoringConfig) -> str:
    """Return a non-sensitive identity for the cached report configuration."""
    private_key = _clean_text(config.service_account_info.get("private_key"))
    private_key_digest = hashlib.sha256(private_key.encode("utf-8")).hexdigest()
    material = json.dumps(
        {
            "project_number": config.project_number,
            "service_account_type": _clean_text(config.service_account_info.get("type")),
            "client_email": _clean_text(config.service_account_info.get("client_email")),
            "token_uri": _clean_text(config.service_account_info.get("token_uri")),
            "private_key_digest": private_key_digest,
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def clear_google_maps_quota_cache() -> None:
    """Clear only the quota-monitoring cache."""
    _cached_quota_report.clear()


def render_google_maps_usage_sidebar(secrets_mapping: Mapping[str, Any]) -> None:
    """Render a compact quota summary at the bottom of the authenticated sidebar."""
    with st.expander("Google Maps API usage", expanded=False):
        st.caption(
            f"Routes and Places usage is sampled within a {MONITORING_LOOKBACK_MINUTES}-minute "
            "lookback. Each row shows Google's latest sampled rate in the quota's "
            "limit units and can lag several minutes, including up to about 240 "
            "seconds after sampling. This is not a real-time remaining-request or "
            "billing/spend meter."
        )
        try:
            config = GoogleMapsQuotaMonitoringConfig.from_secrets(secrets_mapping)
        except GoogleMapsQuotaConfigurationError:
            st.info("Configure the dedicated Maps quota reader to view usage.")
            return
        if not st.session_state.get(QUOTA_VIEW_REQUESTED_KEY, False):
            st.caption("Select Load usage to query Google quota monitoring.")
            if st.button("Load usage", key="load-google-maps-usage-sidebar"):
                st.session_state[QUOTA_VIEW_REQUESTED_KEY] = True
                st.rerun()
            return
        if st.button("Refresh", key="refresh-google-maps-usage-sidebar"):
            clear_google_maps_quota_cache()
            st.session_state.pop(QUOTA_REPORT_SESSION_KEY, None)
            st.session_state.pop(QUOTA_REPORT_FETCHED_AT_KEY, None)
            st.session_state.pop(QUOTA_REPORT_CONFIG_KEY, None)
            st.session_state.pop(QUOTA_FETCH_ATTEMPTED_KEY, None)
            st.session_state.pop(QUOTA_CONFIG_ERROR_KEY, None)
            st.session_state.pop(QUOTA_CONFIG_ERROR_CONFIG_KEY, None)
            st.session_state.pop(QUOTA_REQUEST_ERROR_KEY, None)
            st.session_state.pop(QUOTA_REQUEST_ERROR_CONFIG_KEY, None)
            st.rerun()
        report = st.session_state.get(QUOTA_REPORT_SESSION_KEY)
        current_config_identity = _quota_config_identity(config)
        if report is not None:
            fetched_at = st.session_state.get(QUOTA_REPORT_FETCHED_AT_KEY)
            cached_config_identity = st.session_state.get(QUOTA_REPORT_CONFIG_KEY)
            now = datetime.now(timezone.utc)
            configuration_changed = (
                cached_config_identity != current_config_identity
                or getattr(report, "project_number", None) != config.project_number
            )
            expired = (
                not isinstance(fetched_at, datetime)
                or fetched_at.tzinfo is None
                or now - fetched_at >= timedelta(seconds=QUOTA_CACHE_TTL_SECONDS)
            )
            if configuration_changed:
                st.info("The usage report expired. Select Refresh to load a current report.")
                return
            if expired:
                st.warning("This report is more than 120 seconds old and may be stale. Select Refresh for current data.")
        if report is None and not st.session_state.get(QUOTA_FETCH_ATTEMPTED_KEY, False):
            st.session_state[QUOTA_FETCH_ATTEMPTED_KEY] = True
            try:
                report = load_google_maps_quota_report(secrets_mapping)
            except GoogleMapsQuotaConfigurationError as exc:
                st.session_state[QUOTA_CONFIG_ERROR_KEY] = str(exc)
                st.session_state[QUOTA_CONFIG_ERROR_CONFIG_KEY] = current_config_identity
            except GoogleMapsQuotaRequestError as exc:
                st.session_state[QUOTA_REQUEST_ERROR_KEY] = str(exc)
                st.session_state[QUOTA_REQUEST_ERROR_CONFIG_KEY] = current_config_identity
            else:
                st.session_state[QUOTA_REPORT_SESSION_KEY] = report
                st.session_state[QUOTA_REPORT_FETCHED_AT_KEY] = datetime.now(timezone.utc)
                st.session_state[QUOTA_REPORT_CONFIG_KEY] = current_config_identity
                st.session_state.pop(QUOTA_CONFIG_ERROR_KEY, None)
                st.session_state.pop(QUOTA_CONFIG_ERROR_CONFIG_KEY, None)
                st.session_state.pop(QUOTA_REQUEST_ERROR_KEY, None)
                st.session_state.pop(QUOTA_REQUEST_ERROR_CONFIG_KEY, None)
        config_error = st.session_state.get(QUOTA_CONFIG_ERROR_KEY)
        if config_error and st.session_state.get(QUOTA_CONFIG_ERROR_CONFIG_KEY) != current_config_identity:
            st.session_state.pop(QUOTA_CONFIG_ERROR_KEY, None)
            st.session_state.pop(QUOTA_CONFIG_ERROR_CONFIG_KEY, None)
            config_error = None
        request_error = st.session_state.get(QUOTA_REQUEST_ERROR_KEY)
        if (
            request_error
            and st.session_state.get(QUOTA_REQUEST_ERROR_CONFIG_KEY)
            != current_config_identity
        ):
            st.session_state.pop(QUOTA_REQUEST_ERROR_KEY, None)
            st.session_state.pop(QUOTA_REQUEST_ERROR_CONFIG_KEY, None)
            request_error = None
        if config_error:
            st.error(config_error)
            if st.button("Retry", key="retry-config-error-google-maps-usage-sidebar"):
                st.session_state.pop(QUOTA_FETCH_ATTEMPTED_KEY, None)
                st.session_state.pop(QUOTA_CONFIG_ERROR_KEY, None)
                st.session_state.pop(QUOTA_CONFIG_ERROR_CONFIG_KEY, None)
                st.rerun()
            return
        if report is None:
            st.warning(
                str(request_error)
                if request_error
                else "Google Maps usage is temporarily unavailable."
            )
            if st.button("Retry", key="retry-fetch-error-google-maps-usage-sidebar"):
                st.session_state.pop(QUOTA_FETCH_ATTEMPTED_KEY, None)
                st.session_state.pop(QUOTA_REQUEST_ERROR_KEY, None)
                st.session_state.pop(QUOTA_REQUEST_ERROR_CONFIG_KEY, None)
                st.rerun()
            return
        for group in quota_display(report):
            st.markdown(f"**{group.title}**")
            for row in group.rows:
                st.caption(row)
            if not group.rows:
                st.caption("No Google-reported quota metrics.")
