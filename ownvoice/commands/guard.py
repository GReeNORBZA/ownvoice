import hashlib
import sys
from pathlib import Path

from ownvoice.errors import DiagnosticError, ExitCode
from ownvoice.guard import read_bytes, scan
from ownvoice.guard.rules import without_allowed


def run(args):
    if args.release and not args.names_file:
        raise DiagnosticError(
            "check release boundary",
            "guard --names-file",
            "no names file supplied",
            "a private names file for release checks",
            None,
            "supply --names-file PATH",
        )
    names = ()
    if args.names_file:
        path = Path(args.names_file).expanduser()
        try:
            names = tuple(
                line.strip()
                for line in read_bytes(path).decode("utf-8").splitlines()
                if line.strip()
            )
            names = without_allowed(names, path)
        except UnicodeError as exc:
            raise DiagnosticError(
                "read guard names",
                path,
                str(exc),
                "UTF-8 names, one per line",
                exc,
                "encode the private names file as UTF-8 and retry",
            ) from exc
    violations = scan(args.tree or ".", staged=args.staged, names=names, release=args.release)
    for path, rule in violations:
        args.logger.event(
            record_id=hashlib.sha256(path.encode()).hexdigest()[:16], rule_id=f"guard.rule{rule}"
        )
        print(
            DiagnosticError(
                "check publish boundary",
                path,
                f"rule {rule} violation",
                "publishable content",
                None,
                "remove the private material from this path and retry guard",
                exit_code=ExitCode.GUARD,
            ),
            file=sys.stderr,
        )
    return int(ExitCode.GUARD if violations else ExitCode.OK)
