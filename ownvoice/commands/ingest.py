"""CLI adapter for bounded mbox/eml ingestion."""

from ownvoice.config import load_config
from ownvoice.ingest.run import run as ingest


def run(args):
    config, domain_map = load_config(args.config)
    return ingest(config, domain_map, args)
