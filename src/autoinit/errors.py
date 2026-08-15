"""Exceptions raised by autoinit."""


class AutoInitError(Exception):
    """Base class for expected autoinit failures."""


class ConfigurationError(AutoInitError):
    """Raised when project configuration is missing or invalid."""


class AnalysisError(AutoInitError):
    """Raised when Python source cannot be analyzed statically."""


class OwnershipError(AutoInitError):
    """Raised when an ``__init__.py`` is not safely managed by autoinit."""


class CollisionError(AutoInitError):
    """Raised when multiple children would export the same name."""
