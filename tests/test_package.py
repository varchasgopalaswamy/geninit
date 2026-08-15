"""Tests for the public geninit package interface."""

import geninit


def test_public_package_api_remains_narrow() -> None:
    """Dogfooding generation does not broaden the supported top-level API."""
    assert geninit.__all__ == (
        "Config",
        "GenInitError",
        "GenerationPlan",
        "plan",
    )
    assert geninit.__version__ == "0.1.0"
