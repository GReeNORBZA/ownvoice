"""Content-bound provenance, independent of private paths and addresses."""

import hashlib
import json
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from ownvoice import __version__
from ownvoice.errors import DiagnosticError, ExitCode


def file_sha256(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        raise DiagnosticError(
            "hash provenance file",
            path,
            str(exc),
            "a readable file",
            exc,
            "check the configured file path and permissions",
            exit_code=ExitCode.DEPENDENCY,
        ) from exc


def input_digests(config):
    """Hash input bytes, including packaged defaults, without retaining paths."""
    ingest, profile = config.get("ingest", {}), config.get("profile", {})
    empty = hashlib.sha256(b"").hexdigest()
    sensitive = ingest.get("sensitive_terms", "builtin")
    builtin = file_sha256(files("ownvoice").joinpath("data", "sensitive.txt"))
    if sensitive == "none":
        sensitive_digest = empty
    elif sensitive == "builtin":
        sensitive_digest = builtin
    else:
        sensitive_digest = hashlib.sha256((builtin + file_sha256(sensitive)).encode()).hexdigest()
    softeners = file_sha256(files("ownvoice").joinpath("data", "softeners.txt"))
    if ingest.get("softeners"):
        softeners = hashlib.sha256(
            (softeners + file_sha256(ingest["softeners"])).encode()
        ).hexdigest()
    return {
        "sensitive_terms": sensitive_digest,
        "deny_terms_file": file_sha256(ingest["deny_terms_file"])
        if ingest.get("deny_terms_file")
        else empty,
        "softeners": softeners,
        "llm_ism_lexicon": file_sha256(
            profile.get("llm_ism_lexicon") or files("ownvoice").joinpath("data", "llm-isms.txt")
        ),
    }


def scrub_digests(config):
    # Scrub reuse must not open measurement inputs before their own validation.
    ingest = config.get("ingest", {})
    inputs = input_digests(
        {
            "ingest": {
                key: ingest[key] for key in ("sensitive_terms", "deny_terms_file") if key in ingest
            }
        }
    )
    return {key: inputs[key] for key in ("sensitive_terms", "deny_terms_file")}


def require_scrub(config, value, label):
    if value.get("scrub_digests") != scrub_digests(config):
        raise DiagnosticError(
            "validate scrub policy",
            label,
            "recorded scrub-list digests are missing or stale",
            "current sensitive_terms and deny_terms_file content digests",
            None,
            f"run ownvoice ingest --reparse {label}",
        )


def require_current(config, value, identity, command):
    if value["config_digest"] != config_digest(config):
        raise DiagnosticError(
            "validate artefact policy",
            identity,
            "recorded config digest is stale",
            "current file-backed input content digests",
            None,
            f"run ownvoice {command} with the current config",
        )


def config_digest(config):
    def normalize(value):
        if isinstance(value, dict):
            return {
                k: normalize(v)
                for k, v in value.items()
                if k
                not in {
                    "paths",
                    "path",
                    "addresses",
                    "owner_addresses",
                    "deny_terms_file",
                    "softeners",
                    "llm_ism_lexicon",
                }
            }
        if isinstance(value, list):
            return [normalize(v) for v in value]
        return value

    normalized = normalize(config)
    digests = input_digests(config)
    normalized.setdefault("ingest", {}).update(
        {key: digests[key] for key in ("sensitive_terms", "deny_terms_file", "softeners")}
    )
    normalized.setdefault("profile", {})["llm_ism_lexicon"] = digests["llm_ism_lexicon"]
    data = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode()).hexdigest()


domain_map_digest = file_sha256
rules_sha256 = file_sha256


def tool_version():
    return __version__


def generated_at():
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def build(config, domain_map, editorial_rules, *, timestamp=None, readers=None):
    return {
        "schema_version": 1,
        "tool_version": tool_version(),
        "generated_at": timestamp or generated_at(),
        "config_digest": config_digest(config),
        "scrub_digests": scrub_digests(config),
        "domain_map_digest": domain_map_digest(domain_map),
        "rules_sha256": rules_sha256(editorial_rules),
        "readers": readers or {},
    }
