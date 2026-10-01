"""Installed shared entry point, with the adapter chosen by its SKILL.md."""

import sys
from pathlib import Path

from ownvoice.qual.dispatch import main

if __name__ == "__main__":
    raise SystemExit(main(["--prompt", str(Path(__file__).with_name("PROMPT.md")), *sys.argv[1:]]))
