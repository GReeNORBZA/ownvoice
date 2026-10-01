#!/usr/bin/env bash
set -euo pipefail
exec python3 -c 'from ownvoice.guard import install_hook; raise SystemExit(install_hook())'
