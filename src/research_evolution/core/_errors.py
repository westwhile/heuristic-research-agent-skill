"""Exception hierarchy for the core records module."""

from __future__ import annotations


class CoreError(Exception):
    """Base class for every failure raised by the core records kernel."""


class StrictJsonError(CoreError):
    """Input text is not strict UTF-8 JSON.

    Raised for invalid encoding, BOM, syntax errors, duplicate object keys at
    any nesting level, non-finite numbers, numbers beyond the frozen protocol
    digit/scale limits (such as a 5000-digit integer or 1e9999), excessive
    nesting, and non-object top-level values.
    """


class SchemaDefinitionError(CoreError):
    """A schema file is itself invalid.

    Raised when a schema cannot be parsed, uses keywords outside the supported
    subset, declares an inconsistent ``$id``/filename/``schema`` const, or two
    files claim the same schema id.
    """


class UnknownSchemaError(CoreError):
    """A record declares a missing or unregistered schema id."""


class RecordValidationError(CoreError):
    """A record failed validation against its declared schema."""

    def __init__(self, schema_id: str, violations: list[str]) -> None:
        self.schema_id = schema_id
        self.violations = tuple(violations)
        summary = "; ".join(self.violations)
        super().__init__(
            f"record failed schema {schema_id!r} with {len(self.violations)} "
            f"violation(s): {summary}"
        )


class UnsafePathError(CoreError):
    """A path value violates the safe-relative-path rules."""
