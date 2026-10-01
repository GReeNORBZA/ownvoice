#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 - "$root" "$@" <<'PY'
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

root = Path(sys.argv.pop(1))
sys.path.insert(0, str(root))
from ownvoice.cli import Parser
from ownvoice.config import load_config
from ownvoice.errors import DiagnosticError, ValidationErrors


def reject(identity, observed, expected, next_step):
    raise DiagnosticError("install skills", identity, observed, expected, None, next_step)


def main():
    parser = Parser(prog="install-skills.sh", description="Copy ownvoice skills and rules")
    parser.add_argument("--claude-dir")
    parser.add_argument("--codex-dir")
    parser.add_argument("--profile-dir")
    parser.add_argument("--rules", choices=("owner", "template"), default="template")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    harnesses = [(h, d) for h, d in (("claude", args.claude_dir), ("codex", args.codex_dir)) if d]
    if not harnesses:
        reject("install-skills.sh", "no harness directory given",
               "--claude-dir, --codex-dir or both", "supply at least one skill directory")
    config_path = Path(os.environ.get("OWNVOICE_CONFIG", "~/.config/ownvoice/config.toml")).expanduser()
    if config_path.exists() or "OWNVOICE_CONFIG" in os.environ:
        config, _ = load_config(config_path)
        rules_target = Path(config["paths"]["editorial_rules"])
    elif args.profile_dir:
        rules_target = Path(args.profile_dir).expanduser().absolute() / "editorial-rules.md"
    else:
        reject(config_path, "configuration absent and --profile-dir omitted",
               "configured editorial_rules or a bootstrap profile directory",
               "set OWNVOICE_CONFIG or supply --profile-dir")

    # Preflight every destination before the first copy.
    copies = []
    for harness, directory in harnesses:
        base = Path(directory).expanduser().absolute()
        for source in sorted((root / "skills").iterdir()):
            if not source.is_dir():
                continue
            target = base / source.name
            if target.is_symlink():
                reject(target, "symlink destination", "a real directory",
                       "choose a non-symlink skill destination")
            if rules_target.resolve() == target.resolve() or target.resolve() in rules_target.resolve().parents:
                reject(rules_target, "editorial rules overlap an installed skill directory",
                       "a separate editorial rules destination",
                       "set editorial_rules or --profile-dir outside the skill directories")
            if target.exists() and not target.is_dir():
                reject(target, "non-directory destination", "a skill directory",
                       "choose a directory destination")
            if target.exists() and not (target / ".ownvoice-installed").is_file() and not args.force:
                reject(target, "existing unstamped directory", ".ownvoice-installed stamp",
                       "choose another directory or use --force after reviewing its contents")
            # Never follow existing nested symlinks during a copy, even with force.
            if target.exists() and any(p.is_symlink() for p in target.rglob("*")):
                reject(target, "nested symlink", "a destination without symlinks",
                       "remove the destination symlinks or choose another directory")
            if source.resolve() == target.resolve() or source.resolve() in target.resolve().parents:
                reject(target, "destination overlaps source", "a separate installation directory",
                       "choose a directory outside the source skill")
            adapter = root / "adapters" / harness / source.name / "SKILL.md"
            copies.append((source, target, adapter))
    # A release tarball or wheel has no git metadata; the stamp then carries no SHA.
    try:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True)
        sha = head.stdout.strip() if head.returncode == 0 else None
    except FileNotFoundError:
        sha = None  # git not installed
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    stamp = json.dumps({"tool_version": version, "git_sha": sha}, sort_keys=True) + "\n"
    for source, target, adapter in copies:
        if args.verbose:
            print(f"install skills [{target}]: copying {source}", file=sys.stderr)
        shutil.copytree(source, target, dirs_exist_ok=True, symlinks=False)
        if adapter.is_file():
            shutil.copyfile(adapter, target / "SKILL.md")
        (target / ".ownvoice-installed").write_text(stamp)
    selected = "editorial-rules.md" if args.rules == "owner" else "editorial-rules.TEMPLATE.md"
    rules_target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves even a concurrently created file or dangling symlink.
    try:
        with rules_target.open("xb") as output:
            output.write((root / "skills" / "editorial-rules" / selected).read_bytes())
    except FileExistsError:
        pass  # Required no-overwrite behavior, including --force.
    print(f"Installed {len(copies)} skill directories; editorial rules: {rules_target}")


try:
    main()
except (DiagnosticError, ValidationErrors) as exc:
    print(str(exc), file=sys.stderr)
    sys.exit(int(exc.exit_code))
except (OSError, subprocess.CalledProcessError, ValueError) as exc:
    cause = exc.stderr if isinstance(exc, subprocess.CalledProcessError) else str(exc)
    print(DiagnosticError("install skills", getattr(exc, "filename", None) or root,
          str(exc), "readable sources and writable destinations", cause,
          "check the named path, git checkout and permissions, then retry with --verbose"), file=sys.stderr)
    sys.exit(3)
PY
