"""Generate explicit, managed package APIs for Python 3.15 and newer."""

from importlib.metadata import PackageNotFoundError, version

from autoinit.errors import (
    AutoInitError,
)
from autoinit.generator import plan
from autoinit.models import Config, GenerationPlan

try:
    __version__ = version("autoinit")
except PackageNotFoundError:
    __version__ = "0.1.0"

__all__ = (
    "AutoInitError",
    "Config",
    "GenerationPlan",
    "plan",
)
