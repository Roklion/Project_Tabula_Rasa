"""Read-only Google Maps quota and usage monitoring.

This module is intentionally independent from the profile Sheets and Drive
clients.  Quota monitoring is deployment-wide and uses a dedicated service
account with read-only Cloud APIs.  Google responses and credentials never
cross the module's boundary as errors or rendered data.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

import streamlit as st
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials


SERVICE_USAGE_ENDPOINT = "https://serviceusage.googleapis.com/v1beta1"
MONITORING_ENDPOINT = "https://monitoring.googleapis.com/v3"
MONITORING_METRIC_TYPE = "serviceruntime.googleapis.com/quota/rate/net_usage"
MONITORING_RESOURCE_TYPE = "consumer_quota"
MONITORED_SERVICES = ("routes.googleapis.com", "places.googleapis.com")
MONITORING_LOOKBACK_MINUTES = 15
SERVICE_USAGE_PAGE_SIZE = 200
GOOGLE_UNLIMITED_QUOTA_THRESHOLD = float(2**63 - 1)
SERVICE_USAGE_READ_SCOPE = "https://www.googleapis.com/auth/cloud-platform.read-only"
MONITORING_READ_SCOPE = "https://www.googleapis.com/auth/monitoring.read"
READ_ONLY_SCOPES = (SERVICE_USAGE_READ_SCOPE, MONITORING_READ_SCOPE)
DEFAULT_TIMEOUT_SECONDS = 15.0
QUOTA_CACHE_TTL_SECONDS = 120
QUOTA_VIEW_REQUESTED_KEY = "google_maps_quota_view_requested"
QUOTA_REPORT_SESSION_KEY = "google_maps_quota_report"
QUOTA_REPORT_FETCHED_AT_KEY = "google_maps_quota_report_fetched_at"
QUOTA_REPORT_CONFIG_KEY = "google_maps_quota_report_config"
QUOTA_FETCH_ATTEMPTED_KEY = "google_maps_quota_fetch_attempted"
QUOTA_CONFIG_ERROR_KEY = "google_maps_quota_config_error"
QUOTA_CONFIG_ERROR_CONFIG_KEY = "google_maps_quota_config_error_config"
QUOTA_REQUEST_ERROR_KEY = "google_maps_quota_request_error"
QUOTA_REQUEST_ERROR_CONFIG_KEY = "google_maps_quota_request_error_config"


class GoogleMapsQuotaError(RuntimeError):
    """Base class for safe, user-displayable monitoring failures."""


class GoogleMapsQuotaConfigurationError(GoogleMapsQuotaError):
    """The app-wide quota monitoring configuration is missing or invalid."""


class GoogleMapsQuotaRequestError(GoogleMapsQuotaError):
    """Google could not return quota or usage data."""


@dataclass(frozen=True, repr=False)
class GoogleMapsQuotaMonitoringConfig:
    """Deployment-wide Maps project and dedicated service-account settings."""

    project_number: str
    service_account_info: Mapping[str, Any] = field(repr=False)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        project_number = _clean_text(self.project_number)
        if (
            len(project_number) > 20
            or not project_number.isascii()
            or not project_number.isdigit()
            or int(project_number or "0") <= 0
        ):
            raise GoogleMapsQuotaConfigurationError(
                "Google Maps quota monitoring has an invalid project number."
            )
        if not isinstance(self.service_account_info, Mapping):
            raise GoogleMapsQuotaConfigurationError(
                "Google Maps quota monitoring requires a service-account JSON mapping."
            )
        required = ("type", "client_email", "private_key", "token_uri")
        if any(not _clean_text(self.service_account_info.get(key)) for key in required):
            raise GoogleMapsQuotaConfigurationError(
                "Google Maps quota monitoring service-account JSON is incomplete."
            )
        try:
            timeout = float(self.timeout_seconds)
        except (TypeError, ValueError):
            raise GoogleMapsQuotaConfigurationError(
                "Google Maps quota monitoring timeout is invalid."
            ) from None
        if not 1 <= timeout <= 60:
            raise GoogleMapsQuotaConfigurationError(
                "Google Maps quota monitoring timeout must be between 1 and 60 seconds."
            )
        object.__setattr__(self, "project_number", project_number)
        object.__setattr__(self, "timeout_seconds", timeout)

    @classmethod
    def from_secrets(
        cls, secrets_mapping: Mapping[str, Any]
    ) -> "GoogleMapsQuotaMonitoringConfig":
        if not isinstance(secrets_mapping, Mapping):
            raise GoogleMapsQuotaConfigurationError(
                "Google Maps quota monitoring is not configured for this deployment."
            )
        maps = secrets_mapping.get("google_maps")
        monitoring = maps.get("quota_monitoring") if isinstance(maps, Mapping) else None
        if not isinstance(monitoring, Mapping):
            raise GoogleMapsQuotaConfigurationError(
                "Google Maps quota monitoring is not configured for this deployment."
            )
        project_number = monitoring.get("project_number")
        # ``service_account`` is the documented name.  Accepting the explicit
        # *_json spelling makes migration from secret managers less surprising.
        credential = monitoring.get("service_account")
        if credential is None:
            credential = monitoring.get("service_account_json")
        return cls(
            project_number=(
                str(project_number)
                if isinstance(project_number, (str, int))
                else ""
            ),
            service_account_info=credential if isinstance(credential, Mapping) else {},
            timeout_seconds=monitoring.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
        )

    def credentials(self) -> Credentials:
        """Create least-privilege credentials without exposing key material."""
        try:
            return Credentials.from_service_account_info(
                dict(self.service_account_info), scopes=READ_ONLY_SCOPES
            )
        except Exception as exc:
            raise GoogleMapsQuotaConfigurationError(
                "Google Maps quota monitoring credentials are invalid."
            ) from exc


@dataclass(frozen=True)
class GoogleMapsQuotaBucket:
    dimensions: Mapping[str, str]
    effective_limit: float | None
    default_limit: float | None


@dataclass(frozen=True)
class GoogleMapsQuotaLimit:
    name: str
    display_name: str
    metric: str
    unit: str
    effective_limit: float | None
    default_limit: float | None
    buckets: tuple[GoogleMapsQuotaBucket, ...] = ()

    def effective_limit_for(self, dimensions: Mapping[str, str]) -> float | None:
        """Return the most-specific API bucket matching monitoring labels."""
        matches = [
            bucket
            for bucket in self.buckets
            if all(dimensions.get(key) == value for key, value in bucket.dimensions.items())
        ]
        if matches:
            return max(matches, key=lambda bucket: len(bucket.dimensions)).effective_limit
        return self.effective_limit


@dataclass(frozen=True)
class GoogleMapsQuotaMetric:
    name: str
    display_name: str
    metric: str
    unit: str
    limits: tuple[GoogleMapsQuotaLimit, ...]


@dataclass(frozen=True)
class GoogleMapsQuotaUsage:
    quota_metric: str
    service: str
    value: float
    unit: str
    timestamp: datetime
    dimensions: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GoogleMapsServiceReport:
    service: str
    quota_metrics: tuple[GoogleMapsQuotaMetric, ...]
    usage: Mapping[str, GoogleMapsQuotaUsage]


@dataclass(frozen=True)
class GoogleMapsQuotaReport:
    project_number: str
    services: tuple[GoogleMapsServiceReport, ...]


def _clean_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: object) -> float | None:
    if isinstance(value, Mapping):
        value = value.get("value", value.get("stringValue"))
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 or result == -1 else None


def _dimensions(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items() if item is not None}


def parse_quota_metrics(payload: Mapping[str, Any]) -> tuple[GoogleMapsQuotaMetric, ...]:
    """Parse Service Usage FULL-view metrics while retaining API metadata."""
    # Service Usage's list response uses ``metrics``.  The legacy spelling is
    # accepted for fixtures and older proxies, but is never sent by Google.
    raw_metrics = payload.get("metrics")
    if raw_metrics is None:
        raw_metrics = payload.get("consumerQuotaMetrics", ())
    if not isinstance(raw_metrics, list):
        return ()
    parsed: list[GoogleMapsQuotaMetric] = []
    for raw in raw_metrics:
        if not isinstance(raw, Mapping):
            continue
        limits: list[GoogleMapsQuotaLimit] = []
        raw_limits = raw.get("consumerQuotaLimits", ())
        if isinstance(raw_limits, list):
            for raw_limit in raw_limits:
                if not isinstance(raw_limit, Mapping):
                    continue
                buckets: list[GoogleMapsQuotaBucket] = []
                raw_buckets = raw_limit.get("quotaBuckets", ())
                if isinstance(raw_buckets, list):
                    for raw_bucket in raw_buckets:
                        if isinstance(raw_bucket, Mapping):
                            buckets.append(
                                GoogleMapsQuotaBucket(
                                    dimensions=_dimensions(raw_bucket.get("dimensions")),
                                    effective_limit=_number(raw_bucket.get("effectiveLimit")),
                                    default_limit=_number(raw_bucket.get("defaultLimit")),
                                )
                            )
                global_bucket = next(
                    (bucket for bucket in buckets if not bucket.dimensions), None
                )
                limits.append(
                    GoogleMapsQuotaLimit(
                        name=_clean_text(raw_limit.get("name")),
                        display_name=_clean_text(
                            raw_limit.get("displayName", raw.get("displayName"))
                        ),
                        metric=_clean_text(raw_limit.get("metric", raw.get("metric"))),
                        unit=_clean_text(raw_limit.get("unit", raw.get("unit"))),
                        effective_limit=(
                            _number(raw_limit.get("effectiveLimit"))
                            if raw_limit.get("effectiveLimit") is not None
                            else (global_bucket.effective_limit if global_bucket else None)
                        ),
                        default_limit=(
                            _number(raw_limit.get("defaultLimit"))
                            if raw_limit.get("defaultLimit") is not None
                            else (global_bucket.default_limit if global_bucket else None)
                        ),
                        buckets=tuple(buckets),
                    )
                )
        parsed.append(
            GoogleMapsQuotaMetric(
                name=_clean_text(raw.get("name")),
                display_name=_clean_text(raw.get("displayName")),
                metric=_clean_text(raw.get("metric")),
                unit=_clean_text(raw.get("unit")),
                limits=tuple(limits),
            )
        )
    return tuple(parsed)


def _timestamp(point: Mapping[str, Any]) -> datetime | None:
    interval = point.get("interval")
    if not isinstance(interval, Mapping):
        return None
    raw = interval.get("endTime", interval.get("startTime"))
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_usage_time_series(
    payload: Mapping[str, Any],
    *,
    service: str,
) -> dict[str, GoogleMapsQuotaUsage]:
    """Select the newest aligned point by Google's quota_metric label."""
    raw_series = payload.get("timeSeries", ())
    result: dict[str, GoogleMapsQuotaUsage] = {}
    if not isinstance(raw_series, list):
        return result
    for series in raw_series:
        if not isinstance(series, Mapping):
            continue
        resource = series.get("resource")
        metric = series.get("metric")
        labels: dict[str, str] = {}
        if isinstance(resource, Mapping):
            labels.update(_dimensions(resource.get("labels")))
        if isinstance(metric, Mapping):
            labels.update({key: value for key, value in _dimensions(metric.get("labels")).items() if key not in labels})
        metric_labels = (
            _dimensions(metric.get("labels")) if isinstance(metric, Mapping) else {}
        )
        quota_metric = metric_labels.get("quota_metric") or labels.get("quota_metric", "")
        if not quota_metric:
            continue
        points = series.get("points", ())
        if not isinstance(points, list):
            continue
        for point in points:
            if not isinstance(point, Mapping):
                continue
            timestamp = _timestamp(point)
            if timestamp is None:
                continue
            value = point.get("value")
            if not isinstance(value, Mapping):
                continue
            raw_value = value.get("doubleValue", value.get("int64Value"))
            try:
                numeric = float(raw_value)
            except (TypeError, ValueError):
                continue
            if numeric < 0:
                continue
            current = result.get(quota_metric)
            unit = _clean_text(
                series.get("unit")
                or (series.get("metricDescriptor", {}) or {}).get("unit")
                or "1/s"
            )
            usage = GoogleMapsQuotaUsage(
                quota_metric=quota_metric,
                service=service,
                value=numeric,
                unit=unit,
                timestamp=timestamp,
                dimensions=labels,
            )
            if current is None or timestamp > current.timestamp:
                result[quota_metric] = usage
            elif timestamp == current.timestamp:
                result[quota_metric] = GoogleMapsQuotaUsage(
                    quota_metric=quota_metric,
                    service=service,
                    value=current.value + numeric,
                    unit=current.unit,
                    timestamp=timestamp,
                    dimensions=current.dimensions,
                )
    return result


class GoogleMapsQuotaClient:
    """Authenticated read-only client for Service Usage and Cloud Monitoring."""

    def __init__(
        self,
        config: GoogleMapsQuotaMonitoringConfig,
        *,
        session: Any | None = None,
        now: Any | None = None,
    ) -> None:
        self.config = config
        self.session = session or AuthorizedSession(config.credentials())
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _get(
        self,
        url: str,
        params: Mapping[str, Any],
        *,
        api_name: str = "Google Cloud",
    ) -> Mapping[str, Any]:
        try:
            response = self.session.get(url, params=dict(params), timeout=self.config.timeout_seconds)
        except Exception:
            raise GoogleMapsQuotaRequestError(
                f"{api_name} request could not reach Google. Check outbound "
                "network access and retry."
            ) from None
        if response.status_code != 200:
            status_code = int(response.status_code)
            if status_code in (401, 403):
                guidance = "Verify the quota-reader OAuth scopes and IAM roles."
            elif status_code == 404:
                guidance = "Verify the numeric Google Cloud project number."
            elif status_code == 429:
                guidance = "Retry after the Google API quota recovers."
            else:
                guidance = "Verify the enabled API and quota-reader access."
            raise GoogleMapsQuotaRequestError(
                f"{api_name} request returned HTTP {status_code}. {guidance}"
            )
        try:
            payload = response.json()
        except (ValueError, TypeError):
            raise GoogleMapsQuotaRequestError(
                f"{api_name} returned an unreadable response. Retry later."
            ) from None
        if not isinstance(payload, Mapping):
            raise GoogleMapsQuotaRequestError(
                f"{api_name} returned an unreadable response. Retry later."
            )
        return payload

    def _quota_metrics(self, service: str) -> tuple[GoogleMapsQuotaMetric, ...]:
        url = f"{SERVICE_USAGE_ENDPOINT}/projects/{self.config.project_number}/services/{service}/consumerQuotaMetrics"
        page_token = ""
        parsed: list[GoogleMapsQuotaMetric] = []
        while True:
            params: dict[str, Any] = {
                "view": "FULL",
                "pageSize": SERVICE_USAGE_PAGE_SIZE,
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self._get(url, params, api_name="Service Usage")
            parsed.extend(parse_quota_metrics(payload))
            next_token = _clean_text(payload.get("nextPageToken"))
            if not next_token or next_token == page_token:
                break
            page_token = next_token
        return tuple(parsed)

    def _usage(self, service: str) -> dict[str, GoogleMapsQuotaUsage]:
        end = self.now()
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        else:
            end = end.astimezone(timezone.utc)
        start = end - timedelta(minutes=MONITORING_LOOKBACK_MINUTES)
        url = f"{MONITORING_ENDPOINT}/projects/{self.config.project_number}/timeSeries"
        params: dict[str, Any] = {
            "filter": (
                f'metric.type = "{MONITORING_METRIC_TYPE}" AND '
                f'resource.type = "{MONITORING_RESOURCE_TYPE}" AND '
                f'resource.labels.service = "{service}"'
            ),
            "interval.startTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "interval.endTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "aggregation.alignmentPeriod": "60s",
            "aggregation.perSeriesAligner": "ALIGN_RATE",
            "aggregation.crossSeriesReducer": "REDUCE_SUM",
            "aggregation.groupByFields": "metric.labels.quota_metric",
            "view": "FULL",
        }
        result: dict[str, GoogleMapsQuotaUsage] = {}
        page_token = ""
        while True:
            if page_token:
                params["pageToken"] = page_token
            payload = self._get(url, params, api_name="Cloud Monitoring")
            for key, usage in parse_usage_time_series(payload, service=service).items():
                current = result.get(key)
                if current is None or usage.timestamp > current.timestamp:
                    result[key] = usage
                elif usage.timestamp == current.timestamp:
                    result[key] = GoogleMapsQuotaUsage(
                        quota_metric=usage.quota_metric,
                        service=usage.service,
                        value=current.value + usage.value,
                        unit=current.unit,
                        timestamp=usage.timestamp,
                        dimensions=current.dimensions,
                    )
            next_token = _clean_text(payload.get("nextPageToken"))
            if not next_token or next_token == page_token:
                break
            page_token = next_token
        return result

    def fetch_report(self) -> GoogleMapsQuotaReport:
        services = tuple(
            GoogleMapsServiceReport(
                service=service,
                quota_metrics=self._quota_metrics(service),
                usage=self._usage(service),
            )
            for service in MONITORED_SERVICES
        )
        return GoogleMapsQuotaReport(self.config.project_number, services)


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


def _format_number(value: float | None) -> str:
    if value is None:
        return "Unavailable"
    if value < 0 or value >= GOOGLE_UNLIMITED_QUOTA_THRESHOLD:
        return "Unlimited"
    formatted = f"{value:,.2f}".rstrip("0").rstrip(".")
    return formatted if formatted else "0"


def _format_quota_period(unit: str) -> str:
    """Return only the readable time period from Google's quota-unit grammar."""
    raw = _clean_text(unit)
    parts = [part.strip() for part in raw.split("/") if part.strip()]
    if len(parts) < 2 or parts[0] != "1":
        return ""

    period = {
        "s": "second",
        "min": "minute",
        "h": "hour",
        "d": "day",
    }.get(parts[1].casefold())
    return f"per {period}" if period else ""


def _format_quota_endpoint(value: str) -> str:
    """Reduce Google's quota display name to its endpoint name."""
    name = _clean_text(value)
    if " - " in name:
        name = name.rsplit(" - ", 1)[-1]
    for suffix in (" per-element quota", " per request quota", " quota"):
        if name.casefold().endswith(suffix):
            name = name[: -len(suffix)].rstrip()
            break
    return name or "Quota"


def _rate_in_minutes(value: float, unit: str) -> float | None:
    period = _rate_period_seconds(unit)
    return value * (60.0 / period) if period is not None else None


def _rate_period_seconds(unit: str) -> float | None:
    lower = unit.casefold()
    components = lower.split("/")
    if len(components) > 1:
        period = components[1].strip()
        if period == "s":
            return 1.0
        if period == "min":
            return 60.0
        if period == "h":
            return 3600.0
        if period == "d":
            return 86400.0
    if "per second" in lower:
        return 1.0
    if "per minute" in lower:
        return 60.0
    if "per hour" in lower:
        return 3600.0
    if "per day" in lower:
        return 86400.0
    return None


def _format_google_timestamp(timestamp: datetime) -> str:
    """Render the source point timestamp in an unambiguous UTC form."""
    return timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _usage_in_limit_unit(
    usage: GoogleMapsQuotaUsage, limit: GoogleMapsQuotaLimit
) -> tuple[float, str] | None:
    source_period = _rate_period_seconds(usage.unit)
    target_period = _rate_period_seconds(limit.unit)
    if source_period is None or target_period is None:
        return None
    return usage.value * target_period / source_period, limit.unit


def _utilization(usage: GoogleMapsQuotaUsage, limit: GoogleMapsQuotaLimit) -> float | None:
    configured = limit.effective_limit_for(usage.dimensions)
    if configured is None:
        return None
    usage_rate = _rate_in_minutes(usage.value, usage.unit)
    limit_rate = _rate_in_minutes(configured, limit.unit)
    if usage_rate is None or limit_rate is None or limit_rate <= 0:
        return None
    return usage_rate / limit_rate


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
        for service_report in report.services:
            title = (
                "Routes API"
                if service_report.service == "routes.googleapis.com"
                else "Places API (New)"
            )
            st.markdown(f"**{title}**")
            shown = False
            for metric in service_report.quota_metrics:
                for limit in metric.limits:
                    shown = True
                    endpoint = _format_quota_endpoint(
                        limit.display_name or metric.display_name or metric.metric
                    )
                    usage = service_report.usage.get(limit.metric or metric.metric)
                    effective = (
                        limit.effective_limit_for(usage.dimensions)
                        if usage
                        else limit.effective_limit
                    )
                    quota = _format_number(effective)
                    if usage:
                        converted = _usage_in_limit_unit(usage, limit)
                        recent = (
                            _format_number(converted[0])
                            if converted is not None
                            else _format_number(usage.value)
                        )
                        summary = f"{recent}/{quota}"
                    else:
                        summary = f"0/{quota}"
                    period = _format_quota_period(limit.unit)
                    suffix = f" ({period})" if period else ""
                    st.caption(f"{endpoint}: {summary}{suffix}")
            if not shown:
                st.caption("No Google-reported quota metrics.")
