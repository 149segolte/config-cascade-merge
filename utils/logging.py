"""Shared logging configuration and application errors."""

from __future__ import annotations

import logging

from .yaml_loader import SourceLocation

logger = logging.getLogger("config-merger")


def configure_logging() -> None:
    """Configure command-line logging for config-merger."""
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")


class ConfigError(Exception):
    """Base class for config-merger errors tied to an optional source location."""

    def __init__(self, message: str, location: SourceLocation | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.location = location

    def __str__(self) -> str:
        if self.location is None:
            return self.message

        file_name = self.location.file_name
        line_number = self.location.line_number
        if file_name is not None and line_number is not None:
            return f"{file_name}:{line_number}: {self.message}"
        if line_number is not None:
            return f"line {line_number}: {self.message}"
        if file_name is not None:
            return f"{file_name}: {self.message}"
        return self.message


class SchemaError(ConfigError):
    """Raised when a schema config is structurally invalid."""


class OverlayError(ConfigError):
    """Raised when an overlay file or operation is invalid."""
