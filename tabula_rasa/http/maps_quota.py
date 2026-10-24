"""Lazy deployment-wide monitoring, independent of mileage keys and human grants."""

from collections.abc import Mapping
import json
from pathlib import Path
from threading import Lock
from time import monotonic

from tabula_rasa.google_maps_quota_core import (
    GoogleMapsQuotaClient, GoogleMapsQuotaConfigurationError, GoogleMapsQuotaMonitoringConfig,
    GoogleMapsQuotaRequestError, QUOTA_CACHE_TTL_SECONDS, quota_display,
)

from .models.maps_quota import MapsQuotaGroup, MapsQuotaStatus


SETUP_GUIDANCE = 'Configure the dedicated Maps quota reader to view usage. See Google Maps setup.'
CONFIG_GUIDANCE = 'Maps quota monitoring configuration is invalid. Ask the operator to check the project number and dedicated quota-reader credential.'


class MapsQuotaAdapter:
    def __init__(self, config=None, *, invalid=False, client_factory=GoogleMapsQuotaClient, clock=monotonic):
        self._config = config
        self._invalid = invalid
        self._client_factory = client_factory
        self._clock = clock
        self._client = None
        self._cached = None
        self._fetched_at = 0
        self._lock = Lock()

    def status(self):
        # Checking setup never creates credentials or contacts Google.
        if self._invalid:
            return MapsQuotaStatus(status='error', message=CONFIG_GUIDANCE)
        if self._config is None:
            return MapsQuotaStatus(status='unconfigured', message=SETUP_GUIDANCE)
        return MapsQuotaStatus(status='not_loaded')

    def load(self, *, refresh=False):
        with self._lock:
            status = self.status()
            if status.status != 'not_loaded':
                return status
            remaining = QUOTA_CACHE_TTL_SECONDS - (self._clock() - self._fetched_at)
            if not refresh and self._cached is not None and remaining > 0:
                return self._cached.model_copy(update={'cache_remaining_seconds': remaining})
            self._cached = None
            try:
                if self._client is None:
                    self._client = self._client_factory(self._config)
                report = self._client.fetch_report()
                services = [MapsQuotaGroup(title=group.title, rows=list(group.rows)) for group in quota_display(report)]
            except GoogleMapsQuotaConfigurationError:
                return MapsQuotaStatus(status='error', message=CONFIG_GUIDANCE)
            except GoogleMapsQuotaRequestError as error:
                # The shared client constructs these solely from API name/status.
                return MapsQuotaStatus(status='error', message=str(error))
            except Exception:
                return MapsQuotaStatus(status='error', message='Google Maps usage is temporarily unavailable. Retry later.')
            self._fetched_at = self._clock()
            self._cached = MapsQuotaStatus(status='ready', services=services,
                                          cache_remaining_seconds=QUOTA_CACHE_TTL_SECONDS)
            return self._cached

    def close(self):
        with self._lock:
            if self._client is not None:
                self._client.session.close()
                self._client = None
            self._cached = None


def load_maps_quota(mapping):
    raw = mapping.get('google_maps', {}) if isinstance(mapping, Mapping) else {}
    if not isinstance(raw, Mapping) or 'quota_monitoring' not in raw:
        return MapsQuotaAdapter()
    try:
        config = GoogleMapsQuotaMonitoringConfig.from_secrets(mapping)
    except GoogleMapsQuotaConfigurationError:
        return MapsQuotaAdapter(invalid=True)
    return MapsQuotaAdapter(config)


def environment_maps_quota(environment):
    project = environment.get('TABULA_RASA_MAPS_QUOTA_PROJECT_NUMBER')
    credential_file = environment.get('TABULA_RASA_MAPS_QUOTA_SERVICE_ACCOUNT_FILE')
    if not project and not credential_file:
        return MapsQuotaAdapter()
    try:
        credential = json.loads(Path(credential_file).read_text(encoding='utf-8'))
        return load_maps_quota({'google_maps': {'quota_monitoring': {
            'project_number': project, 'service_account': credential,
            'timeout_seconds': environment.get('TABULA_RASA_MAPS_QUOTA_TIMEOUT_SECONDS', 15),
        }}})
    except Exception:
        # No paths, credential contents or parser/provider exceptions escape.
        return MapsQuotaAdapter(invalid=True)
