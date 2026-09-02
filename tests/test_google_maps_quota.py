from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest

from tabula_rasa.google_maps_quota import (
    GoogleMapsQuotaLimit,
    GoogleMapsQuotaMetric,
    GoogleMapsQuotaConfigurationError,
    GoogleMapsQuotaMonitoringConfig,
    GoogleMapsQuotaRequestError,
    GoogleMapsQuotaClient,
    GoogleMapsQuotaReport,
    GoogleMapsQuotaUsage,
    GoogleMapsServiceReport,
    QUOTA_CONFIG_ERROR_CONFIG_KEY,
    QUOTA_CONFIG_ERROR_KEY,
    QUOTA_REPORT_CONFIG_KEY,
    QUOTA_REPORT_FETCHED_AT_KEY,
    QUOTA_REPORT_SESSION_KEY,
    QUOTA_VIEW_REQUESTED_KEY,
    _format_number,
    _quota_config_identity,
    _rate_in_minutes,
    _rate_period_seconds,
    parse_quota_metrics,
    parse_usage_time_series,
    render_google_maps_usage_sidebar,
)


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
        client._get("https://example.test", {})
    assert "private-key" not in str(error.value)


def test_sidebar_is_discoverable_but_does_not_call_google_when_unconfigured() -> None:
    with patch("tabula_rasa.google_maps_quota.st.expander", return_value=MagicMock()), patch(
        "tabula_rasa.google_maps_quota.st.caption"
    ) as caption, patch("tabula_rasa.google_maps_quota.st.info") as info, patch(
        "tabula_rasa.google_maps_quota.load_google_maps_quota_report"
    ) as load:
        render_google_maps_usage_sidebar({})

    assert "up to about 240 seconds after sampling" in caption.call_args.args[0]
    info.assert_called_once()
    load.assert_not_called()


def test_sidebar_shows_google_timestamp_with_recent_usage() -> None:
    report = GoogleMapsQuotaReport(
        project_number="123456789",
        services=(
            GoogleMapsServiceReport(
                service="routes.googleapis.com",
                quota_metrics=(
                    GoogleMapsQuotaMetric(
                        name="metric-resource",
                        display_name="Compute Routes",
                        metric="routes.googleapis.com/requests",
                        unit="1/min/{project}",
                        limits=(
                            GoogleMapsQuotaLimit(
                                name="limit-resource",
                                display_name="Requests per minute",
                                metric="routes.googleapis.com/requests",
                                unit="1/min/{project}",
                                effective_limit=10,
                                default_limit=10,
                            ),
                        ),
                    ),
                ),
                usage={
                    "routes.googleapis.com/requests": GoogleMapsQuotaUsage(
                        quota_metric="routes.googleapis.com/requests",
                        service="routes.googleapis.com",
                        value=4,
                        unit="1/min/{project}",
                        timestamp=datetime(2026, 9, 1, 12, 1, tzinfo=timezone.utc),
                    )
                },
            ),
        ),
    )
    with patch("tabula_rasa.google_maps_quota.st.expander", return_value=MagicMock()), patch(
        "tabula_rasa.google_maps_quota.st.caption"
    ) as caption, patch("tabula_rasa.google_maps_quota.st.markdown"), patch(
        "tabula_rasa.google_maps_quota.st.button", return_value=False
    ), patch(
        "tabula_rasa.google_maps_quota.load_google_maps_quota_report", return_value=report
    ), patch(
        "tabula_rasa.google_maps_quota.st.session_state",
        {QUOTA_VIEW_REQUESTED_KEY: True},
    ):
        render_google_maps_usage_sidebar(secrets())

    rendered = "\n".join(str(call.args[0]) for call in caption.call_args_list)
    assert "Google timestamp: 2026-09-01 12:01:00 UTC" in rendered
    assert "Google data age:" in rendered


def test_sidebar_does_not_query_google_until_usage_is_loaded() -> None:
    with patch("tabula_rasa.google_maps_quota.st.expander", return_value=MagicMock()), patch(
        "tabula_rasa.google_maps_quota.st.caption"
    ) as caption, patch("tabula_rasa.google_maps_quota.st.button", return_value=False), patch(
        "tabula_rasa.google_maps_quota.st.session_state", {}
    ), patch(
        "tabula_rasa.google_maps_quota.load_google_maps_quota_report"
    ) as load:
        render_google_maps_usage_sidebar(secrets())

    load.assert_not_called()
    assert any("Select Load usage" in str(call.args[0]) for call in caption.call_args_list)


def test_sidebar_reuses_loaded_report_without_requerying_google() -> None:
    report = GoogleMapsQuotaReport(project_number="123456789", services=())
    session_state = {QUOTA_VIEW_REQUESTED_KEY: True}
    with patch("tabula_rasa.google_maps_quota.st.expander", return_value=MagicMock()), patch(
        "tabula_rasa.google_maps_quota.st.caption"
    ), patch("tabula_rasa.google_maps_quota.st.markdown"), patch(
        "tabula_rasa.google_maps_quota.st.button", return_value=False
    ), patch("tabula_rasa.google_maps_quota.st.session_state", session_state), patch(
        "tabula_rasa.google_maps_quota.load_google_maps_quota_report", return_value=report
    ) as load:
        render_google_maps_usage_sidebar(secrets())
        render_google_maps_usage_sidebar(secrets())

    load.assert_called_once()


def test_sidebar_expires_report_without_requerying_until_refresh() -> None:
    report = GoogleMapsQuotaReport(project_number="123456789", services=())
    session_state = {
        QUOTA_VIEW_REQUESTED_KEY: True,
        QUOTA_REPORT_SESSION_KEY: report,
        QUOTA_REPORT_FETCHED_AT_KEY: datetime.now(timezone.utc)
        - timedelta(seconds=121),
        QUOTA_REPORT_CONFIG_KEY: "stale-config",
    }
    with patch("tabula_rasa.google_maps_quota.st.expander", return_value=MagicMock()), patch(
        "tabula_rasa.google_maps_quota.st.caption"
    ), patch("tabula_rasa.google_maps_quota.st.info") as info, patch(
        "tabula_rasa.google_maps_quota.st.warning"
    ) as warning, patch(
        "tabula_rasa.google_maps_quota.st.button", return_value=False
    ), patch(
        "tabula_rasa.google_maps_quota.st.session_state", session_state
    ), patch(
        "tabula_rasa.google_maps_quota.load_google_maps_quota_report"
    ) as load:
        render_google_maps_usage_sidebar(secrets())
        render_google_maps_usage_sidebar(secrets())

    load.assert_not_called()
    info.assert_any_call("The usage report expired. Select Refresh to load a current report.")
    warning.assert_not_called()
    assert QUOTA_REPORT_SESSION_KEY in session_state


def test_sidebar_displays_stale_report_without_requerying_google() -> None:
    report = GoogleMapsQuotaReport(project_number="123456789", services=())
    config = GoogleMapsQuotaMonitoringConfig.from_secrets(secrets())
    session_state = {
        QUOTA_VIEW_REQUESTED_KEY: True,
        QUOTA_REPORT_SESSION_KEY: report,
        QUOTA_REPORT_FETCHED_AT_KEY: datetime.now(timezone.utc)
        - timedelta(seconds=121),
        QUOTA_REPORT_CONFIG_KEY: _quota_config_identity(config),
    }
    with patch("tabula_rasa.google_maps_quota.st.expander", return_value=MagicMock()), patch(
        "tabula_rasa.google_maps_quota.st.caption"
    ), patch("tabula_rasa.google_maps_quota.st.warning") as warning, patch(
        "tabula_rasa.google_maps_quota.st.button", return_value=False
    ), patch(
        "tabula_rasa.google_maps_quota.st.session_state", session_state
    ), patch(
        "tabula_rasa.google_maps_quota.load_google_maps_quota_report"
    ) as load:
        render_google_maps_usage_sidebar(secrets())

    load.assert_not_called()
    warning.assert_called_with(
        "This report is more than 120 seconds old and may be stale. Select Refresh for current data."
    )
    assert session_state[QUOTA_REPORT_SESSION_KEY] is report


def test_sidebar_preserves_sanitized_configuration_error_without_retrying() -> None:
    session_state = {QUOTA_VIEW_REQUESTED_KEY: True}
    error = GoogleMapsQuotaConfigurationError(
        "Google Maps quota monitoring credentials are invalid."
    )
    with patch("tabula_rasa.google_maps_quota.st.expander", return_value=MagicMock()), patch(
        "tabula_rasa.google_maps_quota.st.caption"
    ), patch("tabula_rasa.google_maps_quota.st.error") as show_error, patch(
        "tabula_rasa.google_maps_quota.st.button", return_value=False
    ), patch(
        "tabula_rasa.google_maps_quota.st.session_state", session_state
    ), patch(
        "tabula_rasa.google_maps_quota.load_google_maps_quota_report",
        side_effect=error,
    ) as load:
        render_google_maps_usage_sidebar(secrets())
        render_google_maps_usage_sidebar(secrets())

    load.assert_called_once()
    show_error.assert_called_with(str(error))
    assert session_state[QUOTA_CONFIG_ERROR_KEY] == str(error)
    assert QUOTA_CONFIG_ERROR_CONFIG_KEY in session_state
