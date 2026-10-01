"""Validate private inputs, print only the path allowlist."""

import json
import sys
from pathlib import Path

from ownvoice.config import load_config
from ownvoice.layout import Layout


def run(args):
    config, _ = load_config(args.config)
    paths = Layout(Path(config["paths"]["work_dir"])).resolved_paths(
        config["paths"]["editorial_rules"]
    )
    if args.format == "json":
        print(json.dumps(paths, sort_keys=True))
    elif not args.quiet:
        for key, value in paths.items():
            print(f"{key}: {value}", file=sys.stderr)
    return 0
