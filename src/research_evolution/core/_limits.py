"""Frozen protocol limits shared by the strict parser and canonicalizer.

These constants are part of the wire-format contract. They must never be
derived from runtime-adjustable interpreter settings such as
``PYTHONINTMAXSTRDIGITS`` / ``sys.set_int_max_str_digits()``: the same
record must be valid or invalid on every machine, otherwise hashes and
validation outcomes stop being reproducible.
"""

# Nesting budget for parsed documents and canonical inputs. A data
# property, not a function of the interpreter recursion limit; the
# canonical serializer is iterative so this budget never touches the C
# stack.
MAX_WALK_DEPTH = 500

# Maximum decimal digits of an integer literal / programmatic int.
MAX_INT_DIGITS = 4300
INT_LIMIT = 10 ** MAX_INT_DIGITS

# Maximum absolute adjusted exponent of a Decimal (position of its most
# significant digit). Bounds the canonical string size of values like
# 1e4299 (fine) versus 1e999999999 (would amplify into a gigabyte).
MAX_DECIMAL_SCALE = 4300
