"""Claude Workflow entry point for source-tree execution."""

import sys
from pathlib import Path

from ownvoice.qual.dispatch import main

if __name__ == "__main__":
    prompt = Path(__file__).resolve().parents[3] / "skills/voice-profile-build/PROMPT.md"
    raise SystemExit(main(["--adapter", "claude", "--prompt", str(prompt), *sys.argv[1:]]))
