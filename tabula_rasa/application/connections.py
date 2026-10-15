"""Safe connection transport records; provider grants never belong to sessions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectionStatus:
    provider: str = 'google_drive'
    status: str = 'not_configured'
    revision: int = 0
