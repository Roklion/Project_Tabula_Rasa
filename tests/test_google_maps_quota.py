from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from tabula_rasa.google_maps_quota_core import GoogleMapsQuotaConfigurationError, GoogleMapsQuotaMonitoringConfig, GoogleMapsQuotaRequestError, GoogleMapsQuotaClient, MONITORING_READ_SCOPE, READ_ONLY_SCOPES, SERVICE_USAGE_PAGE_SIZE, SERVICE_USAGE_READ_SCOPE, _format_quota_endpoint, _format_quota_period, _format_number, _number, _rate_in_minutes, _rate_period_seconds, parse_quota_metrics, parse_usage_time_series


SERVICE_ACCOUNT = {
    "type": "service_account",
    "client_email": "quota@example.test",
    "private_key": "private-key",
    "token_uri": "https://oauth2.googleapis.com/token",
}


def secrets() -> dict[str, object]:
    return {
        "google_maps": {
            "quota_monitoring": {
                "project_number": "123456789",
                "service_account": SERVICE_ACCOUNT,
            }
        }
    }


def test_config_requires_explicit_project_and_dedicated_credential() -> None:
    config = GoogleMapsQuotaMonitoringConfig.from_secrets(secrets())
    assert config.project_number == "123456789"
    assert config.service_account_info == SERVICE_ACCOUNT
    assert "private-key" not in repr(config)
    with patch(
        "tabula_rasa.google_maps_quota_core.Credentials.from_service_account_info"
    ) as from_service_account_info:
        config.credentials()
    assert from_service_account_info.call_args.kwargs["scopes"] == READ_ONLY_SCOPES
    assert READ_ONLY_SCOPES == (SERVICE_USAGE_READ_SCOPE, MONITORING_READ_SCOPE)

    with pytest.raises(GoogleMapsQuotaConfigurationError):
        GoogleMapsQuotaMonitoringConfig.from_secrets({"google_maps": {}})
    with pytest.raises(
        GoogleMapsQuotaConfigurationError, match="invalid project number"
    ):
        GoogleMapsQuotaMonitoringConfig.from_secrets(
            {"google_maps": {"quota_monitoring": {"project_number": "maps-id"}}}
        )
    with pytest.raises(
        GoogleMapsQuotaConfigurationError, match="invalid project number"
    ):
        GoogleMapsQuotaMonitoringConfig(
            "9" * 21, SERVICE_ACCOUNT
        )


def test_quota_parser_preserves_effective_limit_and_dimension_buckets() -> None:
    metrics = parse_quota_metrics(
        {
            "metrics": [
                {
                    "name": "metric-resource",
                    "displayName": "Compute Routes",
                    "metric": "routes.googleapis.com/requests",
                    "consumerQuotaLimits": [
                        {
                            "name": "limit-resource",
                            "unit": "1/min/{project}",
                            "quotaBuckets": [
                                {
                                    "dimensions": {"region": "us"},
                                    "defaultLimit": "20",
                                    "effectiveLimit": "10",
                                },
                                {
                                    "dimensions": {},
                                    "defaultLimit": "100",
                                    "effectiveLimit": "60",
                                },
                            ],
                        }
                    ],
                }
            ]
        }
    )
    limit = metrics[0].limits[0]
    assert limit.effective_limit == 60
    assert limit.default_limit == 100
    assert limit.buckets[0].dimensions == {"region": "us"}
    assert limit.effective_limit_for({"region": "us", "quota_metric": "x"}) == 10
    assert limit.effective_limit_for({"region": "ca"}) == 60


def test_usage_parser_uses_metric_quota_label_and_keeps_service_resource_label() -> None:
    usage = parse_usage_time_series(
        {
            "timeSeries": [
                {
                    "resource": {
                        "labels": {"service": "places.googleapis.com"}
                    },
                    "metric": {
                        "labels": {"quota_metric": "places.googleapis.com/requests"}
                    },
                    "points": [
                        {
                            "interval": {"endTime": "2026-09-01T12:01:00Z"},
                            "value": {"doubleValue": 2},
                        }
                    ],
                }
            ]
        },
        service="places.googleapis.com",
    )
    assert usage["places.googleapis.com/requests"].service == "places.googleapis.com"


def test_quota_parser_accepts_legacy_fixture_field_only_as_fallback() -> None:
    assert parse_quota_metrics({"consumerQuotaMetrics": []}) == ()


def test_usage_parser_maps_google_label_and_keeps_newest_timestamp() -> None:
    usage = parse_usage_time_series(
        {
            "timeSeries": [
                {
                    "resource": {
                        "labels": {
                            "service": "routes.googleapis.com",
                        }
                    },
                    "metric": {
                        "labels": {
                            "quota_metric": "routes.googleapis.com/requests",
                        }
                    },
                    "unit": "1/s",
                    "points": [
                        {
                            "interval": {"endTime": "2026-09-01T12:00:00Z"},
                            "value": {"doubleValue": 1},
                        },
                        {
                            "interval": {"endTime": "2026-09-01T12:01:00Z"},
                            "value": {"doubleValue": 2},
                        },
                    ],
                }
            ]
        },
        service="routes.googleapis.com",
    )
    assert usage["routes.googleapis.com/requests"].value == 2
    assert usage["routes.googleapis.com/requests"].timestamp == datetime(
        2026, 9, 1, 12, 1, tzinfo=timezone.utc
    )


def test_number_and_rate_formatting_preserve_zero_and_exact_periods() -> None:
    assert _format_number(0.0) == "0"
    assert _number("-1") == -1.0
    assert _number("-2") is None
    assert _format_number(-1.0) == "Unlimited"
    assert _format_number(float(2**63 - 1)) == "Unlimited"
    assert _format_quota_period("1/min/{project}") == "per minute"
    assert _format_quota_period("1/min/{project}/{user}") == "per minute"
    assert _format_quota_period("1/d/{project}") == "per day"
    assert _format_quota_period("1/session") == ""
    assert _format_quota_endpoint(
        "DistanceMatrix - ComputeRouteMatrix per-element quota"
    ) == "ComputeRouteMatrix"
    assert _format_quota_endpoint(
        "Directions - ComputeRoutes per request quota"
    ) == "ComputeRoutes"
    assert _rate_period_seconds("1/session") is None
    assert _rate_period_seconds("1/min/{project}") == 60.0
    assert _rate_in_minutes(2.0, "1/s") == 120.0


def test_client_paginates_service_usage_and_queries_both_services() -> None:
    def response(payload: object, status_code: int = 200) -> Mock:
        item = Mock(status_code=status_code)
        item.json.return_value = payload
        return item

    session = Mock()
    session.get.side_effect = [
        response({"metrics": [], "nextPageToken": "next"}),
        response({"metrics": []}),
        response({"timeSeries": [], "nextPageToken": "usage-next"}),
        response({"timeSeries": []}),
        response({"metrics": []}),
        response({"timeSeries": []}),
    ]
    config = GoogleMapsQuotaMonitoringConfig.from_secrets(secrets())
    report = GoogleMapsQuotaClient(
        config,
        session=session,
        now=lambda: datetime(
            2026, 9, 1, 12, tzinfo=timezone(timedelta(hours=-4))
        ),
    ).fetch_report()
    assert [item.service for item in report.services] == [
        "routes.googleapis.com",
        "places.googleapis.com",
    ]
    assert session.get.call_args_list[0].kwargs["params"]["view"] == "FULL"
    assert (
        session.get.call_args_list[0].kwargs["params"]["pageSize"]
        == SERVICE_USAGE_PAGE_SIZE
        == 200
    )
    assert session.get.call_args_list[1].kwargs["params"]["pageToken"] == "next"
    assert session.get.call_args_list[2].kwargs["params"]["aggregation.groupByFields"] == (
        "metric.labels.quota_metric"
    )
    assert session.get.call_args_list[2].kwargs["params"]["interval.startTime"] == (
        "2026-09-01T15:45:00Z"
    )
    assert session.get.call_args_list[2].kwargs["params"]["interval.endTime"] == (
        "2026-09-01T16:00:00Z"
    )
    assert session.get.call_args_list[3].kwargs["params"]["pageToken"] == "usage-next"


def test_client_merges_monitoring_usage_across_pages() -> None:
    def response(payload: object) -> Mock:
        item = Mock(status_code=200)
        item.json.return_value = payload
        return item

    def series(metric: str, value: float) -> dict[str, object]:
        return {
            "resource": {"labels": {"service": "routes.googleapis.com"}},
            "metric": {"labels": {"quota_metric": metric}},
            "points": [
                {
                    "interval": {"endTime": "2026-09-01T12:01:00Z"},
                    "value": {"doubleValue": value},
                }
            ],
        }

    session = Mock()
    session.get.side_effect = [
        response({"timeSeries": [series("routes.googleapis.com/first", 2)], "nextPageToken": "next"}),
        response({"timeSeries": [series("routes.googleapis.com/second", 3)]}),
    ]
    config = GoogleMapsQuotaMonitoringConfig.from_secrets(secrets())

    usage = GoogleMapsQuotaClient(config, session=session)._usage("routes.googleapis.com")

    assert usage["routes.googleapis.com/first"].value == 2
    assert usage["routes.googleapis.com/second"].value == 3
    assert session.get.call_args_list[1].kwargs["params"]["pageToken"] == "next"


def test_client_redacts_transport_and_http_failures() -> None:
    config = GoogleMapsQuotaMonitoringConfig.from_secrets(secrets())
    session = Mock()
    session.get.side_effect = RuntimeError("private-key")
    client = GoogleMapsQuotaClient(config, session=session)
    with pytest.raises(GoogleMapsQuotaRequestError) as error:
        client._get("https://example.test", {})
    assert "private-key" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True

    session.get.side_effect = None
    session.get.return_value = Mock(status_code=403)
    with pytest.raises(GoogleMapsQuotaRequestError) as error:
        client._get("https://example.test", {}, api_name="Cloud Monitoring")
    assert "private-key" not in str(error.value)
    assert str(error.value) == (
        "Cloud Monitoring request returned HTTP 403. "
        "Verify the quota-reader OAuth scopes and IAM roles."
    )
