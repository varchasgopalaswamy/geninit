"""Exceptions raised by geninit."""

__all__ = ("GenInitError",)


class GenInitError(Exception):
    """Base class for expected geninit failures."""


class ConfigurationError(GenInitError):
    """Raised when project configuration is missing or invalid."""


class AnalysisError(GenInitError):
    """Raised when Python source cannot be analyzed statically."""


class OwnershipError(GenInitError):
    """Raised when an ``__init__.py`` is not safely managed by geninit."""


class CollisionError(GenInitError):
    """Raised when multiple children would export the same name."""
