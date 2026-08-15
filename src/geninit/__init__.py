"""Generate explicit, managed package APIs for Python 3.15 and newer."""

from importlib.metadata import PackageNotFoundError, version

__public__ = ("errors", "generator", "models")
__private__ = ("cli", "config")

# <geninit>
lazy from . import errors, generator, models
lazy from .errors import GenInitError
lazy from .generator import plan
lazy from .models import Config, GenerationPlan

__all__ = (
    "Config",
    "GenInitError",
    "GenerationPlan",
    "errors",
    "generator",
    "models",
    "plan",
)
# </geninit>

try:
    __version__ = version("geninit")
except PackageNotFoundError:
    __version__ = "0.1.0"

__all__ = (
    "Config",
    "GenInitError",
    "GenerationPlan",
    "plan",
)
