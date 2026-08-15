"""Domain-neutral records, hashing, lineage, and publication invariants."""

from ._canonical import canonical_bytes, canonical_sha256
from ._errors import (
    CoreError,
    RecordValidationError,
    SchemaDefinitionError,
    StrictJsonError,
    UnknownSchemaError,
    UnsafePathError,
)
from ._paths import validate_safe_relative_path
from ._strict_json import load_strict_json
from .records import Record, load_record

__all__ = [
    "CoreError",
    "Record",
    "RecordValidationError",
    "SchemaDefinitionError",
    "StrictJsonError",
    "UnknownSchemaError",
    "UnsafePathError",
    "canonical_bytes",
    "canonical_sha256",
    "load_record",
    "load_strict_json",
    "validate_safe_relative_path",
]
