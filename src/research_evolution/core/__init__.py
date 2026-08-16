"""Domain-neutral records, hashing, lineage, and publication invariants."""

from ._canonical import canonical_bytes, canonical_sha256
from ._errors import (
    CoreError,
    PublicationError,
    RecordValidationError,
    SchemaDefinitionError,
    StoreIntegrityError,
    StrictJsonError,
    UnknownSchemaError,
    UnsafePathError,
)
from ._paths import validate_safe_relative_path
from ._strict_json import load_strict_json
from .publication import (
    GraphVerificationReport,
    PublicationReceipt,
    publish_record,
    verify_record_graph,
)
from .records import Record, load_record

__all__ = [
    "CoreError",
    "GraphVerificationReport",
    "PublicationError",
    "PublicationReceipt",
    "Record",
    "RecordValidationError",
    "SchemaDefinitionError",
    "StoreIntegrityError",
    "StrictJsonError",
    "UnknownSchemaError",
    "UnsafePathError",
    "canonical_bytes",
    "canonical_sha256",
    "load_record",
    "load_strict_json",
    "publish_record",
    "validate_safe_relative_path",
    "verify_record_graph",
]
