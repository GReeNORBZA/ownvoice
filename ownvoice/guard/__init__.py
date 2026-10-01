"""Git-index and filesystem selection, and pre-commit hook installation."""

import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from ownvoice.errors import DiagnosticError, ExitCode
from ownvoice.guard.rules import artifact_name, content_rules
from ownvoice.io import has_private_marker

RELEASE_EXCLUDED_DIRS = ("docs/frd/", "docs/prompts/", "docs/testing/")


def git(root, *arguments):
    try:
        return subprocess.run(
            ["git", "-C", str(root), *arguments], capture_output=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = (
            exc.stderr.decode(errors="replace")
            if isinstance(exc, subprocess.CalledProcessError)
            else str(exc)
        )
        raise DiagnosticError(
            "read git publish boundary",
            root,
            detail,
            "successful git " + arguments[0],
            exc,
            "check the repository and index, then retry guard",
            exit_code=ExitCode.DEPENDENCY,
        ) from exc


def read_bytes(path):
    try:
        return path.read_bytes()
    except OSError as exc:
        raise DiagnosticError(
            "read guard input",
            path,
            str(exc),
            "a readable file",
            exc,
            "check the path and permissions, then retry guard",
            exit_code=ExitCode.DEPENDENCY,
        ) from exc


def scan(root, *, staged=False, names=(), release=False):
    root = Path(root).resolve()
    if not root.is_dir():
        raise DiagnosticError(
            "select guard tree",
            root,
            "directory does not exist",
            "an existing directory",
            None,
            "supply --tree with an existing directory",
        )
    in_git = any((p / ".git").exists() for p in (root, *root.parents))
    if staged or in_git:
        if staged:
            root = Path(os.fsdecode(git(root, "rev-parse", "--show-toplevel")).strip())
        paths = {os.fsdecode(p) for p in git(root, "ls-files", "-z", "--cached").split(b"\0") if p}
    else:
        paths = {
            p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() or p.is_symlink()
        }
    violations = []
    # Internal design, handover and quality-ledger trees never reach a public release.
    for internal in RELEASE_EXCLUDED_DIRS:
        if release and (
            any(p.startswith(internal) for p in paths)
            or (not staged and (root / internal).is_dir())
        ):
            violations.append((internal, 5))
    # Snapshot index bytes in a private temporary file so one parser handles markers.
    with tempfile.TemporaryDirectory(prefix="ownvoice-guard-") as temporary:
        snapshot = Path(temporary) / "content"
        snapshot.touch(mode=0o600)
        for name in sorted(paths):
            if artifact_name(name, paths):
                violations.append((name, 1))
            path = root / name
            data = (
                git(root, "show", ":" + name)
                if staged
                else (os.fsencode(os.readlink(path)) if path.is_symlink() else read_bytes(path))
            )
            snapshot.write_bytes(data)
            if has_private_marker(snapshot):
                violations.append((name, 2))
            violations.extend(
                (name, rule)
                for rule in content_rules(data.decode("utf-8", errors="replace"), names, release)
            )
    return violations


def hook_main():
    """Discover the private names list at commit time, including lists created later."""
    from ownvoice.cli import main
    from ownvoice.config import load_config
    from ownvoice.errors import ValidationErrors
    from ownvoice.layout import Layout

    config_path = Path(
        os.environ.get("OWNVOICE_CONFIG", "~/.config/ownvoice/config.toml")
    ).expanduser()
    try:
        if config_path.exists():
            config, _ = load_config(config_path)
            work_dir = Path(config["paths"]["work_dir"])
        else:
            work_dir = Path("~/.local/share/ownvoice").expanduser()
        names = Layout(work_dir).names
        arguments = ["guard", "--staged"]
        if names.exists():
            arguments.extend(("--names-file", str(names)))
        return main(arguments)
    except (DiagnosticError, ValidationErrors) as exc:
        print(str(exc), file=sys.stderr)
        return int(exc.exit_code)


def install_hook():
    root = Path.cwd()
    try:
        hook = Path(os.fsdecode(git(root, "rev-parse", "--git-path", "hooks/pre-commit")).strip())
        content = (
            "#!/bin/sh\n# ownvoice publish-boundary hook\nexec "
            + shlex.quote(sys.executable)
            + " -c "
            + shlex.quote("from ownvoice.guard import hook_main; raise SystemExit(hook_main())")
            + "\n"
        )
        if hook.exists() and hook.read_text() != content:
            raise DiagnosticError(
                "install pre-commit hook",
                hook.resolve(),
                "an existing different hook",
                "no hook or the identical ownvoice hook",
                None,
                "integrate the existing hook explicitly before installing",
            )
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(content)
        hook.chmod(0o755)
        print(f"Installed ownvoice hook: {hook.resolve()}")
        return 0
    except OSError as exc:
        error = DiagnosticError(
            "install pre-commit hook",
            root,
            str(exc),
            "a writable git hooks directory",
            exc,
            "check repository permissions and retry the installer",
            exit_code=ExitCode.DEPENDENCY,
        )
        print(str(error), file=sys.stderr)
        return int(error.exit_code)
    except DiagnosticError as exc:
        print(str(exc), file=sys.stderr)
        return int(exc.exit_code)
