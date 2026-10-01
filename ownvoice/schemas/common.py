"""Small recursive validators shared by builders and readers, with field diagnostics."""

import math
import re
from copy import deepcopy
from datetime import datetime

from ownvoice.config import CLASSES, read_toml
from ownvoice.errors import DiagnosticError, ValidationErrors
from ownvoice.io import PRIVATE_KEY, PRIVATE_VALUE


def enum(*values):
    return ("enum", values)


def array(item):
    return ("array", item)


def mapping(item):
    return ("mapping", item)


def registers(item):
    return ("registers", item)


def nullable(item):
    return ("nullable", item)


def optional(item):
    return ("optional", item)


def bounded(kind, minimum, maximum=None):
    return ("bounded", (kind, minimum, maximum))


TEXT = str
COUNT = bounded(int, 0)
POSITIVE = bounded(int, 1)
NUMBER = (int, float)
RATE = bounded(NUMBER, 0)
SHARE = bounded(NUMBER, 0, 1)
SHA256 = ("pattern", r"[a-f0-9]{64}")
RECORD_ID = ("pattern", r"[a-f0-9]{16}")
LABEL = ("pattern", r"[a-z0-9-]{1,32}")
REGISTER = enum(*CLASSES, "article", "_global")
THREAD = enum("new", "reply", "forward")
STAGES = dict.fromkeys(("smtp", "x500", "names", "unknown"), COUNT)
FINGERPRINT = {
    "size": COUNT,
    "mtime_ns": COUNT,
    "first_sha256": nullable(SHA256),
    "last_sha256": nullable(SHA256),
}
READER = {"reader": enum("pffexport", "readpst"), "reader_version": str}
PROVENANCE = {
    PRIVATE_KEY: enum(PRIVATE_VALUE),
    "schema_version": enum(1),
    "tool_version": str,
    "generated_at": ("utc", None),
    "config_digest": SHA256,
    "scrub_digests": optional(dict.fromkeys(("sensitive_terms", "deny_terms_file"), SHA256)),
    "domain_map_digest": SHA256,
    "rules_sha256": SHA256,
    "readers": mapping(READER),
}


def check(value, spec, field, errors):
    def fail(expected, observed="missing or invalid value"):
        errors.append(
            DiagnosticError(
                "validate artefact",
                field,
                observed,
                expected,
                None,
                f"correct field {field} using its version-one schema",
            )
        )

    if isinstance(spec, dict):
        if not isinstance(value, dict):
            fail("an object")
            return
        for key, child in spec.items():
            is_optional = isinstance(child, tuple) and child[0] == "optional"
            if key not in value:
                if not is_optional:
                    errors.append(
                        DiagnosticError(
                            "validate artefact",
                            f"{field}.{key}",
                            "field is missing",
                            "a required field",
                            None,
                            f"supply field {key}",
                        )
                    )
            else:
                check(value[key], child, f"{field}.{key}", errors)
        for key in value.keys() - spec.keys():
            # Do not echo arbitrary unknown keys, which may contain private content.
            fail("only schema-defined fields", "unknown field at object boundary")
        return
    if isinstance(spec, tuple) and isinstance(spec[0], str):
        kind, detail = spec
        if kind in ("optional", "nullable"):
            if kind == "nullable" and value is None:
                return
            check(value, detail, field, errors)
        elif kind == "enum":
            if not any(type(value) is type(item) and value == item for item in detail):
                fail("one of " + repr(detail))
        elif kind in ("array", "mapping", "registers"):
            expected_type = list if kind == "array" else dict
            if not isinstance(value, expected_type):
                fail("an array" if kind == "array" else "an object")
            else:
                if kind == "registers":
                    for key in value:
                        if key not in (*CLASSES, "article", "_global"):
                            fail(
                                "a known recipient class, article or _global",
                                "unknown register key",
                            )
                items = enumerate(value) if kind == "array" else enumerate(value.values())
                for index, child in items:
                    check(child, detail, f"{field}[{index}]", errors)
        elif kind == "bounded":
            expected_type, minimum, maximum = detail
            types = expected_type if isinstance(expected_type, tuple) else (expected_type,)
            if (
                type(value) not in types
                or not math.isfinite(value)
                or value < minimum
                or (maximum is not None and value > maximum)
            ):
                fail(
                    f"{expected_type} in {minimum}..{maximum if maximum is not None else 'unbounded'}"
                )
        elif kind == "pattern":
            if not isinstance(value, str) or not re.fullmatch(detail, value):
                fail(detail)
        elif kind == "tuple_array":
            if not isinstance(value, list) or len(value) != len(detail):
                fail(f"an array of {len(detail)} items")
            else:
                for index, (item, child) in enumerate(zip(value, detail)):
                    check(item, child, f"{field}[{index}]", errors)
        elif kind == "utc":
            try:
                parsed = datetime.fromisoformat(value)
                if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
                    fail("UTC ISO-8601 timestamp")
            except (ValueError, TypeError):
                fail("UTC ISO-8601 timestamp")
        return
    types = spec if isinstance(spec, tuple) else (spec,)
    if type(value) not in types or (type(value) is float and not math.isfinite(value)):
        fail(" or ".join(t.__name__ for t in types))


def validate(value, spec, name, extra=None):
    errors = []
    check(value, spec, name, errors)
    if not errors and extra:
        extra(value, errors)
    if errors:
        raise ValidationErrors(errors)
    return value


def build(fields, spec, name, extra=None):
    value = deepcopy(fields)
    if PRIVATE_KEY in spec:
        value[PRIVATE_KEY] = PRIVATE_VALUE
    return validate(value, spec, name, extra)


def load_manifest(path, validator):
    data, _ = read_toml(path)
    return validator(data)


def constraint(errors, field, ok, expected):
    if not ok:
        errors.append(
            DiagnosticError(
                "validate artefact",
                field,
                "constraint not satisfied",
                expected,
                None,
                f"correct field {field}",
            )
        )


QUANTILES = {key: NUMBER for key in ("mean", "p10", "p25", "p50", "p75", "p90")}
LINT_BAND = {key: NUMBER for key in ("p10", "p25", "p75", "p90")}
LINT_BAND.update(n_gated=COUNT, fallback_global=bool)
METRIC = {**QUANTILES, "nonzero_share": SHARE, "lint_band": LINT_BAND}
FORM = {"form": str, "count": COUNT, "share": SHARE}
SPELLING = dict.fromkeys(("ise", "ize", "our", "or"), COUNT)


# Arrays of positional tuples are described explicitly rather than accepting arbitrary lists.
def tuple_array(*items):
    return ("tuple_array", items)
