"""Exception hierarchy."""

from __future__ import annotations


class ReconsiError(Exception):
    """Base class for all ReconSI errors."""


class ConfigurationError(ReconsiError):
    """The reconciliation configuration is invalid."""


class InputError(ReconsiError):
    """An input dataset could not be located or read."""


class BackendUnavailableError(ReconsiError):
    """An optional backend was requested but its dependency is not installed."""
