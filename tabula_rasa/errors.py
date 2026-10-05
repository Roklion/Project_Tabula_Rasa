"""Persistence-neutral, user-safe failures shared by application boundaries."""


class StorageError(RuntimeError):
    """Base class for safe, user-displayable storage errors."""

    def __init__(self, message: str = "", *, code: str | None = None):
        self.code = code
        super().__init__(message)


class StorageValidationError(StorageError):
    """Raised when domain data is invalid."""


class StorageConflictError(StorageError):
    """Raised for uniqueness, stale-baseline, or concurrent-write conflicts."""


class StorageNotFoundError(StorageError):
    """Raised when an ID no longer exists."""


__all__ = [
    "StorageError",
    "StorageValidationError",
    "StorageConflictError",
    "StorageNotFoundError",
]
