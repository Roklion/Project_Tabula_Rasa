"""Persistence-neutral, user-safe failures shared by application boundaries."""


class StorageError(RuntimeError):
    """Base class for safe, user-displayable storage errors."""


class StorageValidationError(StorageError):
    """Raised when domain data is invalid."""


class StorageConflictError(StorageError):
    """Raised when a uniqueness constraint would be violated."""


class StorageNotFoundError(StorageError):
    """Raised when an ID no longer exists."""


__all__ = [
    "StorageError",
    "StorageValidationError",
    "StorageConflictError",
    "StorageNotFoundError",
]
