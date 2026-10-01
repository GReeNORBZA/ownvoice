"""TOML configuration boundary: collect all errors without printing identities."""

import re
import tomllib
from copy import deepcopy
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from ownvoice.errors import DiagnosticError, ExitCode, ValidationErrors
from ownvoice.layout import LABEL_PATTERN

CLASSES = (
    "personal",
    "professional-warm",
    "colleague",
    "client",
    "vendor",
    "cold",
    "group",
    "unknown",
)
# Draft media for lint, rules and write-in-voice. "article" is the long-form
# medium; blog, linkedin, doc and proposal remain for existing rules files.
MEDIA = ("email", "article", "blog", "linkedin", "doc", "proposal")
PRECEDENCE = ("cold", "client", "vendor", "professional-warm", "colleague", "personal", "unknown")
DEFAULT_READER = "pffexport"
DEFAULTS = {
    "ingest": {
        "sent_folders": ["Sent Items", "Sent", "Sent Mail"],
        "readpst_jobs": 0,
        "checkpoint_every": 500,
        "mobile_footers": [
            "Sent from my iPhone",
            "Sent from my iPad",
            "Get Outlook for iOS",
            "Get Outlook for Android",
        ],
        "valedictions": [
            "Kind regards",
            "Regards",
            "Best",
            "Thanks",
            "Thank you",
            "Cheers",
            "Speak soon",
        ],
        "reply_prefixes": ["RE:", "Re:", "AW:", "SV:", "RV:", "Antw:"],
        "takeout_excluded_labels": ["Chat", "Drafts", "Spam", "Trash"],
        "extra_attribution_patterns": [],
        "deny_terms_file": "",
        "sensitive_terms": "builtin",
        "softeners": "",
    },
    "profile": {
        "exemplars_min": 10,
        "exemplars_max": 20,
        "exemplar_words_per_register": 800,
        "token_budget": 25000,
        "thin_register_min": 30,
        "current_source": "",
        "never_hit_min_words": 50000,
        "qual_sample_words": 5000,
        "qual_max_record_words": 2000,
        "qual_retries": 2,
        "llm_ism_lexicon": "",
    },
    "llm": {"provider": "", "retention_terms": "", "training_use": "", "attestation": ""},
}


def read_toml(path):
    path = Path(path).expanduser().resolve()
    try:
        text = path.read_text(encoding="utf-8")
        return tomllib.loads(text), text
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ValidationErrors(
            [
                DiagnosticError(
                    "load TOML",
                    path,
                    str(exc),
                    "a readable UTF-8 TOML document",
                    exc,
                    "correct the file and retry config show",
                )
            ]
        ) from exc


def _line_map(text):
    """Track table/key positions, including each repeated source table."""
    lines, table, source_index = {}, "", -1
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("[[source]]"):
            source_index += 1
            table = f"source[{source_index}]"
            lines[table] = number
        elif re.match(r"^\[[^\[].*\]", stripped):
            table = stripped[1 : stripped.index("]")].strip()
            lines[table] = number
        elif "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip().strip("\"'")
            lines[f"{table}.{key}" if table else key] = number
    return lines


class _Validator:
    def __init__(self, path, text):
        self.path, self.lines, self.errors = path, _line_map(text), []

    def error(
        self, key, observed, expected, cause=None, *, identity_key=None, exit_code=ExitCode.OPERATOR
    ):
        line = self.lines.get(key, self.lines.get(key.rsplit(".", 1)[0], 1))
        self.errors.append(
            DiagnosticError(
                "validate config",
                f"{self.path} {identity_key or key} line {line}",
                observed,
                expected,
                cause,
                f"fix {identity_key or key} at line {line} and retry config show",
                exit_code=exit_code,
            )
        )

    def check(self, ok, key, expected):
        if not ok:
            self.error(key, "missing or invalid value", expected)
        return ok

    def table(self, data, key, *, required=False):
        value = data.get(key, {} if not required else None)
        if not self.check(isinstance(value, dict), key, "a TOML table"):
            return {}
        return value

    def strings(self, value, key, *, nonempty=False):
        return self.check(
            isinstance(value, list)
            and (bool(value) or not nonempty)
            and all(isinstance(x, str) and x.strip() for x in value),
            key,
            "a list of nonempty strings" + (" with at least one entry" if nonempty else ""),
        )

    def timezone(self, value, key):
        if not self.check(isinstance(value, str) and bool(value), key, "an IANA timezone key"):
            return
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            self.error(
                key,
                "timezone not found",
                "an IANA timezone key, e.g. America/Edmonton",
                exc,
                exit_code=ExitCode.OPERATOR if available_timezones() else ExitCode.DEPENDENCY,
            )


def llm_completeness(llm):
    """Missing fields, including a valid ISO date in the owner's attestation."""
    if not isinstance(llm, dict):
        return list(DEFAULTS["llm"])
    missing = [
        key for key in DEFAULTS["llm"] if not isinstance(llm.get(key), str) or not llm[key].strip()
    ]
    if "attestation" not in missing:
        match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", llm["attestation"])
        try:
            date.fromisoformat(match[0] if match else "")
        except ValueError:
            missing.append("attestation")
    return missing


def validate_config(data, *, path="config.toml", text=""):
    v = _Validator(path, text)
    if not isinstance(data, dict):
        v.error("config", "non-table input", "a TOML document")
        raise ValidationErrors(v.errors)
    v.check(
        type(data.get("schema_version")) is int and data.get("schema_version") == 1,
        "schema_version",
        "integer 1",
    )
    owner = v.table(data, "owner", required=True)
    v.strings(owner.get("addresses"), "owner.addresses", nonempty=True)
    v.strings(owner.get("names"), "owner.names", nonempty=True)
    v.timezone(owner.get("timezone"), "owner.timezone")
    paths = v.table(data, "paths", required=True)
    for key in paths.keys() - {"work_dir", "domain_map", "editorial_rules"}:
        v.error("paths", "unknown path field", "work_dir, domain_map and editorial_rules only")
    for key in ("work_dir", "domain_map", "editorial_rules"):
        v.check(
            isinstance(paths.get(key), str) and bool(paths[key].strip()),
            f"paths.{key}",
            "a nonempty path",
        )
    sources = data.get("source")
    if not v.check(
        isinstance(sources, list) and bool(sources), "source", "at least one [[source]] table"
    ):
        sources = []
    labels, eligible = [], False
    for index, source in enumerate(sources):
        prefix = f"source[{index}]"
        if not v.check(isinstance(source, dict), prefix, "a source table"):
            continue
        label = source.get("label")
        valid_label = isinstance(label, str) and re.fullmatch(LABEL_PATTERN, label)
        if v.check(bool(valid_label), f"{prefix}.label", LABEL_PATTERN):
            v.check(label not in labels, f"{prefix}.label", "a unique label")
            labels.append(label)
        v.check(source.get("kind") in ("pst", "mbox", "eml"), f"{prefix}.kind", "pst, mbox or eml")
        v.check(
            isinstance(source.get("path"), str) and bool(source["path"].strip()),
            f"{prefix}.path",
            "a nonempty path",
        )
        if "reader" in source:
            v.check(
                source.get("kind") == "pst" and source["reader"] in ("pffexport", "readpst"),
                f"{prefix}.reader",
                "pffexport or readpst, for pst only",
            )
        for key in ("allow_inside_git_tree", "llm_eligible"):
            v.check(type(source.get(key, False)) is bool, f"{prefix}.{key}", "a boolean")
        eligible |= source.get("llm_eligible") is True
        if "timezone" in source:
            v.timezone(source["timezone"], f"{prefix}.timezone")
        for key in ("owner_addresses", "sent_folders"):
            if key in source:
                v.strings(source[key], f"{prefix}.{key}", nonempty=key == "sent_folders")
        if "era" in source:
            era = source["era"]
            v.check(
                isinstance(era, dict)
                and all(
                    type(era.get(k)) is int and 1 <= era[k] <= 9999
                    for k in ("from_year", "to_year")
                )
                and era["from_year"] <= era["to_year"],
                f"{prefix}.era",
                "from_year <= to_year, both integers in 1..9999",
            )
    for section in ("ingest", "profile"):
        table = v.table(data, section)
        for key, default in DEFAULTS[section].items():
            value = table.get(key, default)
            field = f"{section}.{key}"
            if isinstance(default, list):
                v.strings(value, field, nonempty=key == "sent_folders")
            elif isinstance(default, int):
                minimum = 0 if key in ("readpst_jobs", "qual_retries") else 1
                v.check(type(value) is int and value >= minimum, field, f"an integer >= {minimum}")
            else:
                v.check(isinstance(value, str), field, "a string")
        if section == "ingest":
            patterns = table.get("extra_attribution_patterns", [])
            if isinstance(patterns, list):
                for index, pattern in enumerate(patterns):
                    if isinstance(pattern, str):
                        try:
                            re.compile(pattern)
                        except re.error as exc:
                            v.error(
                                "ingest.extra_attribution_patterns",
                                f"regex {index} does not compile",
                                "valid regular expressions",
                                exc,
                            )
            v.check(
                table.get("sensitive_terms", "builtin") != "",
                "ingest.sensitive_terms",
                "builtin, none, or a path",
            )
        else:
            low, high = table.get("exemplars_min", 10), table.get("exemplars_max", 20)
            if type(low) is int and type(high) is int:
                v.check(low <= high, "profile.exemplars_max", "exemplars_max >= exemplars_min")
            current = table.get("current_source", "")
            if isinstance(current, str):
                v.check(
                    not current or current in labels,
                    "profile.current_source",
                    "an existing source label or empty string",
                )
            # Optional, no default: an absent key leaves the config digest unchanged.
            if "baseline_before" in table:
                cutoff = table["baseline_before"]
                valid = isinstance(cutoff, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", cutoff)
                if valid:
                    try:
                        date.fromisoformat(cutoff)
                    except ValueError:
                        valid = False
                v.check(
                    bool(valid),
                    "profile.baseline_before",
                    'an ISO date string "YYYY-MM-DD" (omit the key for no cutoff)',
                )
    llm = data.get("llm", {})
    if eligible:
        missing = llm_completeness(llm)
        if missing:
            v.error(
                "llm",
                "incomplete [llm]: " + ", ".join(missing),
                "provider, retention_terms, training_use and a dated attestation when llm_eligible = true",
            )
    else:
        llm = v.table(data, "llm")
        for key in DEFAULTS["llm"]:
            if key in llm:
                v.check(isinstance(llm[key], str), f"llm.{key}", "a string")
    if v.errors:
        raise ValidationErrors(v.errors)
    result = deepcopy(data)
    for section, defaults in DEFAULTS.items():
        result[section] = {**deepcopy(defaults), **result.get(section, {})}
    for source in result["source"]:
        source.setdefault("llm_eligible", False)
        source.setdefault("allow_inside_git_tree", False)
        source.setdefault("owner_addresses", [])
        source.setdefault("timezone", owner["timezone"])
        source.setdefault("sent_folders", result["ingest"]["sent_folders"].copy())
        if source["kind"] == "pst":
            source.setdefault("reader", DEFAULT_READER)
    result["profile"]["current_source"] = result["profile"]["current_source"] or labels[-1]
    return result


def validate_domain_map(data, *, path="domain-map.toml", text=""):
    v = _Validator(path, text)
    if not isinstance(data, dict):
        v.error("domain-map", "non-table input", "a TOML document")
        raise ValidationErrors(v.errors)
    v.check(
        type(data.get("schema_version")) is int and data.get("schema_version") == 1,
        "schema_version",
        "integer 1",
    )
    classes = data.get("classes", list(CLASSES))
    classes_valid = v.strings(classes, "classes", nonempty=True)
    if classes_valid:
        classes_valid = v.check(
            len(set(classes)) == len(classes) and set(classes) == set(CLASSES),
            "classes",
            "each recipient class exactly once, including colleague",
        )
    precedence = data.get("precedence", list(PRECEDENCE))
    if v.strings(precedence, "precedence", nonempty=True):
        v.check(
            len(set(precedence)) == len(precedence) and set(precedence) == set(PRECEDENCE),
            "precedence",
            "each non-group class exactly once",
        )
    threshold = data.get("group_threshold", 4)
    v.check(type(threshold) is int and threshold >= 1, "group_threshold", "an integer >= 1")
    for section in ("addresses", "domains", "x500", "names"):
        table = v.table(data, section)
        seen = set()
        for index, (key, value) in enumerate(table.items()):
            # A line number identifies the private entry without leaking its key.
            identity = f"{section}[entry {index + 1}]"
            if not isinstance(value, str) or value not in (classes if classes_valid else CLASSES):
                v.error(
                    f"{section}.{key}",
                    "unknown recipient class",
                    "a class listed in classes",
                    identity_key=identity,
                )
            if not key.strip() or key.casefold() in seen:
                v.error(
                    f"{section}.{key}",
                    "empty or case-insensitive duplicate key",
                    "a nonempty unique key",
                    identity_key=identity,
                )
            seen.add(key.casefold())
    if v.errors:
        raise ValidationErrors(v.errors)
    return {
        "schema_version": 1,
        "classes": list(classes),
        "precedence": list(precedence),
        "group_threshold": threshold,
        **{
            key: {k.casefold(): val for k, val in data.get(key, {}).items()}
            for key in ("addresses", "domains", "x500", "names")
        },
    }


def _resolve(value, base):
    path = Path(value).expanduser()
    return str((base / path).resolve() if not path.is_absolute() else path.resolve())


def load_config(path):
    path = Path(path).expanduser().resolve()
    data, text = read_toml(path)
    errors, config, domain_map = [], None, None
    try:
        config = validate_config(data, path=path, text=text)
    except ValidationErrors as exc:
        errors.extend(exc.errors)
    raw_paths = data.get("paths", {})
    map_path = raw_paths.get("domain_map") if isinstance(raw_paths, dict) else None
    if isinstance(map_path, str) and map_path.strip():
        resolved = _resolve(map_path, path.parent)
        try:
            map_data, map_text = read_toml(resolved)
            domain_map = validate_domain_map(map_data, path=resolved, text=map_text)
        except ValidationErrors as exc:
            errors.extend(exc.errors)
    if errors:
        raise ValidationErrors(errors)
    config["paths"] = {key: _resolve(value, path.parent) for key, value in config["paths"].items()}
    for source in config["source"]:
        source["path"] = _resolve(source["path"], path.parent)
    for section, keys in {
        "ingest": ("deny_terms_file", "softeners", "sensitive_terms"),
        "profile": ("llm_ism_lexicon",),
    }.items():
        for key in keys:
            value = config[section][key]
            if value and not (key == "sensitive_terms" and value in ("builtin", "none")):
                config[section][key] = _resolve(value, path.parent)
    return config, domain_map
