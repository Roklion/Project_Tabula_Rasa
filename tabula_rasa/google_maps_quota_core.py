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
from typing import Any

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


def _usage_in_limit_unit(
    usage: GoogleMapsQuotaUsage, limit: GoogleMapsQuotaLimit
) -> tuple[float, str] | None:
    source_period = _rate_period_seconds(usage.unit)
    target_period = _rate_period_seconds(limit.unit)
    if source_period is None or target_period is None:
        return None
    return usage.value * target_period / source_period, limit.unit


@dataclass(frozen=True)
class GoogleMapsQuotaDisplay:
    title: str
    rows: tuple[str, ...]


def quota_display(report: GoogleMapsQuotaReport) -> tuple[GoogleMapsQuotaDisplay, ...]:
    """Project only display rows; provider identities and dimensions stay private."""
    groups = []
    for service, title in zip(MONITORED_SERVICES, ("Routes API", "Places API (New)")):
        rows = []
        for service_report in report.services:
            if service_report.service != service:
                continue
            for metric in service_report.quota_metrics:
                for limit in metric.limits:
                    endpoint = _format_quota_endpoint(limit.display_name or metric.display_name or metric.metric)
                    usage = service_report.usage.get(limit.metric or metric.metric)
                    effective = limit.effective_limit_for(usage.dimensions) if usage else limit.effective_limit
                    converted = _usage_in_limit_unit(usage, limit) if usage else None
                    recent = (_format_number(converted[0] if converted else usage.value) if usage else "0")
                    period = _format_quota_period(limit.unit)
                    suffix = f" ({period})" if period else ""
                    rows.append(f"{endpoint}: {recent}/{_format_number(effective)}{suffix}")
        groups.append(GoogleMapsQuotaDisplay(title, tuple(rows)))
    return tuple(groups)
